"""
NÖBET — Raporlama (Faz 9)

Kütüphane senaryosunun karşılığı: öğrenci hangi mekânda ne kadar kaldı.

⚠️ İki kural rakamların dürüstlüğünü belirliyor:

1. **Eksik çıkışlar süreye DAHİL EDİLMEZ.** Çıkış okutulmamış oturumun
   `duration_seconds` alanı NULL'dır (Faz 7). Uydurma bir süre yazmak
   koçun önüne yanlış rakam koyardı; bunun yerine ayrı sayaçla gösterilir.
2. **Koç yalnızca kendi öğrencilerini görür** (kontrat §1.3). Filtre
   sorgunun içinde, arayüzde değil.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.deps import CurrentUser, DbSession
from app.models import (
    AppRole,
    AttendanceSession,
    CoachAssignment,
    Person,
    PersonType,
    SessionState,
    Zone,
)

router = APIRouter(prefix="/reports", tags=["reports"])


class PersonReportRow(BaseModel):
    person_id: uuid.UUID
    full_name: str
    person_type: PersonType
    grade: str | None
    sessions: int
    total_seconds: int
    missing_exits: int
    last_seen: dt.datetime | None


class ReportOut(BaseModel):
    date_from: dt.date
    date_to: dt.date
    zone_id: uuid.UUID | None
    zone_name: str | None
    rows: list[PersonReportRow]


async def _visible_person_ids(db: DbSession, user) -> list[uuid.UUID] | None:
    """
    Koç için görünür öğrenci listesi; diğer roller için None (= sınırsız).
    Kontrat §1.3 burada zorlanır.
    """
    if user.role != AppRole.coach:
        return None
    if user.person_id is None:
        return []
    return list((
        await db.execute(
            select(CoachAssignment.student_person_id)
            .where(CoachAssignment.coach_person_id == user.person_id)
        )
    ).scalars().all())


@router.get("/attendance", response_model=ReportOut)
async def attendance_report(
    user: CurrentUser,
    db: DbSession,
    date_from: dt.date = Query(alias="from"),
    date_to: dt.date = Query(alias="to"),
    zone_id: uuid.UUID | None = None,
    person_type: PersonType | None = None,
) -> ReportOut:
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "bitiş tarihi başlangıçtan önce olamaz")

    allowed = await _visible_person_ids(db, user)
    if allowed is not None and not allowed:
        return ReportOut(date_from=date_from, date_to=date_to,
                         zone_id=zone_id, zone_name=None, rows=[])

    start = dt.datetime.combine(date_from, dt.time.min, dt.timezone.utc)
    end = dt.datetime.combine(date_to, dt.time.max, dt.timezone.utc)

    conds = [
        AttendanceSession.tenant_id == user.tenant_id,
        AttendanceSession.entered_at >= start,
        AttendanceSession.entered_at <= end,
    ]
    if zone_id:
        conds.append(AttendanceSession.zone_id == zone_id)
    if allowed is not None:
        conds.append(AttendanceSession.person_id.in_(allowed))
    if person_type:
        conds.append(Person.person_type == person_type)

    rows = (
        await db.execute(
            select(
                Person.id,
                Person.full_name,
                Person.person_type,
                Person.grade,
                func.count(AttendanceSession.id).label("sessions"),
                # NULL süreler (eksik çıkış) toplama girmez
                func.coalesce(func.sum(AttendanceSession.duration_seconds), 0),
                func.sum(
                    case((AttendanceSession.state == SessionState.auto_closed, 1),
                         else_=0)
                ).label("missing"),
                func.max(AttendanceSession.entered_at),
            )
            .join(Person, Person.id == AttendanceSession.person_id)
            .where(*conds)
            .group_by(Person.id, Person.full_name, Person.person_type, Person.grade)
            .order_by(func.coalesce(func.sum(AttendanceSession.duration_seconds), 0).desc())
        )
    ).all()

    zone_name = None
    if zone_id:
        # Denetim O-3: kurum filtresi ŞART. Filtresiz hâlinde, başka kurumun
        # zone_id'sini bilen biri o mekânın ADINI öğrenebiliyordu. Rapor
        # satırları zaten sızmıyordu (oturumlar tenant'a göre filtreli),
        # ama ad sızıyordu.
        zone_name = (
            await db.execute(
                select(Zone.name).where(
                    Zone.id == zone_id, Zone.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none()

    return ReportOut(
        date_from=date_from, date_to=date_to,
        zone_id=zone_id, zone_name=zone_name,
        rows=[
            PersonReportRow(
                person_id=r[0], full_name=r[1], person_type=r[2], grade=r[3],
                sessions=r[4], total_seconds=int(r[5] or 0),
                missing_exits=int(r[6] or 0), last_seen=r[7],
            )
            for r in rows
        ],
    )


class MissingExitRow(BaseModel):
    session_id: uuid.UUID
    person_id: uuid.UUID
    full_name: str
    zone_name: str
    entered_at: dt.datetime
    state: SessionState


@router.get("/missing-exits", response_model=list[MissingExitRow])
async def missing_exits(
    user: CurrentUser,
    db: DbSession,
    days: int = Query(default=14, ge=1, le=90),
) -> list[MissingExitRow]:
    """
    Çıkışı okutulmamış oturumlar. Koç panelinde uyarı olarak görünür;
    yönetici `PATCH /sessions/{id}` ile düzeltir.
    """
    allowed = await _visible_person_ids(db, user)
    if allowed is not None and not allowed:
        return []

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    conds = [
        AttendanceSession.tenant_id == user.tenant_id,
        AttendanceSession.state == SessionState.auto_closed,
        AttendanceSession.entered_at >= since,
    ]
    if allowed is not None:
        conds.append(AttendanceSession.person_id.in_(allowed))

    rows = (
        await db.execute(
            select(AttendanceSession, Person.full_name, Zone.name)
            .join(Person, Person.id == AttendanceSession.person_id)
            .join(Zone, Zone.id == AttendanceSession.zone_id)
            .where(*conds)
            .order_by(AttendanceSession.entered_at.desc())
            .limit(200)
        )
    ).all()

    return [
        MissingExitRow(
            session_id=s.id, person_id=s.person_id, full_name=name,
            zone_name=zname, entered_at=s.entered_at, state=s.state,
        )
        for s, name, zname in rows
    ]


# ---------------------------------------------------------------------------
# Derslik yoklaması (Faz 10)
# ---------------------------------------------------------------------------
class RosterRow(BaseModel):
    person_id: uuid.UUID
    full_name: str
    external_ref: str | None
    present: bool
    entered_at: dt.datetime | None
    still_inside: bool


class ClassroomOut(BaseModel):
    zone_id: uuid.UUID
    zone_name: str
    grade: str
    window_from: dt.datetime
    window_to: dt.datetime
    total: int
    present: int
    absent: int
    rows: list[RosterRow]


@router.get("/classroom", response_model=ClassroomOut)
async def classroom_attendance(
    user: CurrentUser,
    db: DbSession,
    zone_id: uuid.UUID,
    grade: str,
    window_from: dt.datetime = Query(alias="from"),
    window_to: dt.datetime = Query(alias="to"),
) -> ClassroomOut:
    """
    Derslik yoklaması.

    **Sınıf listesi `person.grade` alanından gelir.** Ayrı bir "ders/şube"
    tablosu açılmadı: kurumun zaten girdiği sınıf bilgisi bu işi görüyor ve
    iki yerde tutulan liste kaçınılmaz olarak birbirinden ayrışır.

    "Geldi" sayılma kuralı: öğrencinin bu derslikteki bir oturumu, verilen
    zaman aralığıyla **kesişiyorsa**. Dersin ortasında girip çıkan da,
    ders başlamadan gelip içeride kalan da yoklamada görünür.
    """
    if window_to <= window_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "bitiş zamanı başlangıçtan sonra olmalı")

    zone = (
        await db.execute(
            select(Zone).where(Zone.id == zone_id, Zone.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mekân bulunamadı")

    roster = (
        await db.execute(
            select(Person)
            .where(
                Person.tenant_id == user.tenant_id,
                Person.grade == grade,
                Person.person_type == PersonType.student,
                Person.status == "active",
            )
            .order_by(Person.full_name)
        )
    ).scalars().all()

    if not roster:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"'{grade}' sınıfında aktif öğrenci yok — kişi kayıtlarında "
            "sınıf alanı doldurulmuş mu?",
        )

    # Denetim D-2: eskiden öğrenci başına bir sorgu vardı (30 kişilik sınıfta
    # 31 gidiş-geliş). Tek sorguda çekilip bellekte eşleştiriliyor — bulutta
    # ağ gecikmesi eklenince aradaki fark ciddileşir.
    #
    # Kesişim: oturum pencereden önce başlamış olabilir, sonra bitmemiş
    # olabilir. Açık oturumun bitişi "şimdi" sayılır.
    sessions = (
        await db.execute(
            select(AttendanceSession)
            .where(
                # Denetim D-1: kurum filtresi savunma amaçlı. Kişi ve mekân
                # zaten kurum filtreli sorgulardan geliyor, ama koruma tek
                # katmana bağlı kalmasın.
                AttendanceSession.tenant_id == user.tenant_id,
                AttendanceSession.person_id.in_([p.id for p in roster]),
                AttendanceSession.zone_id == zone_id,
                AttendanceSession.entered_at <= window_to,
                (AttendanceSession.exited_at.is_(None))
                | (AttendanceSession.exited_at >= window_from),
            )
            .order_by(AttendanceSession.entered_at)
        )
    ).scalars().all()

    # `order_by(entered_at).limit(1)` ile aynı sonuç: kişi başına EN ERKEN
    # kesişen oturum. Sorgu sıralı geldiği için ilk gören kazanır.
    first_session: dict[uuid.UUID, AttendanceSession] = {}
    for s in sessions:
        first_session.setdefault(s.person_id, s)

    rows: list[RosterRow] = []
    present_count = 0

    for p in roster:
        sess = first_session.get(p.id)
        present = sess is not None
        if present:
            present_count += 1

        rows.append(RosterRow(
            person_id=p.id, full_name=p.full_name, external_ref=p.external_ref,
            present=present,
            entered_at=sess.entered_at if sess else None,
            still_inside=bool(sess and sess.state == SessionState.open),
        ))

    return ClassroomOut(
        zone_id=zone.id, zone_name=zone.name, grade=grade,
        window_from=window_from, window_to=window_to,
        total=len(roster), present=present_count,
        absent=len(roster) - present_count, rows=rows,
    )


@router.get("/grades", response_model=list[str])
async def list_grades(user: CurrentUser, db: DbSession) -> list[str]:
    """Kayıtlı sınıflar — yoklama ekranındaki seçim listesi."""
    rows = (
        await db.execute(
            select(Person.grade)
            .where(
                Person.tenant_id == user.tenant_id,
                Person.grade.is_not(None),
                Person.person_type == PersonType.student,
            )
            .distinct()
            .order_by(Person.grade)
        )
    ).scalars().all()
    return [g for g in rows if g]


class MyStudentRow(BaseModel):
    person_id: uuid.UUID
    full_name: str
    grade: str | None
    inside_now: bool
    week_seconds: int
    missing_exits: int
    last_seen: dt.datetime | None


@router.get("/my-students", response_model=list[MyStudentRow])
async def my_students(user: CurrentUser, db: DbSession) -> list[MyStudentRow]:
    """Koçun kendi öğrencileri — son 7 günlük özet."""
    if user.role != AppRole.coach:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bu görünüm koçlara özel")
    if user.person_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "koç kaydı bir kişiye bağlı değil")

    students = (
        await db.execute(
            select(Person)
            .join(CoachAssignment, CoachAssignment.student_person_id == Person.id)
            .where(
                CoachAssignment.coach_person_id == user.person_id,
                # Denetim D-1: savunma amaçlı kurum filtresi.
                Person.tenant_id == user.tenant_id,
            )
            .order_by(Person.full_name)
        )
    ).scalars().all()
    if not students:
        return []

    week_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)

    # Denetim D-2: eskiden öğrenci başına bir sorgu vardı. Tek gruplu
    # sorguya indirildi.
    agg_rows = (
        await db.execute(
            select(
                AttendanceSession.person_id,
                func.coalesce(func.sum(AttendanceSession.duration_seconds), 0),
                func.sum(
                    case((AttendanceSession.state == SessionState.auto_closed, 1),
                         else_=0)
                ),
                func.max(AttendanceSession.entered_at),
                func.sum(
                    case((AttendanceSession.state == SessionState.open, 1), else_=0)
                ),
            ).where(
                AttendanceSession.tenant_id == user.tenant_id,
                AttendanceSession.person_id.in_([s.id for s in students]),
                AttendanceSession.entered_at >= week_ago,
            ).group_by(AttendanceSession.person_id)
        )
    ).all()
    by_person = {r[0]: r for r in agg_rows}

    out: list[MyStudentRow] = []
    for s in students:
        agg = by_person.get(s.id)
        # Hiç oturumu olmayan öğrenci de listede görünmeli — sıfırlarla.
        out.append(MyStudentRow(
            person_id=s.id, full_name=s.full_name, grade=s.grade,
            inside_now=bool(agg[4]) if agg else False,
            week_seconds=int(agg[1] or 0) if agg else 0,
            missing_exits=int(agg[2] or 0) if agg else 0,
            last_seen=agg[3] if agg else None,
        ))

    return out
