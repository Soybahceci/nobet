"""
NÖBET — Bildirim Servisi (Faz 8)
=================================
18 yaş altı öğrenci giriş/çıkış yaptığında veliye bildirim.

Tasarım: kanal soyut. Bildirim mantığı (kuyruk, yeniden deneme, mükerrer
engeli, veli bazında açma/kapama) kanaldan bağımsız. Kanal değişirse
yalnızca adaptör değişir.

⚠️ Prototipte kullanılan WhatsApp kanalı **resmî olmayan** bir ağ geçidine
bağlanıyor (kullanıcı kararı, 2026-08-09). Riskler README'de yazılı.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from abc import ABC, abstractmethod
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import mail, sms, worklock
from app.config import settings
from app.db import SessionLocal
from app.models import (
    AttendanceSession,
    Subscription,
    Event,
    EventDecision,
    Guardian,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Person,
    PersonGuardian,
    Tenant,
    Zone,
)

log = logging.getLogger("nobet.notify")


# ---------------------------------------------------------------------------
# Kanallar
# ---------------------------------------------------------------------------
class Channel(ABC):
    name: NotificationChannel

    @abstractmethod
    async def send(self, recipient: str, body: str) -> None:
        """Başarısızlıkta istisna fırlatır; işçi yeniden dener."""

    async def healthy(self) -> tuple[bool, str]:
        return True, "hazır"


class DryRunChannel(Channel):
    """Gerçekten göndermez, yalnızca loglar. Kanal hazır değilken kullanılır."""

    name = NotificationChannel.dryrun

    async def send(self, recipient: str, body: str) -> None:
        log.info("[KURU ÇALIŞMA] %s -> %s", recipient, body.replace("\n", " | "))

    async def healthy(self) -> tuple[bool, str]:
        return True, "kuru çalışma — mesaj gönderilmiyor"


class WhatsAppChannel(Channel):
    """
    Baileys tabanlı ağ geçidine HTTP ile bağlanır (`wa-gateway` konteyneri).

    ⚠️ Resmî WhatsApp Business API DEĞİL. Numara banlanabilir, oturum
    düşebilir. Kuruma teslimde resmî Cloud API'ye geçilmeli.
    """

    name = NotificationChannel.whatsapp

    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def send(self, recipient: str, body: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(f"{self._base}/send", json={"to": recipient, "text": body})
            if r.status_code >= 400:
                raise RuntimeError(f"ağ geçidi {r.status_code}: {r.text[:200]}")

    async def healthy(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self._base}/status")
                d = r.json()
            if d.get("connected"):
                return True, f"bağlı ({d.get('user') or 'numara bilinmiyor'})"
            return False, d.get("state") or "bağlı değil — QR okutulmalı"
        except Exception as exc:
            return False, f"ağ geçidine ulaşılamıyor: {exc}"


class SmsChannel(Channel):
    """Yapılandırılabilir SMS kanalı — sağlayıcı ayarları veritabanından gelir."""

    name = NotificationChannel.sms

    def __init__(self, config: dict, secret: dict[str, str]) -> None:
        self._config = config or {}
        self._secret = secret or {}

    async def send(self, recipient: str, body: str) -> None:
        await sms.send_sms(self._config, self._secret, recipient, body)

    async def healthy(self) -> tuple[bool, str]:
        if not (self._config.get("url") or "").strip():
            return False, "sağlayıcı adresi tanımlı değil"
        if not self._secret.get("user"):
            return False, "kimlik bilgileri girilmemiş"
        if not (self._config.get("sender") or "").strip():
            return False, "gönderici başlığı tanımlı değil"
        # Sağlayıcıya bakiye sorgusu atmıyoruz: her sağlayıcıda farklı ve
        # gereksiz maliyet. Yapılandırma tamsa hazır sayılır; gerçek
        # doğrulama "Test SMS gönder" ile yapılır.
        return True, f"{self._config.get('provider') or 'SMS'} yapılandırıldı"


class EmailChannel(Channel):
    """
    E-posta kanalı (kontrat v1.7).

    ⚠️ Alıcı `guardian.email` — WhatsApp/SMS'in aksine **zorunlu alan değil.**
    Velinin e-postası yoksa gönderim başarısız olur ve işçi yeniden dener,
    ama tekrar denemek adresi var etmez. Bu yüzden `build_body`/bildirim
    üretimi tarafında e-postası olmayan veliye `email` kanalıyla bildirim
    üretilmemeli — üretilirse burada net bir mesajla düşer.
    """

    name = NotificationChannel.email

    def __init__(self, cfg: "mail.SmtpConfig") -> None:
        self._cfg = cfg

    async def send(self, recipient: str, body: str) -> None:
        if not (recipient or "").strip():
            raise RuntimeError("alıcı e-posta adresi yok")
        # İlk satır konu olur; gövde bütün metindir. Bildirim metinleri
        # `build_body` tarafından üretiliyor ve ilk satır zaten özet.
        first = body.strip().splitlines()[0] if body.strip() else "NÖBET bildirimi"
        subject = first[:120]
        await mail.send_mail(self._cfg, recipient, subject, body)

    async def healthy(self) -> tuple[bool, str]:
        return await mail.verify(self._cfg)


def build_channel() -> Channel:
    """Ortam değişkenine göre kanal (geriye dönük uyumluluk)."""
    if settings.notify_channel == "whatsapp":
        return WhatsAppChannel(settings.wa_gateway_url)
    return DryRunChannel()


async def build_channel_for(db: AsyncSession, tenant_id) -> Channel:
    """
    Veritabanındaki ayara göre kanal. Kurum kanalı arayüzden değiştirebilsin
    diye asıl yol budur; ortam değişkeni yalnızca ayar yokken geçerli.
    """
    from app import settings_store

    row = await settings_store.get_setting(db, tenant_id)

    if row.channel == "whatsapp":
        return WhatsAppChannel(settings.wa_gateway_url)

    if row.channel == "sms":
        try:
            secret = settings_store.decrypt_secret(row.secret_enc)
        except settings_store.SecretUnavailable as exc:
            log.error("SMS kimlik bilgileri okunamadi: %s", exc)
            return DryRunChannel()
        cfg = dict(row.sms_config or {})
        cfg.setdefault("provider", row.sms_provider)
        return SmsChannel(cfg, secret)

    if row.channel == "email":
        return EmailChannel(settings_store.smtp_config(row))

    return DryRunChannel()


# ---------------------------------------------------------------------------
# Mesaj metni
# ---------------------------------------------------------------------------
def build_body(
    student: str, zone_name: str, direction: str,
    when: dt.datetime, tz_name: str, institution: str,
) -> str:
    try:
        tz = ZoneInfo(tz_name or settings.timezone)
    except Exception:
        tz = ZoneInfo(settings.timezone)
    local = when.astimezone(tz)

    fiil = "giriş yaptı" if direction == "GİRİŞ" else "çıkış yaptı"
    return (
        f"{institution}\n"
        f"{student}, {local:%d.%m.%Y %H:%M} itibarıyla {zone_name} "
        f"noktasından {fiil}.\n\n"
        f"Bu bilgilendirme mesajı otomatik gönderilmiştir."
    )


# ---------------------------------------------------------------------------
# Gecikmeli bildirim damgası (kullanıcı kararı 2026-08-14)
# ---------------------------------------------------------------------------
# Veli mesajı geç aldığında bunu **ilk satırdan** anlamalı. Aksi hâlde
# 9 saat önce olmuş bir girişi az önce olmuş sanar — bildirim sisteminin
# yapabileceği en zararlı hata bu: yanlış bilgiyi güvenle vermek.
#
# Eşik neden 5 dakika: canlı yolda gecikme saniyelerle ölçülür, dakikalar
# zaten anormaldir. Daha kısa bir eşik sıradan ağ gecikmelerini "gecikmeli"
# diye damgalar ve damga anlamını yitirir.
GECIKME_ESIGI = dt.timedelta(minutes=5)

_BASLIK = "GECİKMELİ BİLDİRİM · "
_ACIKLAMA_ON = "Bu mesaj bağlantı kesintisi nedeniyle "


def _sure_metni(d: dt.timedelta) -> str:
    """'8 dakika', '2 saat 15 dakika', '1 gün 3 saat'."""
    dk = int(d.total_seconds() // 60)
    if dk < 60:
        return f"{dk} dakika"
    sa, dk = divmod(dk, 60)
    if sa < 24:
        return f"{sa} saat {dk} dakika" if dk else f"{sa} saat"
    gun, sa = divmod(sa, 24)
    return f"{gun} gün {sa} saat" if sa else f"{gun} gün"


def apply_delay_notice(body: str, delay: dt.timedelta) -> str:
    """
    Mesaja gecikme damgasını vurur. **Fikir sabitli (idempotent)** —
    zaten damgalı bir metne uygulanırsa damgayı üst üste bindirmez,
    güncel gecikmeyle yeniler.

    Bu şart: gönderim başarısız olup yeniden denendiğinde bu fonksiyon
    aynı metin üzerinde tekrar çalışır ve o sırada gecikme de büyümüştür.

    ⚠️ Emoji YOK — bilerek. Emoji, SMS'i GSM-7'den UCS-2'ye düşürür;
    mesaj başına karakter sınırı yarılanır ve bir mesaj iki mesaja bölünüp
    **ücreti ikiye katlar**. SMS işletmecinin cebinden çıkıyor (§5.3).
    """
    satir = [s for s in body.split("\n") if not s.startswith(_ACIKLAMA_ON)]
    if not satir:
        return body
    if satir[0].startswith(_BASLIK):
        satir[0] = satir[0][len(_BASLIK):]
    satir[0] = _BASLIK + satir[0]
    # Olayın saatini taşıyan cümlenin hemen ardına.
    satir.insert(2, f"{_ACIKLAMA_ON}{_sure_metni(delay)} gecikmeyle iletilmiştir.")
    return "\n".join(satir)


# ---------------------------------------------------------------------------
# Bildirim üretimi — alım hattı çağırır
# ---------------------------------------------------------------------------
async def _enqueue(
    db: AsyncSession,
    *,
    tenant_id,
    person_id,
    zone_name: str,
    direction: str,
    when: dt.datetime,
    event_id: int | None = None,
    session_id=None,
) -> int:
    """
    Bildirim üretiminin ORTAK gövdesi — kart okumasında da elle girişte de
    aynı kurallar işler.

    ⚠️ Kasıtlı olarak tek bir yerde: "kime bildirim gider" kuralı iki koda
    bölünürse zamanla ayrışır ve bir gün kart girişinde giden mesaj elle
    girişte gitmez (ya da tersi). Velinin ihtiyacı iki durumda da aynı.

    Kural (kontrat §1.2): **18 yaş altı** + velisi var + `notify_enabled`
    açık + numarası dolu.

    COMMIT ETMEZ — çağıran işlemin parçasıdır; kaynak kayıt yazılmazsa
    bildirim de yazılmaz.
    """
    person = (
        await db.execute(select(Person).where(Person.id == person_id))
    ).scalar_one_or_none()
    if person is None:
        return 0

    # Kontrat §1.2: bildirim mantığı doğum tarihine bakar
    if not person.is_minor:
        return 0

    rows = (
        await db.execute(
            select(Guardian)
            .join(PersonGuardian, PersonGuardian.guardian_id == Guardian.id)
            .where(
                PersonGuardian.person_id == person.id,
                PersonGuardian.notify_enabled.is_(True),
            )
        )
    ).scalars().all()
    if not rows:
        return 0

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()

    body = build_body(
        student=person.full_name,
        zone_name=zone_name,
        direction=direction,
        when=when,
        tz_name=tenant.timezone if tenant else settings.timezone,
        institution=tenant.name if tenant else "NÖBET",
    )

    # Kanal etiketini kurum ayarından al — kayıt hangi kanalla gönderildiğini
    # göstermeli, ortam değişkeninin ne dediğini değil.
    from app import settings_store

    row = await settings_store.get_setting(db, tenant_id)
    channel = (
        NotificationChannel(row.channel)
        if row.channel in NotificationChannel.__members__
        else NotificationChannel.dryrun
    )

    count = 0
    for g in rows:
        if not g.phone:
            continue
        db.add(Notification(
            tenant_id=tenant_id,
            event_id=event_id,
            session_id=session_id,
            person_id=person.id,
            guardian_id=g.id,
            direction=direction,
            channel=channel,
            recipient=g.phone,
            body=body,
            # Olayın gerçek zamanı. Gecikme damgası buradan hesaplanır;
            # `created_at` (üretim anı) tampon gecikmesini göstermez.
            occurred_at=when,
        ))
        count += 1

    return count


async def enqueue_for_event(
    db: AsyncSession, event: Event, zone: Zone, direction: str | None
) -> int:
    """
    Kart okumasından doğan bildirim. Alım hattı çağırır.

    Yalnızca `granted` okumalar bildirim üretir: reddedilen ya da mükerrer
    sayılan okuma "içeri girdi" demek değildir.
    """
    if event.decision != EventDecision.granted or event.person_id is None:
        return 0
    if direction is None:
        return 0

    return await _enqueue(
        db,
        tenant_id=event.tenant_id,
        person_id=event.person_id,
        zone_name=zone.name,
        direction=direction,
        when=event.effective_ts,
        event_id=event.id,
    )


async def enqueue_for_session(
    db: AsyncSession, session: AttendanceSession, zone: Zone, direction: str
) -> int:
    """
    **Elle** açılan/kapatılan oturumdan doğan bildirim (Faz 13a-5).

    Kartını unutan öğrencinin velisi de haber almalı — velinin ihtiyacı,
    kaydın kartla mı elle mi oluştuğundan bağımsız. Bildirim gitmezse
    elle giriş yarım bir özellik olurdu.

    `decision` kontrolü YOK: elle kayıt zaten bir insanın kararı, okuyucu
    kararı değil. `event` üretilmediği için bildirim **oturuma** bağlanır
    (`notification.session_id`).

    Kartla açılmış bir oturumun çıkışı elle verildiğinde de çağrılır: o
    çıkış için hiç `event` üretilmez, dolayısıyla veliye haber vermenin
    tek yolu budur. Mükerrer riski yok — kartla verilen çıkış zaten olay
    yolundan gider ve bu uca hiç uğramaz.
    """
    if session.person_id is None:
        return 0

    when = session.exited_at if direction == "ÇIKIŞ" else session.entered_at
    if when is None:
        when = session.entered_at

    return await _enqueue(
        db,
        tenant_id=session.tenant_id,
        person_id=session.person_id,
        zone_name=zone.name,
        direction=direction,
        when=when,
        session_id=session.id,
    )


# ---------------------------------------------------------------------------
# Gönderim işçisi
# ---------------------------------------------------------------------------
def _backoff(attempts: int) -> dt.timedelta:
    """1dk, 5dk, 15dk, 1sa … — geçici ağ arızasında ısrarcı, kalıcıda nazik."""
    ladder = [60, 300, 900, 3600, 10800]
    return dt.timedelta(seconds=ladder[min(attempts, len(ladder) - 1)])


async def flush_pending(db: AsyncSession, channel: Channel | None = None) -> int:
    """
    Kuyruğu boşaltır. Kanal **her kiracı için ayrı** kurulur.

    ⚠️ Önceden tek bir `channel` parametre olarak geliyordu ve çağıran onu
    `select(Tenant.id).limit(1)` ile bulduğu **ilk** kuruma göre kuruyordu
    (sıralama bile yoktu). Tek kurum dağıtıldığı için canlıda etkisi olmadı,
    ama ikinci kurum eklendiği anda B kurumunun veli mesajları A kurumunun
    WhatsApp/SMS hesabından çıkardı — A `dryrun` ise B'nin bildirimleri
    sessizce "gönderildi" işaretlenirdi. Bildirim bu ürünün ana vaadi;
    sessiz kaybın en pahalı olduğu yer burası.

    `channel` yalnızca test/geri uyumluluk için duruyor; verilirse tüm
    kiracılar için o kullanılır.
    """
    now = dt.datetime.now(dt.timezone.utc)

    pending = (
        await db.execute(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.pending,
                Notification.scheduled_at <= now,
            )
            .order_by(Notification.scheduled_at)
            .limit(20)
        )
    ).scalars().unique().all()

    if not pending:
        return 0

    # Kiracı başına kanal — aynı turda birden fazla kurum varsa her biri
    # kendi sağlayıcısından gönderir. Kanal kurma maliyeti düşük ama yine de
    # tur içinde önbelleklenir.
    channels: dict[uuid.UUID, Channel] = {}

    # --- Abonelik kademesi (mimari §5.2, §5.3) ------------------------------
    # SMS gerçek para ve **işletmecinin cebinden** çıkar; bu yüzden kesilen
    # ilk şey odur. `restricted` ve `suspended` kademelerinde bildirim
    # gönderilmez.
    #
    # ⚠️ Bildirim SİLİNMEZ, `pending` kalır. Ödeme gelince gönderilsin diye
    # değil — aksine, o mesajlar artık bayattır ("çocuğunuz 3 gün önce
    # girdi") ve gönderilmeleri kafa karıştırır. Kuyrukta durmaları,
    # işletmecinin "kaç bildirim gitmedi" sorusunu cevaplayabilmesi için.
    # Kademe geri açıldığında bayatları temizlemek 13b konsolunun işi.
    subs: dict[uuid.UUID, Subscription | None] = {}

    async def sub_for(tenant_id: uuid.UUID) -> Subscription | None:
        if tenant_id not in subs:
            subs[tenant_id] = (
                await db.execute(
                    select(Subscription).where(Subscription.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
        return subs[tenant_id]

    async def channel_for(tenant_id: uuid.UUID) -> Channel:
        if channel is not None:
            return channel
        if tenant_id not in channels:
            channels[tenant_id] = await build_channel_for(db, tenant_id)
        return channels[tenant_id]

    sent = 0
    for n in pending:
        sub = await sub_for(n.tenant_id)
        if sub is not None:
            if sub.status in ("restricted", "suspended"):
                log.info(
                    "bildirim ertelendi (abonelik %s): kurum=%s", sub.status, n.tenant_id
                )
                continue
            # Kota (§5.3): 0 = sınırsız. Aşılırsa bildirim durur, panel uyarır.
            if sub.sms_quota and sub.sms_used >= sub.sms_quota:
                log.warning(
                    "SMS KOTASI DOLDU: kurum=%s (%d/%d) — bildirim durduruldu",
                    n.tenant_id, sub.sms_used, sub.sms_quota,
                )
                continue
        # --- gecikmeli bildirim damgası (2026-08-14) --------------------
        # GÖNDERİM anında vuruluyor, üretim anında değil. Gecikme iki ayrı
        # yerden doğar ve ikincisi üretim anında henüz bilinmez:
        #   1) düğüm tamponunu boşalttı — olay saatlerce eski
        #   2) kuyruğun kendisi — yeniden deneme merdiveni 3 saate çıkıyor,
        #      abonelik `restricted` ise mesaj günlerce bekleyebilir
        # Damgalanmış metin `n.body`ye geri yazılır: kayıt, velinin
        # gerçekten aldığı metni göstermeli.
        if n.occurred_at is not None:
            gecikme = now - n.occurred_at
            if gecikme >= GECIKME_ESIGI:
                n.body = apply_delay_notice(n.body, gecikme)

        try:
            await (await channel_for(n.tenant_id)).send(n.recipient, n.body)
            if sub is not None:
                sub.sms_used += 1
            n.status = NotificationStatus.sent
            n.sent_at = dt.datetime.now(dt.timezone.utc)
            n.last_error = None
            sent += 1
        except Exception as exc:
            n.attempts += 1
            n.last_error = str(exc)[:500]
            if n.attempts >= settings.notify_max_attempts:
                n.status = NotificationStatus.failed
                log.error("bildirim vazgecildi: id=%s alici=%s hata=%s",
                          n.id, n.recipient, n.last_error)
            else:
                n.scheduled_at = dt.datetime.now(dt.timezone.utc) + _backoff(n.attempts)
                log.warning("bildirim basarisiz, tekrar denenecek (%d): %s",
                            n.attempts, n.last_error)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        log.exception("bildirim durumu yazilamadi")
        return 0

    return sent


async def worker_loop() -> None:
    """
    Alım hattıyla aynı süreçte, 10 saniyede bir kuyruğu boşaltır.

    Kanal HER DÖNGÜDE veritabanından okunur: kurum ayarı arayüzden
    değiştirdiğinde konteyner yeniden başlatılmadan geçerli olmalı.
    """
    last_name: str | None = None

    # İkinci bir ingest kopyası kalkarsa ikisi de aynı `pending` satırlarını
    # okuyup gönderir → veli ÇİFT mesaj alır. `UNIQUE(event_id, guardian_id)`
    # bildirimin üretilmesini tekilleştiriyor, gönderilmesini değil.
    async with worklock.WorkLock(worklock.LOCK_NOTIFY, "bildirim isçisi") as got:
        if not got:
            return
        await _worker_loop_locked(last_name)


async def _worker_loop_locked(last_name: str | None) -> None:
    while True:
        try:
            async with SessionLocal() as db:
                # Kanal seçimi artık `flush_pending` içinde, HER BİLDİRİMİN
                # KENDİ kiracısına göre yapılıyor. Buradaki tek iş, kanal
                # adı değiştiğinde bunu günlüğe düşürmek.
                tenant_id = (
                    await db.execute(select(Tenant.id).order_by(Tenant.slug).limit(1))
                ).scalar_one_or_none()
                if tenant_id is not None:
                    name = (await build_channel_for(db, tenant_id)).name.value
                    if name != last_name:
                        log.info("bildirim kanali: %s", name)
                        last_name = name

                n = await flush_pending(db)
                if n:
                    log.info("%d bildirim gonderildi", n)
        except Exception:
            log.exception("bildirim isçisi hatasi")
        await asyncio.sleep(10)
