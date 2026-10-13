"""
NÖBET — Oturum Motoru (kontrat §4.1)
=====================================
Olaylar ham ve değişmez; oturumlar onlardan TÜRETİLİR ve düzeltilebilir.
Kontrat §0: "Unutulan çıkışlar ham veriyi bozmadan düzeltilir."

    granted okuma
       ↓ açık oturum var mı? (person, zone)
       ├── VAR  → kapat, süre hesapla        -> "ÇIKIŞ"
       └── YOK  → yeni oturum aç, state=open -> "GİRİŞ"

Prototipte tüm düğümler `toggle` yönünde (Faz 0 kararı).
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AttendanceSession,
    Event,
    EventDecision,
    Node,
    SessionState,
    Tenant,
    Zone,
)

log = logging.getLogger("nobet.sessions")

DIRECTION_IN = "GİRİŞ"
DIRECTION_OUT = "ÇIKIŞ"


async def is_duplicate_read(
    db: AsyncSession, node: Node, person_id, effective_ts: dt.datetime
) -> bool:
    """
    Turnikeye yaslanma koruması (§4.1).

    ⚠️ Bu kontrol event INSERT'inden ÖNCE çalışmak ZORUNDA. Kontrat §4'ün
    adım listesi oturum motorunu INSERT'ten sonra gösteriyor ama §4.1
    `decision = "duplicate"` atıyor — `event` değişmez olduğu için yazıldıktan
    sonra karar değiştirilemez. Tek uygulanabilir sıra budur.

    Aynı MEKÂNDAKİ son okumaya bakılır (aynı düğüme değil): çift okuyuculu
    bir kapıda kişi giriş okuyucusuna, sonra hemen çıkış okuyucusuna
    yaslanabilir; ikisi de aynı mekâna aittir.

    ⚠️ **Sorulan soru: "bu olaydan ÖNCEKİ `window` içinde okuma var mı?"**
    Eskiden en yeni okumaya bakılıyor ve `(effective_ts - last) < window`
    deniyordu. Gelen olay o okumadan ESKİYSE fark negatif çıkıyor, negatif
    sayı da her zaman `window`'dan küçük olduğu için olay `duplicate`
    sayılıyordu — **oturum üretmeden.**

    Yani zaman damgası geriye giden her olay sessizce yutuluyordu:
      · kenar kuyruğu kesinti sonrası boşalırken,
      · aynı mekândaki iki okuyucunun saatleri farklıysa,
      · kenarda NTP saati geri aldığında.
    Sonuç: öğrencinin girişi yoklamada hiç görünmez.

    Bugün tek okuyucu ve canlı akış olduğu için ortaya çıkmıyordu; Faz 13a-3
    ile kenar kuyruğu devreye girince doğrudan veri kaybına dönerdi.
    Bulundu: 2026-08-10, 13a-2 testinde.

    Düzeltme sıradan bağımsız: kıyaslama YALNIZCA gelen olaydan önceki
    okumalarla yapılır.
    """
    window = dt.timedelta(seconds=settings.duplicate_window_seconds)

    last = (
        await db.execute(
            select(func.max(Event.effective_ts))
            .select_from(Event)
            .join(Node, Node.id == Event.node_id)
            .where(
                Event.person_id == person_id,
                Node.zone_id == node.zone_id,
                Event.decision == EventDecision.granted,
                # ⭐ Sıra bağımsızlığının anahtarı: sonradan gelen ESKİ bir
                # olay, kendisinden SONRAKİ okumalarla kıyaslanmaz.
                Event.effective_ts <= effective_ts,
            )
        )
    ).scalar_one_or_none()

    if last is None:
        return False
    return (effective_ts - last) < window


async def apply(db: AsyncSession, node: Node, event: Event) -> str | None:
    """
    Olayı oturumlara yansıtır ve yönü döndürür ("GİRİŞ" / "ÇIKIŞ").
    `granted` olmayan okumalar oturum üretmez (§4.1) — None döner.

    Çağıran, event'i eklemiş ama HENÜZ COMMIT ETMEMİŞ olmalı; oturum ve
    olay aynı işlemde yazılır ki biri yazılıp diğeri yazılmadan kalmasın.
    """
    if event.decision != EventDecision.granted or event.person_id is None:
        return None

    open_session = (
        await db.execute(
            select(AttendanceSession).where(
                AttendanceSession.person_id == event.person_id,
                AttendanceSession.zone_id == node.zone_id,
                AttendanceSession.state == SessionState.open,
            )
        )
    ).scalar_one_or_none()

    if open_session is not None:
        # --- ÇIKIŞ ---
        open_session.exited_at = event.effective_ts
        open_session.exit_event_id = event.id
        delta = event.effective_ts - open_session.entered_at
        # Saat kayması ya da gecikmeli tampon boşaltması negatif süre
        # üretebilir; oturum kapansın ama süre kirlenmesin.
        secs = int(delta.total_seconds())
        open_session.duration_seconds = secs if secs >= 0 else None
        open_session.state = SessionState.closed
        return DIRECTION_OUT

    # --- GİRİŞ ---
    db.add(AttendanceSession(
        tenant_id=node.tenant_id,
        person_id=event.person_id,
        zone_id=node.zone_id,
        entry_event_id=event.id,
        entered_at=event.effective_ts,
        state=SessionState.open,
    ))
    return DIRECTION_IN


# ---------------------------------------------------------------------------
# Gece otomatik kapatma (§4.1)
# ---------------------------------------------------------------------------
async def auto_close_due(db: AsyncSession) -> int:
    """
    `zone.auto_close_at` saatini geçmiş açık oturumları kapatır.

    Kontrat: bu oturumlar `auto_closed` işaretlenir ve **süre hesabına dahil
    edilmez** — `duration_seconds` NULL bırakılır. Koç panelinde "eksik çıkış"
    olarak görünür (Faz 9). Uydurma bir süre yazmak, raporları sessizce
    yanlışlar; boş bırakmak dürüst olandır.

    Döndürdüğü: kapatılan oturum sayısı.
    """
    rows = (
        await db.execute(
            select(Zone, Tenant.timezone)
            .join(Tenant, Tenant.id == Zone.tenant_id)
            .where(Zone.auto_close_at.is_not(None))
        )
    ).all()

    closed_total = 0

    for zone, tz_name in rows:
        try:
            tz = ZoneInfo(tz_name or settings.timezone)
        except Exception:
            tz = ZoneInfo(settings.timezone)

        now_local = dt.datetime.now(tz)
        cutoff_local = now_local.replace(
            hour=zone.auto_close_at.hour,
            minute=zone.auto_close_at.minute,
            second=0,
            microsecond=0,
        )
        # Kapatma saati henüz gelmediyse dünkü kesim geçerlidir
        if cutoff_local > now_local:
            cutoff_local -= dt.timedelta(days=1)
        cutoff = cutoff_local.astimezone(dt.timezone.utc)

        open_sessions = (
            await db.execute(
                select(AttendanceSession).where(
                    and_(
                        AttendanceSession.zone_id == zone.id,
                        AttendanceSession.state == SessionState.open,
                        AttendanceSession.entered_at < cutoff,
                    )
                )
            )
        ).scalars().all()

        for s in open_sessions:
            s.state = SessionState.auto_closed
            s.exited_at = cutoff
            s.duration_seconds = None      # süre hesabına GİRMEZ
            s.note = (s.note or "") + "[otomatik kapatildi: cikis okutulmadi]"
            closed_total += 1

        if open_sessions:
            log.warning(
                "gece kapatma: mekan=%s adet=%d kesim=%s",
                zone.name, len(open_sessions), cutoff_local.isoformat(),
            )

    if closed_total:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            log.exception("gece kapatma yazilamadi")
            return 0

    return closed_total
