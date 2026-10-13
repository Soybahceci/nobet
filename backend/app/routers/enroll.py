"""
NÖBET — Enrollment (kontrat §3.4)
==================================
"Sıfır CLI" kuralının kalbi: kurum kart kaydını teknik bilgi olmadan yapar.

    1. Operatör "Kart Ata" der, öğrenciyi seçer
    2. Ekran: "Kartı okutucuya okutun..."
    3. Öğrenci kartı okutur → unknown_credential olayı düşer → ekranda UID belirir
    4. Operatör onaylar → credential oluşur, olay geriye dönük ilişkilendirilir
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.config import settings
from app.deps import DbSession, StaffUser
from app.models import Credential, Event, EventDecision, Node, Person
from app.schemas import CredentialOut, EnrollClaimIn, EnrollPendingOut

router = APIRouter(prefix="/enroll", tags=["enroll"])


@router.get("/pending", response_model=list[EnrollPendingOut])
async def pending(
    user: StaffUser,
    db: DbSession,
    window: int = Query(default=settings.enroll_window_seconds, ge=1, le=3600),
) -> list[EnrollPendingOut]:
    """Son `window` saniyedeki kayıtsız okumalar."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=window)

    # Olaylar DEĞİŞMEZ, dolayısıyla sahiplenme sonrası geçmiş olayın
    # credential_id'si dolmaz. "Hâlâ kayıtsız mı?" sorusu bu yüzden
    # credential tablosuna bakılarak yanıtlanır.
    rows = (
        await db.execute(
            select(Event, Node.name)
            .join(Node, Node.id == Event.node_id)
            .outerjoin(
                Credential,
                (Credential.tenant_id == Event.tenant_id)
                & (Credential.type == Event.cred_type)
                & (Credential.identifier == Event.cred_identifier),
            )
            .where(
                Event.tenant_id == user.tenant_id,
                Event.decision == EventDecision.unknown_credential,
                Event.effective_ts >= since,
                Credential.id.is_(None),      # bu kart hâlâ kayıtsız
            )
            .order_by(Event.effective_ts.desc())
            .limit(50)
        )
    ).all()

    return [
        EnrollPendingOut(
            event_id=e.id,
            cred_type=e.cred_type,
            cred_identifier=e.cred_identifier,
            node_name=node_name,
            seen_at=e.effective_ts,
        )
        for e, node_name in rows
    ]


@router.post("/claim", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def claim(body: EnrollClaimIn, user: StaffUser, db: DbSession) -> CredentialOut:
    """Kartı bir kişiye bağla ve olayı geriye dönük ilişkilendir."""
    event = (
        await db.execute(
            select(Event).where(Event.id == body.event_id, Event.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "olay bulunamadı")
    if event.decision != EventDecision.unknown_credential:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"bu olay kayıtsız bir okuma değil (karar: {event.decision.value})",
        )

    person = (
        await db.execute(
            select(Person).where(Person.id == body.person_id, Person.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kişi bulunamadı")

    # Kart başkasına kayıtlı mı? UNIQUE(tenant, type, identifier) zaten
    # engelliyor ama net bir hata mesajı vermek arayüz için daha iyi.
    existing = (
        await db.execute(
            select(Credential).where(
                Credential.tenant_id == user.tenant_id,
                Credential.type == event.cred_type,
                Credential.identifier == event.cred_identifier,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "bu kart zaten kayıtlı; önce mevcut kaydı iptal edin",
        )

    cred = Credential(
        tenant_id=user.tenant_id,
        person_id=person.id,
        type=event.cred_type,
        identifier=event.cred_identifier,
        label=body.label,
    )
    db.add(cred)
    await db.flush()

    # ⚠️ event DEĞİŞMEZ — satır UPDATE edilemez (trigger engeller).
    # Geriye dönük ilişkilendirme, olayın kararını değiştirmeden yalnızca
    # çözümleme alanlarını doldurur; bu yüzden trigger'ı geçici olarak
    # atlamak yerine ilişkilendirmeyi credential üzerinden kuruyoruz:
    # aynı (tenant, type, identifier) taşıyan geçmiş olaylar sorgu anında
    # credential ile eşleşir. Ham olay kaydı bozulmaz.
    #
    # Bu, kontrat §3.4'teki "o olayı geriye dönük ilişkilendirir" ifadesini
    # değişmezlik ilkesini (§0) çiğnemeden karşılar.

    await db.commit()
    await db.refresh(cred)
    return CredentialOut.model_validate(cred)
