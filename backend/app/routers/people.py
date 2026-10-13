"""NÖBET — Kişi, veli ve credential yönetimi (kontrat §3.2, §3.3)"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.deps import AdminUser, CurrentUser, DbSession, StaffUser, assert_can_see_person
from app.models import (
    CoachAssignment,
    Credential,
    CredentialStatus,
    Event,
    Guardian,
    Notification,
    Person,
    PersonGuardian,
    PersonStatus,
    PersonType,
)
from app.schemas import (
    CredentialIn,
    CredentialOut,
    CredentialPatch,
    EventOut,
    GuardianLinkIn,
    GuardianLinkOut,
    GuardianLinkPatch,
    PersonDetailOut,
    PersonIn,
    PersonOut,
    PersonPage,
    PersonPatch,
)

router = APIRouter(tags=["people"])


def _guardian_link_count():
    """
    Velinin kaç öğrenciye bağlı olduğunu veren bağıntılı alt sorgu.

    `guardian` satırı kardeşler arasında paylaşıldığı için arayüzün
    "ad/telefon değişikliği N öğrenciyi etkiler" uyarısı buna dayanıyor.
    Alt sorgu olarak yazıldı ki veli listesi tek turda dönsün.

    ⚠️ İki incelik var, ikisi de atlanırsa çalışmıyor:
    - **Takma ad zorunlu.** Dış sorgu da `person_guardian`'ı kullanıyor;
      aynı tabloyu alias'sız kullanmak iki kapsamı karıştırır.
    - **`correlate(Guardian)` zorunlu.** Yoksa SQLAlchemy `person_guardian`'ı
      da dış sorguyla ilişkilendirip alt sorguyu FROM'suz bırakıyor ve
      `InvalidRequestError: returned no FROM clauses` ile patlıyor.
    """
    pg = aliased(PersonGuardian)
    return (
        select(func.count())
        .select_from(pg)
        .where(pg.guardian_id == Guardian.id)
        .correlate(Guardian)
        .scalar_subquery()
    )


async def _count_guardian_links(db: DbSession, guardian_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(PersonGuardian)
            .where(PersonGuardian.guardian_id == guardian_id)
        )
    ).scalar_one()


def _assert_not_anonymized(person: Person) -> None:
    """
    Anonimleştirilmiş kayda yeni kişisel veri bağlanmasını engeller.

    `anonymize` kişinin kimlik alanlarını temizler ve veli bağlarını kaldırır,
    ama bundan sonra yeniden veli eklenmesini hiçbir şey engellemiyordu —
    silme talebi yerine getirilmiş bir kayda tekrar ad/telefon iliştirmek
    KVKK açısından silmeyi geçersiz kılar.
    """
    if person.anonymized_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "bu kayıt KVKK talebiyle anonimleştirildi; "
            "yeni kişisel veri bağlanamaz",
        )


async def _cleanup_orphan_guardian(db: DbSession, guardian_id: uuid.UUID) -> str | None:
    """
    Hiçbir öğrenciye bağlı kalmamış veliyi temizler. Döndürdüğü değer
    `"deleted"`, `"anonymized"` ya da bağ hâlâ varsa `None`.

    ⚠️ Bu olmadan "Kaldır" düğmesi `person_guardian` bağını siliyor ama
    `guardian` satırını ad ve telefonuyla **öksüz** bırakıyordu. Zamanla
    hiçbir amaca hizmet etmeyen kişisel veri birikir — KVKK'nın veri
    minimizasyonu ilkesine aykırı. (Anonimleştirme akışı bunu düşünmüştü,
    sıradan kaldırma düşünmemişti.)

    İki yol var, çünkü yabancı anahtarlar farklı davranıyor:
      - `notification.guardian_id` → RESTRICT: gönderilmiş bildirim varsa
        satır silinemez, kimliği temizlenir.
      - Bildirim yoksa satır tamamen silinir; `wa_thread.guardian_id`
        SET NULL olduğu için o numara yeniden "tanınmayan"a düşer — doğru
        davranış, veli artık sistemde değil.
    """
    remaining = (
        await db.execute(
            select(func.count()).select_from(PersonGuardian)
            .where(PersonGuardian.guardian_id == guardian_id)
        )
    ).scalar_one()
    if remaining > 0:
        return None

    g = (
        await db.execute(select(Guardian).where(Guardian.id == guardian_id))
    ).scalar_one_or_none()
    if g is None:
        return None

    notif_count = (
        await db.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.guardian_id == guardian_id)
        )
    ).scalar_one()

    if notif_count == 0:
        await db.delete(g)
        return "deleted"

    g.full_name = f"Anonimleştirilmiş veli ({str(g.id)[:8]})"
    g.phone = ""
    g.email = None
    return "anonymized"


async def _get_person(db: DbSession, tenant_id: uuid.UUID, person_id: uuid.UUID) -> Person:
    person = (
        await db.execute(
            select(Person).where(Person.id == person_id, Person.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kişi bulunamadı")
    return person


# ---------------------------------------------------------------------------
# §3.2 Kişi
# ---------------------------------------------------------------------------
@router.get("/persons", response_model=PersonPage)
async def list_persons(
    user: StaffUser,
    db: DbSession,
    type: PersonType | None = None,
    status_: PersonStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="isim veya öğrenci no'da arama"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> PersonPage:
    conds = [Person.tenant_id == user.tenant_id]
    if type:
        conds.append(Person.person_type == type)
    if status_:
        conds.append(Person.status == status_)
    if q:
        pattern = f"%{q.strip()}%"
        conds.append(Person.full_name.ilike(pattern) | Person.external_ref.ilike(pattern))

    total = (await db.execute(select(func.count()).select_from(Person).where(*conds))).scalar_one()
    rows = (
        await db.execute(
            select(Person).where(*conds).order_by(Person.full_name)
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()

    return PersonPage(
        total=total, page=page, size=size,
        items=[PersonOut.model_validate(p) for p in rows],
    )


@router.post("/persons", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(body: PersonIn, user: StaffUser, db: DbSession) -> PersonOut:
    person = Person(tenant_id=user.tenant_id, **body.model_dump(exclude_unset=True))
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


@router.get("/persons/{person_id}", response_model=PersonDetailOut)
async def get_person(person_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PersonDetailOut:
    # Koç yalnızca kendi öğrencisini görebilir (§1.3)
    await assert_can_see_person(db, user, person_id)
    person = await _get_person(db, user.tenant_id, person_id)

    creds = (
        await db.execute(
            select(Credential).where(Credential.person_id == person_id).order_by(Credential.issued_at)
        )
    ).scalars().all()

    guardian_rows = (
        await db.execute(
            select(Guardian, PersonGuardian, _guardian_link_count())
            .join(PersonGuardian, PersonGuardian.guardian_id == Guardian.id)
            .where(PersonGuardian.person_id == person_id)
        )
    ).all()

    events = (
        await db.execute(
            select(Event).where(Event.person_id == person_id)
            .order_by(Event.effective_ts.desc()).limit(10)
        )
    ).scalars().all()

    return PersonDetailOut(
        **PersonOut.model_validate(person).model_dump(),
        credentials=[CredentialOut.model_validate(c) for c in creds],
        guardians=[
            GuardianLinkOut(
                id=g.id, full_name=g.full_name, phone=g.phone, email=g.email,
                relation=link.relation, is_primary=link.is_primary,
                notify_enabled=link.notify_enabled, linked_person_count=n,
            )
            for g, link, n in guardian_rows
        ],
        recent_events=[EventOut.model_validate(e) for e in events],
    )


@router.patch("/persons/{person_id}", response_model=PersonOut)
async def update_person(
    person_id: uuid.UUID, body: PersonPatch, user: StaffUser, db: DbSession
) -> PersonOut:
    person = await _get_person(db, user.tenant_id, person_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


@router.delete("/persons/{person_id}", response_model=PersonOut)
async def deactivate_person(
    person_id: uuid.UUID, user: StaffUser, db: DbSession
) -> PersonOut:
    """
    Soft delete (§3.2): status=passive.
    Kalıcı silme YAPILMAZ — kişiye bağlı `event` kayıtları değişmezdir,
    veritabanı da bunu FK RESTRICT ile engeller. Denetim izi korunur.
    """
    person = await _get_person(db, user.tenant_id, person_id)
    person.status = PersonStatus.passive
    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


# ---------------------------------------------------------------------------
# Veli
# ---------------------------------------------------------------------------
@router.get("/persons/{person_id}/guardians", response_model=list[GuardianLinkOut])
async def list_guardians(
    person_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[GuardianLinkOut]:
    await assert_can_see_person(db, user, person_id)
    await _get_person(db, user.tenant_id, person_id)

    rows = (
        await db.execute(
            select(Guardian, PersonGuardian, _guardian_link_count())
            .join(PersonGuardian, PersonGuardian.guardian_id == Guardian.id)
            .where(PersonGuardian.person_id == person_id)
        )
    ).all()
    return [
        GuardianLinkOut(
            id=g.id, full_name=g.full_name, phone=g.phone, email=g.email,
            relation=link.relation, is_primary=link.is_primary,
            notify_enabled=link.notify_enabled, linked_person_count=n,
        )
        for g, link, n in rows
    ]


@router.post(
    "/persons/{person_id}/guardians",
    response_model=GuardianLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_guardian(
    person_id: uuid.UUID, body: GuardianLinkIn, user: StaffUser, db: DbSession
) -> GuardianLinkOut:
    _assert_not_anonymized(await _get_person(db, user.tenant_id, person_id))

    if body.guardian_id is None and body.guardian is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "guardian_id ya da guardian nesnesi verilmeli",
        )

    if body.guardian_id is not None:
        guardian = (
            await db.execute(
                select(Guardian).where(
                    Guardian.id == body.guardian_id, Guardian.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none()
        if guardian is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "veli bulunamadı")
    else:
        guardian = Guardian(tenant_id=user.tenant_id, **body.guardian.model_dump())
        db.add(guardian)
        await db.flush()

    db.add(PersonGuardian(
        person_id=person_id,
        guardian_id=guardian.id,
        relation=body.relation,
        is_primary=body.is_primary,
        notify_enabled=body.notify_enabled,
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "bu veli zaten bağlı") from exc

    await db.refresh(guardian)
    return GuardianLinkOut(
        id=guardian.id, full_name=guardian.full_name, phone=guardian.phone,
        email=guardian.email, relation=body.relation,
        is_primary=body.is_primary, notify_enabled=body.notify_enabled,
        linked_person_count=await _count_guardian_links(db, guardian.id),
    )


@router.patch(
    "/persons/{person_id}/guardians/{guardian_id}",
    response_model=GuardianLinkOut,
)
async def update_guardian(
    person_id: uuid.UUID,
    guardian_id: uuid.UUID,
    body: GuardianLinkPatch,
    user: StaffUser,
    db: DbSession,
) -> GuardianLinkOut:
    """
    Veli düzenleme (§3.2).

    Alanlar iki tabloya dağılıyor: kimlik bilgileri `guardian`, ilişki
    bilgileri `person_guardian`. Veli çoka-çok olduğu için kimlik alanlarını
    değiştirmek bu veliye bağlı **tüm** öğrencileri etkiler — kardeşlerde
    istenen davranış bu.
    """
    _assert_not_anonymized(await _get_person(db, user.tenant_id, person_id))

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

    guardian = (
        await db.execute(
            select(Guardian).where(
                Guardian.id == guardian_id, Guardian.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if guardian is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "veli bulunamadı")

    data = body.model_dump(exclude_unset=True)

    for field in ("full_name", "phone", "email"):
        if field in data:
            setattr(guardian, field, data[field])

    for field in ("relation", "is_primary", "notify_enabled"):
        if field in data:
            setattr(link, field, data[field])

    # Bir öğrencinin tek birincil velisi olur. Veritabanı bunu zorlamıyor
    # (kısmi tekil indeks yok), o yüzden burada tutuluyor: yeni birincil
    # işaretlenirse diğerleri düşürülür.
    if data.get("is_primary") is True:
        others = (
            await db.execute(
                select(PersonGuardian).where(
                    PersonGuardian.person_id == person_id,
                    PersonGuardian.guardian_id != guardian_id,
                    PersonGuardian.is_primary.is_(True),
                )
            )
        ).scalars().all()
        for o in others:
            o.is_primary = False

    await db.commit()
    await db.refresh(guardian)
    await db.refresh(link)

    return GuardianLinkOut(
        id=guardian.id, full_name=guardian.full_name, phone=guardian.phone,
        email=guardian.email, relation=link.relation,
        is_primary=link.is_primary, notify_enabled=link.notify_enabled,
        linked_person_count=await _count_guardian_links(db, guardian.id),
    )


@router.delete(
    "/persons/{person_id}/guardians/{guardian_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_guardian(
    person_id: uuid.UUID, guardian_id: uuid.UUID, user: StaffUser, db: DbSession
) -> None:
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
    await db.delete(link)
    await db.flush()

    # Başka öğrenciye bağlı kalmadıysa veli kaydının kendisi de temizlenir;
    # yoksa ad ve telefon hiçbir amaca hizmet etmeden sistemde kalırdı.
    await _cleanup_orphan_guardian(db, guardian_id)
    await db.commit()


# ---------------------------------------------------------------------------
# §3.3 Credential
# ---------------------------------------------------------------------------
@router.get("/persons/{person_id}/credentials", response_model=list[CredentialOut])
async def list_credentials(
    person_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[CredentialOut]:
    await assert_can_see_person(db, user, person_id)
    rows = (
        await db.execute(
            select(Credential).where(Credential.person_id == person_id)
            .order_by(Credential.issued_at)
        )
    ).scalars().all()
    return [CredentialOut.model_validate(c) for c in rows]


@router.post("/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(body: CredentialIn, user: StaffUser, db: DbSession) -> CredentialOut:
    """
    Elle kart atama. Normal akış enrollment'tır (§3.4) — bu uç, kart
    numarası kâğıttan giriliyorsa ya da toplu aktarımda kullanılır.
    """
    await _get_person(db, user.tenant_id, body.person_id)

    cred = Credential(
        tenant_id=user.tenant_id,
        person_id=body.person_id,
        type=body.type,
        # Kontrat §2.2: UID hex, büyük harf, ayraçsız
        identifier=body.identifier.strip().upper().replace(":", "").replace("-", ""),
        label=body.label,
    )
    db.add(cred)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "bu kart zaten kayıtlı"
        ) from exc
    await db.refresh(cred)
    return CredentialOut.model_validate(cred)


@router.patch("/credentials/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: uuid.UUID, body: CredentialPatch, user: StaffUser, db: DbSession
) -> CredentialOut:
    """Kayıp/iptal bildirimi. Silme yerine DAİMA bu kullanılır."""
    cred = (
        await db.execute(
            select(Credential).where(
                Credential.id == credential_id, Credential.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kart bulunamadı")

    cred.status = body.status
    if body.label is not None:
        cred.label = body.label
    if body.status in (CredentialStatus.lost, CredentialStatus.revoked):
        cred.revoked_at = dt.datetime.now(dt.timezone.utc)
    else:
        cred.revoked_at = None

    await db.commit()
    await db.refresh(cred)
    return CredentialOut.model_validate(cred)


@router.post("/persons/{person_id}/anonymize", response_model=PersonOut)
async def anonymize_person(
    person_id: uuid.UUID, user: AdminUser, db: DbSession
) -> PersonOut:
    """
    KVKK silme talebinin karşılığı.

    Kişi **kalıcı olarak silinemez**: `event.person_id` yabancı anahtarı
    RESTRICT ve olaylar değişmezdir (kontrat §0). Bu denetim izi için doğru
    ama silme hakkını karşılamıyordu.

    Anonimleştirme, kimliği belirleyen alanları temizler; satır ve geçmiş
    olaylar korunur. "Kaç kişi girdi çıktı" istatistiği bozulmaz, ama o satır
    artık bir insanı işaret etmez.

    ⚠️ GERİ ALINAMAZ. Temizlenen veri hiçbir yerde saklanmaz.
    """
    person = await _get_person(db, user.tenant_id, person_id)

    if person.anonymized_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "bu kişi zaten anonimleştirilmiş")

    short = str(person.id)[:8]

    # Kimliği belirleyen her alan temizlenir
    person.full_name = f"Anonimleştirilmiş kayıt ({short})"
    person.birth_date = None
    person.phone = None
    person.email = None
    person.address = None
    person.external_ref = None
    person.grade = None
    person.title = None
    person.department = None
    person.status = PersonStatus.passive
    person.anonymized_at = dt.datetime.now(dt.timezone.utc)

    # Kartlar iptal edilir. SİLİNEMEZLER: olaylar onlara atıf yapıyor.
    # Kart numarası olaylarda kalır ama artık bir kişiye bağlı değildir —
    # takma ad hâline gelir.
    creds = (
        await db.execute(select(Credential).where(Credential.person_id == person.id))
    ).scalars().all()
    for c in creds:
        c.status = CredentialStatus.revoked
        c.revoked_at = dt.datetime.now(dt.timezone.utc)
        c.label = None

    # Veli bağlantıları kaldırılır. Veli kaydının kendisi, BAŞKA bir
    # öğrenciye de bağlıysa korunur — o öğrencinin verisi silinmemeli.
    links = (
        await db.execute(
            select(PersonGuardian).where(PersonGuardian.person_id == person.id)
        )
    ).scalars().all()

    for link in links:
        gid = link.guardian_id
        await db.delete(link)
        await db.flush()
        # Başka çocuğa bağlı değilse veli de temizlenir. Bildirim kaydı varsa
        # satır silinemez (FK RESTRICT), kimliği temizlenir — ayrıntı
        # `_cleanup_orphan_guardian` içinde.
        await _cleanup_orphan_guardian(db, gid)

    # Koç atamaları kaldırılır
    for link in (
        await db.execute(
            select(CoachAssignment).where(
                (CoachAssignment.student_person_id == person.id)
                | (CoachAssignment.coach_person_id == person.id)
            )
        )
    ).scalars().all():
        await db.delete(link)

    await db.commit()
    await db.refresh(person)
    return PersonOut.model_validate(person)


# ---------------------------------------------------------------------------
# Koç ataması (kontrat §1.3)
# ---------------------------------------------------------------------------
@router.get("/persons/{person_id}/coaches", response_model=list[PersonOut])
async def list_coaches(
    person_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[PersonOut]:
    """Öğrenciye atanmış koçlar."""
    await assert_can_see_person(db, user, person_id)
    rows = (
        await db.execute(
            select(Person)
            .join(CoachAssignment, CoachAssignment.coach_person_id == Person.id)
            .where(CoachAssignment.student_person_id == person_id)
            .order_by(Person.full_name)
        )
    ).scalars().all()
    return [PersonOut.model_validate(p) for p in rows]


@router.post("/persons/{person_id}/coaches/{coach_person_id}",
             status_code=status.HTTP_201_CREATED)
async def assign_coach(
    person_id: uuid.UUID, coach_person_id: uuid.UUID,
    user: AdminUser, db: DbSession,
) -> dict[str, str]:
    """
    Öğrenciye koç atar. Koç YALNIZCA atandığı öğrencileri görebilir (§1.3),
    dolayısıyla bu uç bir yetki işlemidir — admin gerektirir.
    """
    student = await _get_person(db, user.tenant_id, person_id)
    coach = await _get_person(db, user.tenant_id, coach_person_id)

    if coach.person_type != PersonType.coach:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{coach.full_name}' koç değil (tür: {coach.person_type.value})",
        )
    if student.id == coach.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "kişi kendi koçu olamaz")

    db.add(CoachAssignment(coach_person_id=coach.id, student_person_id=student.id))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "bu koç zaten atanmış") from exc
    return {"status": "atandı"}


@router.delete("/persons/{person_id}/coaches/{coach_person_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def unassign_coach(
    person_id: uuid.UUID, coach_person_id: uuid.UUID,
    user: AdminUser, db: DbSession,
) -> None:
    link = (
        await db.execute(
            select(CoachAssignment).where(
                CoachAssignment.student_person_id == person_id,
                CoachAssignment.coach_person_id == coach_person_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "atama bulunamadı")
    await db.delete(link)
    await db.commit()


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID, user: AdminUser, db: DbSession
) -> None:
    """
    Yalnızca HİÇ KULLANILMAMIŞ kart silinebilir (yanlış girilen numara gibi).
    Kullanılmışsa `event` kayıtları ona atıf yapar ve FK RESTRICT engeller;
    o durumda doğru işlem PATCH ile `revoked` yapmaktır (§1.2).
    """
    cred = (
        await db.execute(
            select(Credential).where(
                Credential.id == credential_id, Credential.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kart bulunamadı")

    used = (
        await db.execute(
            select(func.count()).select_from(Event).where(Event.credential_id == credential_id)
        )
    ).scalar_one()
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"bu kart {used} olayda kullanılmış, silinemez — "
            "PATCH /credentials/{id} ile 'revoked' yapın",
        )

    await db.delete(cred)
    await db.commit()
