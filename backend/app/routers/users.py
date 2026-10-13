"""
NÖBET — Kullanıcı hesapları (kontrat §3.1, §1.3)
================================================
"Sıfır CLI" kuralının gereği: kurum yeni personel işe aldığında hesabını
arayüzden açabilmeli. Bu yönlendirici gelmeden önce hesap açmanın tek yolu
`python -m app.bootstrap` idi ve o da `person_id` doldurmadığı için
**çalışan bir koç hesabı hiçbir desteklenen yoldan oluşturulamıyordu.**

Kilitlenmeye karşı üç koruma var; üçü de burada zorlanıyor:
  1. Kimse kendi hesabını pasife alamaz veya rolünü düşüremez
  2. Son etkin yönetici pasife alınamaz / rolü düşürülemez
  3. `kurum_admin`, `super_admin` üretemez veya o role dokunamaz
"""
from __future__ import annotations

import datetime as dt
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import passwords
from app.deps import AdminUser, DbSession
from app.models import AppRole, AppUser, Membership, Person, PersonStatus, ResetPurpose
from app.schemas import AppUserOut, UserIn, UserPasswordIn, UserPatch
from app.security import hash_password

router = APIRouter(tags=["users"])

ADMIN_ROLES = (AppRole.super_admin, AppRole.kurum_admin)


