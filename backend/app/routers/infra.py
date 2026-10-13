"""NÖBET — Mekân ve düğüm yönetimi (kontrat §3.5)"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import Event, EventDecision, Lesson, Node, Tenant, Zone
from app.schemas import (
    LessonIn,
    LessonOut,
    LessonPatch,
    LessonTodayOut,
    NodeHealthOut,
    NodeIn,
    NodeOut,
    NodePatch,
    ZoneIn,
    ZoneOut,
)

log = logging.getLogger("nobet.infra")
router = APIRouter(tags=["infra"])


# --- Mekân -----------------------------------------------------------------
@router.get("/zones", response_model=list[ZoneOut])
async def list_zones(user: CurrentUser, db: DbSession) -> list[ZoneOut]:
    rows = (
        await db.execute(
            select(Zone).where(Zone.tenant_id == user.tenant_id).order_by(Zone.name)
        )
    ).scalars().all()
    return [ZoneOut.model_validate(z) for z in rows]


@router.post("/zones", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
async def create_zone(body: ZoneIn, user: AdminUser, db: DbSession) -> ZoneOut:
    if body.parent_zone_id is not None:
        parent = (
            await db.execute(
                select(Zone).where(
                    Zone.id == body.parent_zone_id, Zone.tenant_id == user.tenant_id
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "üst mekân bulunamadı")

    zone = Zone(tenant_id=user.tenant_id, **body.model_dump())
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return ZoneOut.model_validate(zone)


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
async def update_zone(
    zone_id: uuid.UUID, body: ZoneIn, user: AdminUser, db: DbSession
) -> ZoneOut:
    zone = (
        await db.execute(
            select(Zone).where(Zone.id == zone_id, Zone.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mekân bulunamadı")
    if body.parent_zone_id == zone_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "mekân kendi üstü olamaz")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    await db.commit()
    await db.refresh(zone)
    return ZoneOut.model_validate(zone)


# --- Düğüm -----------------------------------------------------------------
@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def create_node(body: NodeIn, user: AdminUser, db: DbSession) -> NodeOut:
    zone = (
        await db.execute(
            select(Zone).where(Zone.id == body.zone_id, Zone.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mekân bulunamadı")

    node = Node(tenant_id=user.tenant_id, **body.model_dump())
    db.add(node)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{body.node_key}' anahtarlı düğüm zaten var",
        ) from exc
    await db.refresh(node)
    return NodeOut.model_validate(node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: uuid.UUID, body: NodePatch, user: AdminUser, db: DbSession
) -> NodeOut:
    node = (
        await db.execute(
            select(Node).where(Node.id == node_id, Node.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "düğüm bulunamadı")

    # node_key BİLEREK değiştirilemez: firmware'deki NODE_KEY ile eşleşmesi
    # gerekiyor ve geçmiş olaylar bu düğüme bağlı. Değişmesi gerekiyorsa
    # yeni düğüm tanımlanır.
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    await db.commit()
    await db.refresh(node)
    return NodeOut.model_validate(node)


@router.get("/nodes/{node_id}/health", response_model=NodeHealthOut)
async def node_health(
    node_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> NodeHealthOut:
    node = (
        await db.execute(
            select(Node).where(Node.id == node_id, Node.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "düğüm bulunamadı")

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    events_24h = (
        await db.execute(
            select(func.count()).select_from(Event)
            .where(Event.node_id == node_id, Event.effective_ts >= since)
        )
    ).scalar_one()
    unknown_24h = (
        await db.execute(
            select(func.count()).select_from(Event).where(
                Event.node_id == node_id,
                Event.effective_ts >= since,
                Event.decision == EventDecision.unknown_credential,
            )
        )
    ).scalar_one()

    return NodeHealthOut(
        node_key=node.node_key,
        status=node.status,
        last_seen_at=node.last_seen_at,
        firmware_version=node.firmware_version,
        events_24h=events_24h,
        unknown_24h=unknown_24h,
        reader_ok=node.reader_ok,
        reader_reinits=node.reader_reinits,
    )


# ---------------------------------------------------------------------------
# Ders programı (kontrat §3.5, v1.9)
# ---------------------------------------------------------------------------
async def _tenant_tz(db: DbSession, tenant_id: uuid.UUID) -> ZoneInfo:
    name = (
        await db.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    try:
        return ZoneInfo(name or settings.timezone)
    except Exception:
        # Kurumun dilimi bozuksa uygulamanın varsayılanına düş; yoklama
        # ekranı hiç açılmamaktansa doğru olması muhtemel bir dilimle açılsın.
        log.warning("kurum dilimi cozulemedi: %r", name)
        return ZoneInfo(settings.timezone)


async def _get_lesson(db: DbSession, tenant_id: uuid.UUID, lesson_id: uuid.UUID) -> Lesson:
    row = (
        await db.execute(
            select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ders bulunamadı")
    return row


async def _assert_zone(db: DbSession, tenant_id: uuid.UUID, zone_id: uuid.UUID) -> None:
    z = (
        await db.execute(
            select(Zone.id).where(Zone.id == zone_id, Zone.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if z is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mekân bulunamadı")


def _overlap_conds(zone_id, grade: str, weekday: int, starts, ends):
    """
    Aynı derslik + sınıf + gün içinde saat çakışması.

    Çakışma kuralı `yeni.başlangıç < var.bitiş AND yeni.bitiş > var.başlangıç`.
    Uç noktalar dahil değil: 09:00–09:50 ile 09:50–10:40 çakışmaz — arka arkaya
    derslerin normal hâli budur.
    """
    return [
        Lesson.zone_id == zone_id,
        Lesson.grade == grade,
        Lesson.weekday == weekday,
        Lesson.is_active.is_(True),
        Lesson.starts_at < ends,
        Lesson.ends_at > starts,
    ]


@router.get("/lessons", response_model=list[LessonOut])
async def list_lessons(
    user: CurrentUser,
    db: DbSession,
    zone_id: uuid.UUID | None = None,
    grade: str | None = None,
    weekday: int | None = Query(default=None, ge=1, le=7),
) -> list[LessonOut]:
    conds = [Lesson.tenant_id == user.tenant_id]
    if zone_id:
        conds.append(Lesson.zone_id == zone_id)
    if grade:
        conds.append(Lesson.grade == grade)
    if weekday:
        conds.append(Lesson.weekday == weekday)

    rows = (
        await db.execute(
            select(Lesson, Zone.name)
            .join(Zone, Zone.id == Lesson.zone_id)
            .where(*conds)
            .order_by(Lesson.weekday, Lesson.starts_at, Zone.name)
        )
    ).all()
    return [
        LessonOut(**{
            **LessonOut.model_validate(le).model_dump(), "zone_name": zn,
        })
        for le, zn in rows
    ]


@router.get("/lessons/today", response_model=list[LessonTodayOut])
async def lessons_today(
    user: CurrentUser,
    db: DbSession,
    zone_id: uuid.UUID,
    grade: str,
) -> list[LessonTodayOut]:
    """
    Bugünkü dersler, saatleri **UTC'ye çevrilmiş** hâlde.

    Yoklama ekranı bunu doğrudan kullanır; tarayıcının saat dilimine hiç
    bakılmaz. `is_current` şu an süren dersi işaretler — ekran onu ön seçili
    getirir, operatör hiçbir şey yazmaz.
    """
    tz = await _tenant_tz(db, user.tenant_id)
    now_local = dt.datetime.now(tz)
    today = now_local.date()

    rows = (
        await db.execute(
            select(Lesson, Zone.name)
            .join(Zone, Zone.id == Lesson.zone_id)
            .where(
                Lesson.tenant_id == user.tenant_id,
                Lesson.zone_id == zone_id,
                Lesson.grade == grade,
                Lesson.weekday == today.isoweekday(),
                Lesson.is_active.is_(True),
            )
            .order_by(Lesson.starts_at)
        )
    ).all()

    out: list[LessonTodayOut] = []
    for le, zn in rows:
        start_local = dt.datetime.combine(today, le.starts_at, tzinfo=tz)
        end_local = dt.datetime.combine(today, le.ends_at, tzinfo=tz)
        out.append(LessonTodayOut(
            **{**LessonOut.model_validate(le).model_dump(), "zone_name": zn},
            starts_at_utc=start_local.astimezone(dt.timezone.utc),
            ends_at_utc=end_local.astimezone(dt.timezone.utc),
            is_current=start_local <= now_local < end_local,
        ))
    return out


@router.post("/lessons", response_model=LessonOut,
             status_code=status.HTTP_201_CREATED)
async def create_lesson(body: LessonIn, user: AdminUser, db: DbSession) -> LessonOut:
    if body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "bitiş saati başlangıçtan sonra olmalı")
    await _assert_zone(db, user.tenant_id, body.zone_id)

    clash = (
        await db.execute(
            select(Lesson.name).where(
                Lesson.tenant_id == user.tenant_id,
                *_overlap_conds(body.zone_id, body.grade, body.weekday,
                                body.starts_at, body.ends_at),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"aynı gün ve derslikte saat çakışması: '{clash}'",
        )

    row = Lesson(tenant_id=user.tenant_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return LessonOut.model_validate(row)


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: uuid.UUID, body: LessonPatch, user: AdminUser, db: DbSession
) -> LessonOut:
    row = await _get_lesson(db, user.tenant_id, lesson_id)
    data = body.model_dump(exclude_unset=True)

    if "zone_id" in data:
        await _assert_zone(db, user.tenant_id, data["zone_id"])

    starts = data.get("starts_at", row.starts_at)
    ends = data.get("ends_at", row.ends_at)
    if ends <= starts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "bitiş saati başlangıçtan sonra olmalı")

    clash = (
        await db.execute(
            select(Lesson.name).where(
                Lesson.tenant_id == user.tenant_id,
                Lesson.id != row.id,          # kendisiyle çakışmasın
                *_overlap_conds(data.get("zone_id", row.zone_id),
                                data.get("grade", row.grade),
                                data.get("weekday", row.weekday), starts, ends),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"aynı gün ve derslikte saat çakışması: '{clash}'",
        )

    for field, value in data.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return LessonOut.model_validate(row)


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: uuid.UUID, user: AdminUser, db: DbSession
) -> None:
    """
    Kalıcı siler. `lesson` türetilmiş bir plan kaydı — hiçbir olaya atıf
    yapmıyor, denetim izi taşımıyor. Kişi/olay kayıtlarındaki yumuşak silme
    mantığı burada gerekmez.
    """
    row = await _get_lesson(db, user.tenant_id, lesson_id)
    await db.delete(row)
    await db.commit()
