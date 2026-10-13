"""
NÖBET — İşletmeci konsolu (Faz 13b)
====================================
Mimari: docs/nobet-faz13-saas-mimarisi.md §5

Buradaki yetkiler **kurumun değil, işletmecinin**. Bir kurum yöneticisi
kendi aboneliğini açamamalı; hepsi `SuperAdmin` arkasında.

⭐ **§5.1 — kurumun kaydı hiçbir kademede durdurulmaz.** Bu uçlar hizmeti
kısar, veriyi değil. En ağır kademede bile kenar cihazı kayıt tutmaya devam
eder ve ödeme gelince kuyruk buluta akar.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import secrets
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import passwords
from app.deps import DbSession, SuperAdmin
from app.models import (
    AppRole,
    AppUser,
    EdgeDevice,
    Membership,
    Person,
    ResetPurpose,
    Subscription,
    Tenant,
)
from app.schemas import MIN_PASSWORD_LEN
from app.security import hash_password

log = logging.getLogger("nobet.admin")
router = APIRouter(tags=["admin"])

SLUG_RE = re.compile(r"^[a-z0-9-]{2,40}$")
STATUSES = ("active", "warning", "restricted", "suspended")


# ---------------------------------------------------------------------------
class TenantRow(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    timezone: str
    created_at: dt.datetime
    # --- abonelik ---
    status: str
    period_start: dt.date | None
    period_end: dt.date | None
    sms_quota: int
    sms_used: int
    suspended_at: dt.datetime | None
    note: str | None
    # --- büyüklük göstergeleri (fatura ve destek için) ---
    person_count: int
    user_count: int
    edge_count: int


class TenantIn(BaseModel):
    slug: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Europe/Istanbul"
    # Kurum açılırken İLK YÖNETİCİ de açılır. Aksi hâlde kuruma kimse
    # giremez — denetimde bulunan "temiz kurulum hiç açılamıyor" hatasının
    # aynısı olurdu.
    admin_email: EmailStr
    # Boşsa davet e-postası gider ve parolayı kullanıcı kendi belirler.
    admin_password: str | None = Field(default=None, min_length=MIN_PASSWORD_LEN)


class TenantCreated(BaseModel):
    tenant: TenantRow
    admin_email: str
    invite_sent: bool | None = None
    invite_error: str | None = None


class SubscriptionPatch(BaseModel):
    status: str | None = None
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    sms_quota: int | None = Field(default=None, ge=0)
    # Sayaç sıfırlama (yeni fatura dönemi).
    reset_sms_used: bool = False
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
async def _rows(db: DbSession, tenant_id: uuid.UUID | None = None) -> list[TenantRow]:
    conds = [] if tenant_id is None else [Tenant.id == tenant_id]
    result = (
        await db.execute(
            select(Tenant, Subscription)
            .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
            .where(*conds)
            .order_by(Tenant.name)
        )
    ).all()

    out: list[TenantRow] = []
    for t, sub in result:
        pc = (await db.execute(
            select(func.count()).select_from(Person).where(Person.tenant_id == t.id)
        )).scalar_one()
        uc = (await db.execute(
            select(func.count()).select_from(Membership).where(Membership.tenant_id == t.id)
        )).scalar_one()
        ec = (await db.execute(
            select(func.count()).select_from(EdgeDevice)
            .where(EdgeDevice.tenant_id == t.id)
        )).scalar_one()
        out.append(TenantRow(
            id=t.id, slug=t.slug, name=t.name, timezone=t.timezone,
            created_at=t.created_at,
            status=sub.status if sub else "active",
            period_start=sub.period_start if sub else None,
            period_end=sub.period_end if sub else None,
            sms_quota=sub.sms_quota if sub else 0,
            sms_used=sub.sms_used if sub else 0,
            suspended_at=sub.suspended_at if sub else None,
            note=sub.note if sub else None,
            person_count=pc, user_count=uc, edge_count=ec,
        ))
    return out


@router.get("/admin/tenants", response_model=list[TenantRow])
async def list_tenants(user: SuperAdmin, db: DbSession) -> list[TenantRow]:
    return await _rows(db)


@router.post("/admin/tenants", response_model=TenantCreated,
             status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantIn, user: SuperAdmin, db: DbSession
) -> TenantCreated:
    """
    Kurum açar **ve ilk yöneticisini oluşturur.**

    İkisi tek işlemde: yöneticisiz bir kurum, kimsenin giremediği ölü bir
    kayıttır. Denetimde tam bu hata bulunmuştu (kurum oluşturmanın yolu
    yoktu, hesap açmanın da).
    """
    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "kurum kodu yalnızca küçük harf, rakam ve tire içerebilir (2-40)",
        )

    if (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "bu kurum kodu zaten kullanımda")

    tenant = Tenant(slug=slug, name=body.name.strip(), timezone=body.timezone)
    db.add(tenant)
    await db.flush()   # tetikleyiciler subscription ve sync_state satırını açar

    email = str(body.admin_email).strip().lower()
    existing = (
        await db.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()

    invite = body.admin_password is None
    if existing is not None:
        # ⚠️ Var olan kimliğin parolasına DOKUNULMAZ (Faz 13a-0 kuralı):
        # başka bir kurumdaki hesabı devralmak olurdu.
        identity = existing
        invite = False
    else:
        identity = AppUser(
            email=email,
            password_hash=hash_password(body.admin_password or secrets.token_urlsafe(32)),
            is_active=True,
        )
        db.add(identity)
        await db.flush()

    db.add(Membership(
        user_id=identity.id, tenant_id=tenant.id,
        role=AppRole.kurum_admin, is_active=True,
    ))

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "kurum açılamadı") from exc

    sent: bool | None = None
    err: str | None = None
    if invite:
        token = await passwords.issue(db, identity, ResetPurpose.invite)
        await db.commit()
        sent = await passwords.send_reset_mail(db, identity, token, ResetPurpose.invite)
        if not sent:
            err = ("kurum açıldı ama davet e-postası gönderilemedi — "
                   "SMTP ayarlarını kontrol edip yeniden gönderin")
    elif existing is not None:
        err = ("Bu e-postanın zaten bir hesabı vardı; kuruma yönetici olarak "
               "eklendi. MEVCUT parolasıyla giriş yapar.")

    log.info("kurum acildi: %s (%s) yonetici=%s", tenant.slug, tenant.name, email)
    rows = await _rows(db, tenant.id)
    return TenantCreated(
        tenant=rows[0], admin_email=email, invite_sent=sent, invite_error=err,
    )


@router.patch("/admin/tenants/{tenant_id}/subscription", response_model=TenantRow)
async def patch_subscription(
    tenant_id: uuid.UUID, body: SubscriptionPatch, user: SuperAdmin, db: DbSession
) -> TenantRow:
    """
    Abonelik kademesini değiştirir (§5.2).

    Kademe düşürmek **veriyi silmez, kayıt tutmayı durdurmaz.** En ağır
    kademede (`suspended`) bile kenar cihazı olayları biriktirmeye devam
    eder; ödeme gelince kuyruk buluta akar ve hiçbir şey kaybolmaz.
    """
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kurum bulunamadı")

    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"geçersiz kademe — {', '.join(STATUSES)} olabilir",
            )
        onceki = sub.status
        sub.status = body.status
        # Askıya alma anı kaydedilir: "ne zamandır kapalı" sorusu hem
        # faturada hem destek konuşmasında sorulur.
        if body.status == "suspended" and onceki != "suspended":
            sub.suspended_at = dt.datetime.now(dt.timezone.utc)
        elif body.status != "suspended":
            sub.suspended_at = None
        if onceki != body.status:
            log.warning(
                "abonelik kademesi: %s -> %s (kurum=%s, degistiren=%s)",
                onceki, body.status, tenant_id, user.email,
            )

    if body.period_start is not None:
        sub.period_start = body.period_start
    if body.period_end is not None:
        sub.period_end = body.period_end
    if body.sms_quota is not None:
        sub.sms_quota = body.sms_quota
    if body.reset_sms_used:
        sub.sms_used = 0
    if body.note is not None:
        sub.note = body.note.strip() or None

    # Para konusudur; kimin değiştirdiği izsiz kalmaz.
    sub.changed_by = user.id
    sub.updated_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()

    rows = await _rows(db, tenant_id)
    return rows[0]