async def _get_user(
    db: DbSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[AppUser, Membership]:
    """
    Kimlik + BU KURUMDAKİ üyeliği (Faz 13a-0).

    Kurum filtresi üyelik üzerinden uygulanır: başka kurumun kullanıcısı
    404 alır. Kişinin başka bir kurumda üyeliği olup olmadığı bu uçtan
    **hiçbir biçimde görünmez.**
    """
    row = (
        await db.execute(
            select(AppUser, Membership)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(AppUser.id == user_id, Membership.tenant_id == tenant_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kullanıcı bulunamadı")
    return row[0], row[1]


async def _active_admin_count(db: DbSession, tenant_id: uuid.UUID) -> int:
    """Bu KURUMDAKİ etkin yönetici sayısı — kimlik değil üyelik sayılır."""
    return (
        await db.execute(
            select(func.count()).select_from(Membership)
            .join(AppUser, AppUser.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
                Membership.role.in_(ADMIN_ROLES),
                # Kimliği kapatılmış hesap yönetici sayılmaz.
                AppUser.is_active.is_(True),
            )
        )
    ).scalar_one()


def _assert_may_touch_role(actor: AppUser, role: AppRole) -> None:
    """
    `super_admin` rolüne yalnızca `super_admin` dokunabilir.

    Aksi hâlde bir `kurum_admin` kendini super_admin'e yükseltebilir ya da
    çok kurumlu kurulumda başka kurumların üstündeki hesabı ele geçirebilirdi.
    """
    if role == AppRole.super_admin and actor.role != AppRole.super_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "super_admin rolünü yalnızca super_admin verebilir",
        )


async def _resolve_person(
    db: DbSession, tenant_id: uuid.UUID, person_id: uuid.UUID | None, role: AppRole
) -> None:
    """Bağlanacak kişiyi doğrular; koç rolünde kişi bağı zorunludur."""
    if role == AppRole.coach and person_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "koç hesabı bir kişiye bağlanmalı — yoksa hiçbir öğrenci göremez",
        )
    if person_id is None:
        return

    person = (
        await db.execute(
            select(Person).where(Person.id == person_id, Person.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bağlanacak kişi bulunamadı")
    if person.anonymized_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "anonimleştirilmiş kayda hesap bağlanamaz",
        )
    if person.status != PersonStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "pasif kişiye hesap bağlanamaz")


def _out(u: AppUser, m: Membership, person_name: str | None) -> AppUserOut:
    """
    Rol / kişi bağı / etkinlik **üyelikten** okunur (Faz 13a-0).

    `is_active`: kimlik VE üyelik birlikte etkinse etkin. Kimlik kapalıysa
    kişi hiçbir kuruma giremez; üyelik kapalıysa yalnızca buraya giremez.
    Panelde tek bir "etkin" göstergesi olması yeterli.
    """
    return AppUserOut(
        id=u.id, email=u.email, role=m.role,
        is_active=bool(u.is_active and m.is_active),
        person_id=m.person_id, person_name=person_name,
        last_login_at=u.last_login_at, created_at=m.created_at,
    )


@router.get("/users", response_model=list[AppUserOut])
async def list_users(
    user: AdminUser,
    db: DbSession,
    include_inactive: bool = Query(default=True),
) -> list[AppUserOut]:
    conds = [Membership.tenant_id == user.tenant_id]
    if not include_inactive:
        conds.append(Membership.is_active.is_(True))
        conds.append(AppUser.is_active.is_(True))

    rows = (
        await db.execute(
            select(AppUser, Membership, Person.full_name)
            .join(Membership, Membership.user_id == AppUser.id)
            .outerjoin(Person, Person.id == Membership.person_id)
            .where(*conds)
            .order_by(Membership.role, AppUser.email)
        )
    ).all()
    return [_out(u, m, name) for u, m, name in rows]


@router.post("/users", response_model=AppUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserIn, user: AdminUser, db: DbSession) -> AppUserOut:
    """
    Hesap açar.

    `password` verilirse doğrudan atanır (yönetici parolayı kullanıcıya kendisi
    iletir). Verilmezse **davet e-postası** gider ve kullanıcı parolasını kendi
    belirler — yöneticinin parolayı bilmesi ve düz metin iletmesi gerekmez.

    Davet kipinde hesap **giriş yapılamaz bir parola hash'iyle** açılır:
    `password_hash` NOT NULL, ama oraya rastgele bir değer konur ve kimseye
    verilmez. Boş/sabit bir değer koymak, o değeri bilen herkese kapı açardı.
    """
    _assert_may_touch_role(user, body.role)
    await _resolve_person(db, user.tenant_id, body.person_id, body.role)

    email = str(body.email).strip().lower()

    # --- Faz 13a-0: kimlik zaten var mı? ------------------------------------
    # Varsa YENİ KİMLİK AÇILMAZ, o kimliğe bu kurumda üyelik eklenir.
    # Aynı kişinin iki kurumda çalışabilmesinin yolu bu.
    existing = (
        await db.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()

    if existing is not None:
        dup = (
            await db.execute(
                select(Membership).where(
                    Membership.user_id == existing.id,
                    Membership.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "bu e-posta bu kurumda zaten kayıtlı"
            )

    invite = body.password is None
    if existing is not None:
        # ⚠️ Var olan kimliğin parolasına ASLA dokunulmaz. Yönetici burada
        # parola verirse bu, o kişinin BAŞKA kurumdaki hesabının parolasını
        # değiştirmek olurdu — kendi kurumunun yöneticisi olmadığı bir hesabı
        # devralması demek. Kişi mevcut parolasıyla girer.
        new = existing
        invite = False
    else:
        new = AppUser(
            email=email,
            password_hash=hash_password(body.password or secrets.token_urlsafe(32)),
            is_active=True,
        )
        db.add(new)
        await db.flush()

    db.add(Membership(
        user_id=new.id,
        tenant_id=user.tenant_id,
        role=body.role,
        person_id=body.person_id,
        is_active=True,
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "bu e-posta bu kurumda zaten kayıtlı"
        ) from exc

    await db.refresh(new)
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == new.id, Membership.tenant_id == user.tenant_id
            )
        )
    ).scalar_one()

    sent: bool | None = None
    err: str | None = None
    if existing is not None:
        err = ("Bu e-postanın NÖBET hesabı zaten vardı; kuruma eklendi. "
               "Kişi MEVCUT parolasıyla giriş yapar — yeni parola belirlenmedi.")
    elif invite:
        token = await passwords.issue(db, new, ResetPurpose.invite)
        await db.commit()
        sent = await passwords.send_reset_mail(db, new, token, ResetPurpose.invite)
        if not sent:
            # Hesap açıldı ama davet gitmedi. Sessizce geçilirse yönetici işi
            # bittiğini sanır, kullanıcı e-posta bekler ve kimse fark etmez.
            err = ("hesap açıldı ama davet e-postası gönderilemedi — "
                   "SMTP ayarlarını kontrol edip 'Sıfırlama bağlantısı gönder' "
                   "ile yeniden deneyin")

    name = None
    if membership.person_id:
        name = (
            await db.execute(
                select(Person.full_name).where(Person.id == membership.person_id)
            )
        ).scalar_one_or_none()
    out = _out(new, membership, name)
    out.invite_sent = sent
    out.invite_error = err
    return out


@router.post("/users/{user_id}/invite", response_model=dict)
async def send_reset_link(
    user_id: uuid.UUID, user: AdminUser, db: DbSession
) -> dict:
    """
    Kullanıcıya parola belirleme bağlantısı gönderir.

    Yöneticinin parola uydurup iletmesine alternatif: bağlantı doğrudan
    kullanıcının e-postasına gider, parolayı yalnızca o bilir.
    """
    target, m = await _get_user(db, user.tenant_id, user_id)
    _assert_may_touch_role(user, m.role)
    if not target.is_active or not m.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "hesap pasif")

    token = await passwords.issue(db, target, ResetPurpose.invite)
    await db.commit()

    ok = await passwords.send_reset_mail(db, target, token, ResetPurpose.invite)
    if not ok:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "e-posta gönderilemedi — SMTP ayarlarını kontrol edin",
        )
    return {"ok": True, "detail": f"{target.email} adresine gönderildi"}


@router.patch("/users/{user_id}", response_model=AppUserOut)
async def update_user(
    user_id: uuid.UUID, body: UserPatch, user: AdminUser, db: DbSession
) -> AppUserOut:
    target, m = await _get_user(db, user.tenant_id, user_id)
    data = body.model_dump(exclude_unset=True)

    # Mevcut rolüne dokunma yetkisi (super_admin koruması)
    _assert_may_touch_role(user, m.role)
    if "role" in data:
        _assert_may_touch_role(user, data["role"])

    is_self = target.id == user.id
    losing_admin = (
        m.role in ADMIN_ROLES
        and m.is_active
        and (
            data.get("is_active") is False
            or ("role" in data and data["role"] not in ADMIN_ROLES)
        )
    )

    # 1) Kendi kendini kilitleme koruması
    if is_self and losing_admin:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "kendi yönetici yetkinizi kaldıramazsınız — başka bir yönetici yapmalı",
        )

    # 2) Son yöneticiyi koruma — SAVUNMA AMAÇLI YEDEK.
    #
    #    Bugünkü kurguda bu dala düşülmez: isteği yapan zaten etkin bir
    #    yönetici olduğu için sayaç en az 1'dir; sayaç tam 1 ise o yönetici
    #    aktörün kendisidir ve yukarıdaki (1) kontrolü çoktan durdurmuştur.
    #    Yine de duruyor, çünkü şu üç değişiklikten biri onu anında
    #    gerekli kılar: (1) kontrolünün gevşetilmesi, super_admin'e
    #    kurumlar arası yetki verilmesi, ya da hesap yönetiminin
    #    yönetici olmayan bir role açılması.
    if losing_admin and await _active_admin_count(db, user.tenant_id) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "son etkin yönetici hesabı — önce başka bir yönetici tanımlayın",
        )

    new_role = data.get("role", m.role)
    if "person_id" in data or "role" in data:
        await _resolve_person(
            db, user.tenant_id, data.get("person_id", m.person_id), new_role
        )

    if "email" in data:
        # E-posta KİMLİĞE ait — değiştirmek kişinin tüm kurumlardaki girişini
        # etkiler. Başka kurumda da üyeliği varsa buna izin verilmez: bir
        # kurumun yöneticisi, diğer kurumdaki oturumu kilitleyebilirdi.
        other = (
            await db.execute(
                select(func.count()).select_from(Membership).where(
                    Membership.user_id == target.id,
                    Membership.tenant_id != user.tenant_id,
                )
            )
        ).scalar_one()
        if other:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "bu hesabın e-postası buradan değiştirilemez — kullanıcı "
                "kendi hesap sayfasından değiştirmeli",
            )
        target.email = str(data["email"]).strip().lower()

    # Rol, kişi bağı ve etkinlik ÜYELİĞE yazılır; kimliğe değil.
    for field in ("role", "is_active", "person_id"):
        if field in data:
            setattr(m, field, data[field])

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "bu e-posta zaten kayıtlı"
        ) from exc

    await db.refresh(target)
    await db.refresh(m)
    name = None
    if m.person_id:
        name = (
            await db.execute(
                select(Person.full_name).where(Person.id == m.person_id)
            )
        ).scalar_one_or_none()
    return _out(target, m, name)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID, body: UserPasswordIn, user: AdminUser, db: DbSession
) -> None:
    """
    Parola sıfırlama. Kullanıcı parolasını unuttuğunda yönetici yenisini
    belirler; eski parola sorulmaz çünkü zaten bilinmiyor olan odur.
    """
    target, m = await _get_user(db, user.tenant_id, user_id)
    _assert_may_touch_role(user, m.role)

    # ⚠️ Parola KİMLİĞE ait. Kişinin başka kurumda da üyeliği varsa, buradan
    # parola atamak o kurumdaki hesabını da devralmak olurdu. Bu durumda
    # yönetici parola belirleyemez; sıfırlama bağlantısı gönderir, parolayı
    # yalnızca kişinin kendisi belirler.
    other = (
        await db.execute(
            select(func.count()).select_from(Membership).where(
                Membership.user_id == target.id,
                Membership.tenant_id != user.tenant_id,
            )
        )
    ).scalar_one()
    if other:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "bu hesap başka bir kuruma da bağlı — parolasını siz "
            "belirleyemezsiniz. 'Sıfırlama bağlantısı gönder' kullanın.",
        )

    target.password_hash = hash_password(body.password)
    # Kullanıcının açık oturumları da düşer (denetim Y-1). Yönetici parolayı
    # genelde bir sorun olduğu için sıfırlar; eski oturumun ayakta kalması
    # işlemi anlamsız kılardı.
    target.password_changed_at = dt.datetime.now(dt.timezone.utc)
    # Parola HER değiştiğinde bekleyen jetonlar kapanır: dolaşımdaki eski bir
    # davet/sıfırlama e-postası yeni parolanın üzerine yazamasın.
    await passwords.invalidate_all(db, target.id)
    await db.commit()


