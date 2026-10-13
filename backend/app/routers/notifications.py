"""NÖBET — Bildirim uçları (Faz 8)"""
from __future__ import annotations

import datetime as dt
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app import mail, notify, settings_store, sms
from app.config import settings
from app.deps import AdminUser, DbSession, StaffUser
from app.models import Notification, NotificationStatus, PersonGuardian
from app.schemas import ORM, MailTestIn, Page, SmtpIn

router = APIRouter(tags=["notifications"])


class NotificationOut(ORM):
    id: uuid.UUID
    event_id: int
    person_id: uuid.UUID
    person_name: str | None = None
    guardian_id: uuid.UUID
    guardian_name: str | None = None
    channel: str
    recipient: str
    body: str
    status: NotificationStatus
    attempts: int
    last_error: str | None
    scheduled_at: dt.datetime
    sent_at: dt.datetime | None
    created_at: dt.datetime


class NotificationPage(Page):
    items: list[NotificationOut]


class ChannelStatusOut(BaseModel):
    channel: str
    healthy: bool
    detail: str


class GuardianNotifyPatch(BaseModel):
    notify_enabled: bool


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    user: StaffUser,
    db: DbSession,
    status_: NotificationStatus | None = Query(default=None, alias="status"),
    person_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> NotificationPage:
    conds = [Notification.tenant_id == user.tenant_id]
    if status_:
        conds.append(Notification.status == status_)
    if person_id:
        conds.append(Notification.person_id == person_id)

    total = (
        await db.execute(select(func.count()).select_from(Notification).where(*conds))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Notification).where(*conds)
            .order_by(Notification.created_at.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().unique().all()

    return NotificationPage(
        total=total, page=page, size=size,
        items=[NotificationOut.model_validate(n) for n in rows],
    )


@router.get("/notifications/channel", response_model=ChannelStatusOut)
async def channel_status(user: StaffUser, db: DbSession) -> ChannelStatusOut:
    """
    Kanalın gerçekten gönderime hazır olup olmadığı.

    ⚠️ Burası `build_channel()` çağırıyordu — yani **ortam değişkenini**.
    Oysa kanal seçimi Faz 8'de veritabanına taşındı ve Ayarlar sayfasından
    değiştiriliyor. İkisi ayrı kaynak olduğu için kurum kanalı SMS'e
    çevirdiğinde rozet hâlâ WhatsApp'ı yoklardı: gönderim SMS'ten giderken
    panel "WhatsApp bağlı" derdi. Gönderimin kendisi (`flush_pending`)
    zaten veritabanını okuyordu; yanlış olan yalnızca gösterge idi.
    """
    ch = await notify.build_channel_for(db, user.tenant_id)
    ok, detail = await ch.healthy()
    return ChannelStatusOut(channel=ch.name.value, healthy=ok, detail=detail)


@router.get("/notifications/channel/qr")
async def channel_qr(user: AdminUser, db: DbSession) -> Response:
    """
    WhatsApp eşleştirme QR'ını arayüze taşır.

    ⚠️ YALNIZCA YÖNETİCİ. Bu QR'ı okutan kişi KENDİ WhatsApp hesabını
    sisteme bağlar — kurumun tüm veli bildirimleri o hattan gitmeye başlar.
    Operatör veya koç görmemeli.

    Ağ geçidi yalnızca konteyner ağından erişilebilir (127.0.0.1'e bağlı);
    bu uç olmadan QR'a ulaşmak için sunucuya SSH gerekirdi — "sıfır CLI"
    kuralına aykırı.
    """
    # ⚠️ Kanal `settings.notify_channel`'dan (ortam değişkeni) okunuyordu.
    # Kanal seçimi veritabanına taşındıktan sonra bu, kurum WhatsApp'ı
    # arayüzden seçmiş olsa bile QR'ı 409 ile reddedebiliyordu.
    row = await settings_store.get_setting(db, user.tenant_id)
    await db.commit()
    if row.channel != "whatsapp":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"aktif kanal '{row.channel}', WhatsApp değil",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{settings.wa_gateway_url.rstrip('/')}/qr")
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"ağ geçidine ulaşılamıyor: {exc}",
        ) from exc

    if r.status_code == 404:
        # Bağlıyken QR üretilmez — bu bir hata değil
        raise HTTPException(status.HTTP_404_NOT_FOUND, r.text[:200])
    if r.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, r.text[:200])

    return Response(
        content=r.content,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/notifications/{notification_id}/retry",
             response_model=NotificationOut)
