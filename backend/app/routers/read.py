"""NÖBET — Okuma uçları: olaylar, düğümler, dashboard (kontrat §3.5–§3.7)"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app import notify
from app.db import SessionLocal
from app.deps import (
    AdminUser, CurrentUser, DbSession, StaffUser, assert_can_see_person,
)
from app.models import (
    AppRole,
    AttendanceSession,
    CoachAssignment,
    Event,
    EventDecision,
    Node,
    NodeStatus,
    Person,
    PersonStatus,
    PersonType,
    SessionState,
    Zone,
)
from app.schemas import (
    DashboardOut,
    EventOut,
    EventPage,
    InsideNowOut,
    ManualSessionIn,
    ManualSessionOut,
    NodeOut,
    SessionOut,
    SessionPage,
    SessionPatch,
)

log = logging.getLogger("nobet.read")
router = APIRouter(tags=["read"])


@router.get("/nodes", response_model=list[NodeOut])
async def list_nodes(user: CurrentUser, db: DbSession) -> list[NodeOut]:
    rows = (
        await db.execute(
            select(Node).where(Node.tenant_id == user.tenant_id).order_by(Node.node_key)
        )
    ).scalars().all()
    return [NodeOut.model_validate(n) for n in rows]


@router.get("/events", response_model=EventPage)
async def list_events(
    user: StaffUser,
    db: DbSession,
    person_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    decision: EventDecision | None = None,
    date_from: dt.datetime | None = Query(default=None, alias="from"),
    date_to: dt.datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> EventPage:
    conds = [Event.tenant_id == user.tenant_id]
    if person_id:
        conds.append(Event.person_id == person_id)
    if node_id:
        conds.append(Event.node_id == node_id)
    if decision:
        conds.append(Event.decision == decision)
    if date_from:
        conds.append(Event.effective_ts >= date_from)
    if date_to:
        conds.append(Event.effective_ts <= date_to)

    total = (await db.execute(select(func.count()).select_from(Event).where(*conds))).scalar_one()

    rows = (
        await db.execute(
            select(Event)
            .where(*conds)
            .order_by(Event.effective_ts.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()

    return EventPage(
        total=total, page=page, size=size,
        items=[EventOut.model_validate(e) for e in rows],
    )


@router.get("/events/stream")
async def stream_events(user: StaffUser, db: DbSession) -> StreamingResponse:
    """
    §3.6 — canlı olay akışı (Server-Sent Events).

    Alım hattı ayrı bir konteynerde çalıştığı için süreç içi pub/sub yok;
    akış `event.id` imlecini saniyede bir yoklayarak ilerler. Düğüm sayısı
    ve olay hızı düşük olduğundan bu yeterli. Yük artarsa PostgreSQL
    LISTEN/NOTIFY'a geçilmeli.
    """
    tenant_id = user.tenant_id

    last_id = (
        await db.execute(
            select(func.coalesce(func.max(Event.id), 0)).where(Event.tenant_id == tenant_id)
        )
    ).scalar_one()

    async def gen() -> AsyncGenerator[str, None]:
        cursor = last_id
        idle = 0
        # Kendi oturumumuzu açıyoruz: istek bağımlılığının oturumu akış
        # boyunca havuzu meşgul etmesin.
        async with SessionLocal() as stream_db:
            while True:
                rows = (
                    await stream_db.execute(
                        select(Event)
                        .where(Event.tenant_id == tenant_id, Event.id > cursor)
                        .order_by(Event.id)
                        .limit(100)
                    )
                ).scalars().all()

                if rows:
                    for e in rows:
                        cursor = e.id
                        payload = EventOut.model_validate(e).model_dump_json()
                        yield f"id: {e.id}\nevent: reading\ndata: {payload}\n\n"
                    idle = 0
                else:
                    idle += 1
                    # Ara sunucular boşta kalan bağlantıyı kesmesin
                    if idle >= 15:
                        idle = 0
                        yield ": keepalive\n\n"

                # ⚠️ HER YOKLAMADAN SONRA İŞLEMİ KAPAT.
                # SQLAlchemy ilk sorguda örtük bir işlem başlatır. Kapatılmazsa
                # SSE bağlantısı açık kaldığı sürece (saatlerce) işlem de açık
                # kalır ve okuduğu tablolarda ACCESS SHARE kilidi tutar.
                # Sonuç: `ALTER TABLE` gibi DDL komutları süresiz bekler ve
                # PostgreSQL'in kilit kuyruğu sıralı olduğu için ARKALARINDAKİ
                # tüm okumalar da bloke olur. 2026-08-09'da tam olarak bu
                # yaşandı: migration 8.5 saat asılı kaldı.
                await stream_db.rollback()
                await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/open", response_model=list[InsideNowOut])
async def sessions_open(user: CurrentUser, db: DbSession) -> list[InsideNowOut]:
    """§3.6 — şu an içeride olanlar."""
    now = dt.datetime.now(dt.timezone.utc)
    rows = (
        await db.execute(
            select(AttendanceSession, Person, Zone)
            .join(Person, Person.id == AttendanceSession.person_id)
            .join(Zone, Zone.id == AttendanceSession.zone_id)
            .where(
                AttendanceSession.tenant_id == user.tenant_id,
                AttendanceSession.state == SessionState.open,
            )
            .order_by(AttendanceSession.entered_at)
        )
    ).all()

    visible = []
    for s, p, z in rows:
        if user.role == AppRole.coach:
            try:
                await assert_can_see_person(db, user, p.id)
            except HTTPException:
                continue
        visible.append(
            InsideNowOut(
                person_id=p.id, full_name=p.full_name, person_type=p.person_type,
                zone_id=z.id, zone_name=z.name, entered_at=s.entered_at,
                elapsed_seconds=int((now - s.entered_at).total_seconds()),
            )
        )
    return visible


@router.get("/sessions", response_model=SessionPage)
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
    person_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    state: SessionState | None = None,
    date_from: dt.datetime | None = Query(default=None, alias="from"),
    date_to: dt.datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> SessionPage:
    conds = [AttendanceSession.tenant_id == user.tenant_id]

    # Koç yalnızca kendi öğrencilerini görebilir (§1.3)
    if user.role == AppRole.coach:
        if person_id is not None:
            await assert_can_see_person(db, user, person_id)
            conds.append(AttendanceSession.person_id == person_id)
        else:
            allowed = (
                await db.execute(
                    select(CoachAssignment.student_person_id)
                    .where(CoachAssignment.coach_person_id == user.person_id)
                )
            ).scalars().all()
            if not allowed:
                return SessionPage(total=0, page=page, size=size, items=[])
            conds.append(AttendanceSession.person_id.in_(allowed))
    elif person_id is not None:
        conds.append(AttendanceSession.person_id == person_id)

    if zone_id:
        conds.append(AttendanceSession.zone_id == zone_id)
    if state:
        conds.append(AttendanceSession.state == state)
    if date_from:
        conds.append(AttendanceSession.entered_at >= date_from)
    if date_to:
        conds.append(AttendanceSession.entered_at <= date_to)

    total = (
        await db.execute(select(func.count()).select_from(AttendanceSession).where(*conds))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AttendanceSession).where(*conds)
            .order_by(AttendanceSession.entered_at.desc())
            .offset((page - 1) * size).limit(size)
        )
    ).scalars().all()

    return SessionPage(
        total=total, page=page, size=size,
        items=[SessionOut.model_validate(s) for s in rows],
    )


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def correct_session(
    session_id: uuid.UUID, body: SessionPatch, user: AdminUser, db: DbSession
) -> SessionOut:
    """
    §3.6 — unutulan çıkışın düzeltilmesi.

    Ham `event` kayıtlarına DOKUNULMAZ; yalnızca türetilmiş oturum düzeltilir
    (kontrat §0). Kim düzeltti bilgisi `corrected_by` ile saklanır.
    """
    s = (
        await db.execute(
            select(AttendanceSession).where(
                AttendanceSession.id == session_id,
                AttendanceSession.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "oturum bulunamadı")

    if body.exited_at is not None:
        exited = body.exited_at
        if exited.tzinfo is None:
            exited = exited.replace(tzinfo=dt.timezone.utc)
        if exited < s.entered_at:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "çıkış saati girişten önce olamaz",
            )
        s.exited_at = exited
        s.duration_seconds = int((exited - s.entered_at).total_seconds())
        s.state = SessionState.corrected

    if body.note is not None:
        s.note = body.note

    s.corrected_by = user.id
    await db.commit()
    await db.refresh(s)
    return SessionOut.model_validate(s)


# ---------------------------------------------------------------------------
# Elle giriş/çıkış (Faz 13a-5)
# ---------------------------------------------------------------------------
# ⚠️ Bu uç `event` tablosuna DOKUNMAZ. Kart okunmadı; ham olay akışına
# insan eliyle satır yazmak, `event`'in tek değerini — "bir okuyucu bir kart
# okudu" güvencesini — yok ederdi (Faz 0). İnsan müdahalesi türetilmiş
# katmanda kalır, `corrected_by` mekanizmasıyla aynı felsefe.
MANUAL_BACKDATE_LIMIT = dt.timedelta(hours=24)


@router.post("/sessions/manual", response_model=ManualSessionOut,
             status_code=status.HTTP_201_CREATED)
async def manual_session(
    body: ManualSessionIn, user: StaffUser, db: DbSession
) -> ManualSessionOut:
    """
    Kartsız giriş/çıkış — kapıdaki görevli için.

    Öğrenci kartını unutur, kart bozulur ya da okuyucu arıza yaparsa kayıt
    yine tutulabilsin diye. Bugüne kadar bunun hiçbir yolu yoktu: kart
    okunmazsa öğrenci sistemde hiç görünmüyor, yoklamada devamsız çıkıyordu.

    **Değiştirmeli (toggle)** çalışır — okuyucularla aynı: açık oturum varsa
    kapanır, yoksa açılır. Görevlinin yön seçmesi gerekmez.
    """
    person = (
        await db.execute(
            select(Person).where(
                Person.id == body.person_id, Person.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kişi bulunamadı")
    if person.anonymized_at is not None:
        # KVKK ile temizlenmiş kayda yeni veri bağlamak, silmenin anlamını
        # ortadan kaldırırdı.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "anonimleştirilmiş kayda giriş açılamaz"
        )
    if person.status != PersonStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "pasif kişiye giriş açılamaz")

    zone = (
        await db.execute(
            select(Zone).where(Zone.id == body.zone_id, Zone.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mekân bulunamadı")

    now = dt.datetime.now(dt.timezone.utc)
    at = body.at or now
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.timezone.utc)

    # Geleceğe kayıt açmak devam kaydını uydurmaktır.
    if at > now + dt.timedelta(minutes=5):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "gelecek bir saate kayıt açılamaz"
        )
    # Geriye dönük kayda sınır: görevli sabahki girişi öğlen girebilmeli ama
    # haftalar öncesini "hatırlayamamalı".
    if at < now - MANUAL_BACKDATE_LIMIT:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "en fazla 24 saat geriye kayıt açılabilir",
        )

    open_session = (
        await db.execute(
            select(AttendanceSession).where(
                AttendanceSession.person_id == person.id,
                AttendanceSession.zone_id == zone.id,
                AttendanceSession.tenant_id == user.tenant_id,
                AttendanceSession.state == SessionState.open,
            )
        )
    ).scalar_one_or_none()

    if open_session is not None:
        # --- ÇIKIŞ ---
        if at < open_session.entered_at:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "çıkış saati girişten önce olamaz",
            )
        open_session.exited_at = at
        open_session.duration_seconds = int((at - open_session.entered_at).total_seconds())
        open_session.state = SessionState.closed
        # Kaydı kimin kapattığı da iz bırakmalı. Oturum kartla açılmış olsa
        # bile çıkışı elle verildiyse bu bilinmeli.
        open_session.corrected_by = user.id
        note = (body.note or "").strip()
        open_session.note = ((open_session.note or "") + " " + note).strip() or None

        # Veliye haber ver. Bu çıkış için hiç `event` üretilmiyor; kartla
        # açılmış bir oturum bile olsa haber vermenin TEK yolu bu.
        # Bildirim oturumla AYNI işlemde yazılır (olay yolundaki kural):
        # biri yazılıp diğeri yazılmadan kalmasın.
        n = await notify.enqueue_for_session(db, open_session, zone, "ÇIKIŞ")
        await db.commit()
        await db.refresh(open_session)
        log.info("elle CIKIS: kisi=%s mekan=%s gorevli=%s bildirim=%d",
                 person.full_name, zone.name, user.email, n)
        # ⚠️ `model_validate(orm)` KULLANILMAZ: `direction` ORM nesnesinde
        # yok, zorunlu alan olduğu için doğrulama patlar. Önce SessionOut
        # üretilip üstüne ekleniyor.
        return ManualSessionOut(
            **SessionOut.model_validate(open_session).model_dump(),
            direction="ÇIKIŞ",
        )

    # --- GİRİŞ ---
    s = AttendanceSession(
        tenant_id=user.tenant_id,
        person_id=person.id,
        zone_id=zone.id,
        entry_event_id=None,          # kart okunmadı — olay YOK
        entered_at=at,
        state=SessionState.open,
        entry_source="manual",
        created_by=user.id,
        note=(body.note or "").strip() or None,
    )
    db.add(s)
    # `flush` şart: bildirim `session_id`'ye bağlanacak, id COMMIT'ten önce
    # gerekli.
    await db.flush()
    n = await notify.enqueue_for_session(db, s, zone, "GİRİŞ")
    await db.commit()
    await db.refresh(s)
    log.info("elle GIRIS: kisi=%s mekan=%s gorevli=%s bildirim=%d",
             person.full_name, zone.name, user.email, n)
    return ManualSessionOut(
        **SessionOut.model_validate(s).model_dump(),
        direction="GİRİŞ",
    )


@router.get("/dashboard/summary", response_model=DashboardOut)
async def dashboard(user: CurrentUser, db: DbSession) -> DashboardOut:
    tid = user.tenant_id
    now = dt.datetime.now(dt.timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Şu an içeride olanlar, kişi tipine göre
    inside_rows = (
        await db.execute(
            select(Person.person_type, func.count())
            .select_from(AttendanceSession)
            .join(Person, Person.id == AttendanceSession.person_id)
            .where(AttendanceSession.tenant_id == tid, AttendanceSession.state == SessionState.open)
            .group_by(Person.person_type)
        )
    ).all()
    inside = {pt.value: 0 for pt in PersonType}
    for ptype, cnt in inside_rows:
        inside[ptype.value] = cnt

    today_events = (
        await db.execute(
            select(func.count()).select_from(Event)
            .where(Event.tenant_id == tid, Event.effective_ts >= today_start)
        )
    ).scalar_one()

    node_rows = (
        await db.execute(
            select(Node.status, func.count()).where(Node.tenant_id == tid).group_by(Node.status)
        )
    ).all()
    nodes = {ns.value: 0 for ns in NodeStatus}
    for st, cnt in node_rows:
        nodes[st.value] = cnt

    open_sessions = (
        await db.execute(
            select(func.count()).select_from(AttendanceSession)
            .where(AttendanceSession.tenant_id == tid, AttendanceSession.state == SessionState.open)
        )
    ).scalar_one()

    unknown_24h = (
        await db.execute(
            select(func.count()).select_from(Event).where(
                Event.tenant_id == tid,
                Event.decision == EventDecision.unknown_credential,
                Event.effective_ts >= now - dt.timedelta(hours=24),
            )
        )
    ).scalar_one()

    return DashboardOut(
        inside_now=inside,
        today_events=today_events,
        nodes=nodes,
        open_sessions=open_sessions,
        unknown_reads_24h=unknown_24h,
    )