@router.delete("/users/{user_id}", response_model=AppUserOut)
async def deactivate_user(
    user_id: uuid.UUID, user: AdminUser, db: DbSession
) -> AppUserOut:
    """
    Yumuşak silme: `is_active = false`.

    Kalıcı silme yok — `attendance_session.corrected_by` bu kimliği tutuyor;
    hesabı yok etmek "bu düzeltmeyi kim yaptı" izini koparırdı.
    """
    target, m = await _get_user(db, user.tenant_id, user_id)
    _assert_may_touch_role(user, m.role)

    if target.id == user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "kendi hesabınızı pasife alamazsınız"
        )
    if (
        m.role in ADMIN_ROLES
        and m.is_active
        and await _active_admin_count(db, user.tenant_id) <= 1
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "son etkin yönetici hesabı — önce başka bir yönetici tanımlayın",
        )

    # ÜYELİK kapatılır, kimlik değil: kişinin başka kurumdaki erişimi
    # sürmeli. Bir kurumun yöneticisi diğerinin kullanıcısını kilitleyemez.
    m.is_active = False
    await db.commit()
    await db.refresh(m)

    name = None
    if m.person_id:
        name = (
            await db.execute(
                select(Person.full_name).where(Person.id == m.person_id)
            )
        ).scalar_one_or_none()
    return _out(target, m, name)