async def retry_notification(
    notification_id: uuid.UUID, user: AdminUser, db: DbSession
) -> NotificationOut:
    """Vazgeçilmiş bir bildirimi yeniden kuyruğa alır."""
    n = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.tenant_id == user.tenant_id,
            )
        )
    ).scalars().unique().one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bildirim bulunamadı")
    if n.status == NotificationStatus.sent:
        raise HTTPException(status.HTTP_409_CONFLICT, "bu bildirim zaten gönderildi")

    n.status = NotificationStatus.pending
    n.attempts = 0
    n.last_error = None
    n.scheduled_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(n)
    return NotificationOut.model_validate(n)


@router.patch("/persons/{person_id}/guardians/{guardian_id}/notify",
              status_code=status.HTTP_204_NO_CONTENT)
async def set_guardian_notify(
    person_id: uuid.UUID, guardian_id: uuid.UUID,
    body: GuardianNotifyPatch, user: AdminUser, db: DbSession,
) -> None:
    """Veli bazında bildirim aç/kapa (kontrat §1.3: admin yetkisi)."""
    link = (
        await db.execute(
            select(PersonGuardian).where(
                PersonGuardian.person_id == person_id,
                PersonGuardian.guardian_id == guardian_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bağlantı bulunamadı")

    link.notify_enabled = body.notify_enabled
    await db.commit()


@router.get("/notifications/config", response_model=dict)
async def notify_config(user: StaffUser, db: DbSession) -> dict:
    row = await settings_store.get_setting(db, user.tenant_id)
    await db.commit()
    return {
        **settings_store.public_config(row),
        "max_attempts": settings.notify_max_attempts,
        # Kuru çalışmada mesaj üretilir ve kaydedilir ama GÖNDERİLMEZ
        "dry_run": row.channel == "dryrun",
    }


# ---------------------------------------------------------------------------
# Ayarlar — kanal ve SMS sağlayıcı arayüzden değişir ("sıfır CLI")
# ---------------------------------------------------------------------------
class SettingsPatch(BaseModel):
    channel: str
    sms_provider: str | None = None
    sms_config: dict | None = None
    # Girilirse şifrelenip saklanır; boş bırakılırsa mevcut sır KORUNUR
    sms_user: str | None = None
    sms_password: str | None = None


class TestSendIn(BaseModel):
    to: str
    text: str = "NÖBET test mesajı."


@router.get("/settings/notify", response_model=dict)
async def get_notify_settings(user: AdminUser, db: DbSession) -> dict:
    row = await settings_store.get_setting(db, user.tenant_id)
    await db.commit()
    return {
        **settings_store.public_config(row),
        "presets": {
            k: {kk: vv for kk, vv in v.items()}
            for k, v in sms.PRESETS.items()
        },
        "secret_storage_ready": bool(settings.settings_key),
    }


@router.patch("/settings/notify", response_model=dict)
async def update_notify_settings(
    body: SettingsPatch, user: AdminUser, db: DbSession
) -> dict:
    if body.channel not in ("dryrun", "whatsapp", "sms", "email"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"geçersiz kanal: {body.channel}")

    row = await settings_store.get_setting(db, user.tenant_id)
    row.channel = body.channel
    if body.sms_provider is not None:
        row.sms_provider = body.sms_provider
    if body.sms_config is not None:
        row.sms_config = body.sms_config

    if body.sms_user or body.sms_password:
        try:
            row.secret_enc = settings_store.encrypt_secret({
                "user": body.sms_user or "",
                "password": body.sms_password or "",
            })
        except settings_store.SecretUnavailable as exc:
            # Düz metin saklamaktansa reddet
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    row.updated_by = user.id
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(row)
    return settings_store.public_config(row)


@router.post("/settings/notify/test", response_model=dict)
async def test_send(body: TestSendIn, user: AdminUser, db: DbSession) -> dict:
    """
    Ayarları gerçek gönderimle doğrular.

    Sağlayıcı ön ayarları başlangıç noktasıdır; alan adları hesap tipine göre
    değişebilir. Bu uç olmadan yanlış yapılandırma ancak gerçek bir veli
    bildirimi kaybolduğunda fark edilirdi.
    """
    channel = await notify.build_channel_for(db, user.tenant_id)
    try:
        await channel.send(body.to, body.text)
    except Exception as exc:
        return {"ok": False, "channel": channel.name.value, "detail": str(exc)[:400]}
    return {"ok": True, "channel": channel.name.value, "detail": "gönderildi"}


# ---------------------------------------------------------------------------
# SMTP ayarları (kontrat v1.7)
# ---------------------------------------------------------------------------
@router.put("/settings/smtp", response_model=dict)
async def update_smtp(body: SmtpIn, user: AdminUser, db: DbSession) -> dict:
    """
    SMTP yapılandırması. Parola Fernet ile şifrelenir, ayrı sütunda tutulur.

    ⚠️ `password` boş bırakılırsa **kayıtlı parola korunur.** Arayüz mevcut
    parolayı hiç görmediği için (sır dışarı çıkmıyor), her kaydetmede yeniden
    yazmak zorunda kalınsaydı kullanıcı sunucu adresini düzeltmek isterken
    parolayı sessizce silerdi.
    """
    row = await settings_store.get_setting(db, user.tenant_id)

    row.smtp_host = body.host.strip()
    row.smtp_port = body.port
    row.smtp_security = body.security
    row.smtp_from = str(body.from_addr).strip()
    row.smtp_user = (body.user or "").strip() or None

    if body.password:
        try:
            row.smtp_secret_enc = settings_store.encrypt_secret(
                {"password": body.password}
            )
        except settings_store.SecretUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    elif not row.smtp_user:
        # Kimlik doğrulamasız röleye geçildi — eski parolayı taşımanın anlamı
        # yok, kalırsa kafa karıştırır ("parola kayıtlı" der ama kullanılmaz).
        row.smtp_secret_enc = None

    row.updated_by = user.id
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(row)
    return settings_store.public_config(row)


@router.get("/settings/smtp/check", response_model=dict)
async def check_smtp(user: AdminUser, db: DbSession) -> dict:
    """Bağlanıp kimlik doğrular, mesaj GÖNDERMEZ."""
    row = await settings_store.get_setting(db, user.tenant_id)
    await db.commit()
    ok, detail = await mail.verify(settings_store.smtp_config(row))
    return {"ok": ok, "detail": detail}


@router.post("/settings/smtp/test", response_model=dict)
async def test_mail(body: MailTestIn, user: AdminUser, db: DbSession) -> dict:
    """
    Gerçek bir test e-postası gönderir.

    `check` yalnızca bağlantıyı doğrular; teslimatı doğrulamaz. Konut
    IP'lerinden çıkan posta çoğu sağlayıcıda spam'e düşer — bunu ancak
    gerçek gönderim gösterir.
    """
    row = await settings_store.get_setting(db, user.tenant_id)
    await db.commit()
    cfg = settings_store.smtp_config(row)
    try:
        await mail.send_mail(
            cfg, str(body.to), "NÖBET — test e-postası",
            "Bu bir test mesajıdır. Bunu görüyorsanız SMTP ayarlarınız "
            "çalışıyor demektir.\n\n— NÖBET",
        )
    except mail.MailError as exc:
        return {"ok": False, "detail": str(exc)[:400]}
    return {"ok": True, "detail": f"{body.to} adresine gönderildi"}
