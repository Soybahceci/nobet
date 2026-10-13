"""
NÖBET — Bağımlılıklar ve yetki kapıları
========================================
Kontrat §1.3 rol yetki matrisi burada zorlanır.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, set_tenant_scope
from app.models import AppRole, AppUser, CoachAssignment, Membership, Subscription
from app.security import TokenError, decode_token, token_predates_password_change

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_session)]


@dataclass
class Principal:
    """
    İstek sahibi: **kimlik + etkin üyelik** (Faz 13a-0, mimari §3b).

    Faz 13a-0'da `tenant_id` / `role` / `person_id` `app_user`'dan
    `membership`'e taşındı. Uçlarda bu alanlar 101 yerde kullanılıyordu;
    hepsini tek tek değiştirmek yerine burada **eski arayüz aynen
    korunuyor** — `user.tenant_id`, `user.role`, `user.person_id` çalışmaya
    devam ediyor, ama artık jetonun işaret ettiği üyelikten okunuyorlar.

    ⚠️ Bu bir ORM nesnesi DEĞİL. Kimliği değiştirmek gerekiyorsa
    `principal.user` üzerinden gidin (ör. parola değiştirme).
    """
    user: AppUser
    membership: Membership
    # Kurumun abonelik kademesi (Faz 13b-1). Arayüz `warning` durumunda
    # bandrol göstersin, `restricted` durumunda yazma düğmelerini gizlesin.
    subscription_status: str = "active"

    # --- kimlikten ---
    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def is_active(self) -> bool:
        return self.user.is_active

    @property
    def password_changed_at(self):
        return self.user.password_changed_at

    # --- etkin üyelikten ---
    @property
    def tenant_id(self) -> uuid.UUID:
        return self.membership.tenant_id

    @property
    def role(self) -> AppRole:
        return self.membership.role

    @property
    def person_id(self) -> uuid.UUID | None:
        return self.membership.person_id


async def active_memberships(db: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    """Kullanıcının etkin üyelikleri, en eskiden yeniye."""
    return list((
        await db.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.is_active.is_(True))
            .order_by(Membership.created_at)
        )
    ).scalars().all())


# Yazma sayılan HTTP yöntemleri. `restricted` kademesinde panel salt
# okunur olur (§5.2) — okumak serbest, değiştirmek değil.
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _assert_subscription_allows(
    db: AsyncSession, tenant_id: uuid.UUID, role: AppRole, method: str
) -> str:
    """
    Abonelik kademesini zorlar (mimari §5.2) ve kademeyi döndürür.

    ⚠️ **Kenar cihazı bu kontrolden GEÇMEZ** — `/edge/*` uçları
    `CurrentEdge` kullanıyor, `current_user` değil. Kasıtlı: §5.1'e göre
    kurumun kaydı hiçbir kademede durdurulmaz. En ağır kademede bile
    okuyucular çalışır, kenar kayıt tutar; kesilen şey hizmettir, veri değil.

    `super_admin` her kademeden muaftır — aksi hâlde askıya alınmış bir
    kurumu geri açmanın yolu kalmazdı.
    """
    row = (
        await db.execute(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    # Satır yoksa (tetikleyici bir şekilde çalışmamışsa) kısıtlama yapma:
    # ödeme kaydının eksikliği yüzünden çalışan bir kurumu kilitlemek,
    # çözdüğünden büyük sorun olur.
    if row is None:
        return "active"

    if role == AppRole.super_admin:
        return row.status

    if row.status == "suspended":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "aboneliğiniz askıya alındı — kayıtlarınız güvende ve giriş-çıkış "
            "kaydı tutulmaya devam ediyor; panele erişim için ödeme gerekiyor",
        )
    if row.status == "restricted" and method.upper() in _WRITE_METHODS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "aboneliğiniz kısıtlı — panel şu an salt okunur; "
            "kayıtlarınızı görüntüleyebilir ama değiştiremezsiniz",
        )
    return row.status


async def current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "kimlik bilgisi yok")

    try:
        payload = decode_token(creds.credentials, "access")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token içeriği bozuk") from exc

    user = (await db.execute(select(AppUser).where(AppUser.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "kullanıcı yok veya pasif")

    # Parola değiştiyse ondan önce üretilmiş token'lar ölür (denetim Y-1).
    # Çalınmış bir oturumu düşürmenin tek yolu bu — token'lar durumsuz.
    if token_predates_password_change(payload, user.password_changed_at):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "parola değişti — yeniden giriş yapın"
        )

    # --- etkin üyeliği jetondan çöz (Faz 13a-0) -----------------------------
    # Kurum, kullanıcının kendisinden değil JETONDAN gelir. Kimlik birden
    # fazla kuruma üye olabildiği için "kullanıcının kurumu" diye tek bir
    # şey artık yok; hangi üyelikle çalışıldığını jeton söyler.
    tid_raw = payload.get("tid")
    try:
        tenant_id = uuid.UUID(str(tid_raw))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "token kurum bilgisi taşımıyor"
        ) from exc

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        # Üyelik kapatılmış ya da jeton başka kuruma ait. Rol/kurum
        # değişiklikleri böylece ANINDA etkili olur — token'ın süresi
        # dolmasını beklemez.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "bu kurumdaki erişiminiz sona ermiş"
        )

    # --- satır düzeyi güvenlik bağlamı (Faz 13b-3b) -------------------------
    # Buradan sonra veritabanı, bu isteğe YALNIZCA bu kurumun satırlarını
    # gösterir. Bir uçta `WHERE tenant_id` unutulursa sonuç boş döner,
    # başka kurumun verisi değil.
    #
    # super_admin muaf: işletmeci konsolu (kurum listesi, abonelik kademesi)
    # tanım gereği kurumlar arası çalışır. Bu rol panelde elle atanır ve
    # kuruma teslimde kimsede olmaz.
    await set_tenant_scope(
        db,
        "*" if membership.role == AppRole.super_admin else str(membership.tenant_id),
    )

    # Abonelik kademesi (Faz 13b-1). Kenar cihazları bu yoldan geçmez.
    sub_status = await _assert_subscription_allows(
        db, membership.tenant_id, membership.role, request.method
    )

    return Principal(
        user=user, membership=membership, subscription_status=sub_status
    )


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_roles(*roles: AppRole):
    """Belirtilen rollerden birine sahip olmayanı 403 ile geri çevirir."""
    allowed: Sequence[AppRole] = roles

    async def _guard(user: CurrentUser) -> Principal:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"bu işlem için yetkiniz yok (rol: {user.role.value})",
            )
        return user

    return _guard


# --- Kontrat §1.3 kısayolları ---------------------------------------------
# Kişi CRUD / credential atama: operator ve üstü
StaffUser = Annotated[Principal, Depends(require_roles(
    AppRole.super_admin, AppRole.kurum_admin, AppRole.operator
))]

# Düğüm/mekân config, oturum düzeltme, veli bildirim ayarı: admin ve üstü
AdminUser = Annotated[Principal, Depends(require_roles(
    AppRole.super_admin, AppRole.kurum_admin
))]

# İşletmeci konsolu: kurum açma, abonelik kademesi (Faz 13b).
# Bunlar KURUMUN değil, işletmecinin yetkileri — bir kurum yöneticisi
# kendi aboneliğini açamamalı.
SuperAdmin = Annotated[Principal, Depends(require_roles(AppRole.super_admin))]


async def assert_can_see_person(
    db: AsyncSession, user: Principal, person_id: uuid.UUID
) -> None:
    """
    Koç YALNIZCA kendisine atanmış öğrencileri görebilir (§1.3).
    Diğer roller kendi tenant'ındaki herkesi görebilir.
    """
    if user.role != AppRole.coach:
        return

    if user.person_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "koç kaydı bir kişiye bağlı değil")

    link = (
        await db.execute(
            select(CoachAssignment).where(
                CoachAssignment.coach_person_id == user.person_id,
                CoachAssignment.student_person_id == person_id,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        # 404 değil 403: öğrencinin varlığını sızdırmamak için ikisi de olur,
        # ama koç zaten kurum içindedir; net mesaj daha kullanışlı.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bu öğrenci size atanmamış")
