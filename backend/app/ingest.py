"""
NÖBET — MQTT Alım Hattı (kontrat §4)
=====================================
Ayrı bir konteyner olarak çalışır. API çökse bile olay alımı durmaz.

    MQTT mesajı
       ↓ şema doğrulama (v==1, zorunlu alanlar)
       ↓ node_key → node çözümle   (bilinmeyen düğüm → reddet + logla)
       ↓ dedup: (node_id, seq) var mı? → varsa ack tekrarla, çık
       ↓ credential çözümle → person_id, decision
       ↓ effective_ts hesapla (§2.3)
       ↓ event INSERT  (değişmez)
       ↓ cmd publish   (ack + geri bildirim)

Oturum motoru (§4.1) BU FAZDA YOK — yol haritasında Faz 7.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
import json
import logging
from typing import Any

import aiomqtt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify, sessions, worklock
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Credential,
    CredentialStatus,
    CredentialType,
    Event,
    EventDecision,
    Node,
    NodeStatus,
    Zone,
)

log = logging.getLogger("nobet.ingest")

# Firmware cred.t değerleri → veritabanı enum'u.
# Kontrat §2.2: "rfid" | "fp"
_CRED_TYPE = {
    "rfid": CredentialType.rfid,
    "fp": CredentialType.fingerprint,
    "fingerprint": CredentialType.fingerprint,
}

# Kontrat §2.6 — sunucunun düğüme döndüğü geri bildirim
_FEEDBACK = {
    EventDecision.granted: "ok",
    EventDecision.unknown_credential: "warn",
    EventDecision.revoked: "deny",
    EventDecision.duplicate: "dup",
    EventDecision.disabled_node: "deny",
}


class SchemaError(Exception):
    """Payload kontrata uymuyor."""


# ---------------------------------------------------------------------------
# Şema doğrulama
# ---------------------------------------------------------------------------
def parse_event(payload: bytes) -> dict[str, Any]:
    try:
        d = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaError(f"JSON çözülemedi: {exc}") from exc

    if not isinstance(d, dict):
        raise SchemaError("payload bir nesne değil")
    if d.get("v") != 1:
        raise SchemaError(f"desteklenmeyen şema sürümü: {d.get('v')!r}")

    for field in ("node", "seq", "cred", "up"):
        if field not in d:
            raise SchemaError(f"zorunlu alan eksik: {field}")

    cred = d["cred"]
    if not isinstance(cred, dict) or "t" not in cred or "id" not in cred:
        raise SchemaError("cred.t / cred.id eksik")
    if cred["t"] not in _CRED_TYPE:
        raise SchemaError(f"bilinmeyen cred.t: {cred['t']!r}")
    if not isinstance(d["seq"], int) or d["seq"] < 0:
        raise SchemaError(f"gecersiz seq: {d['seq']!r}")
    if not isinstance(d["up"], int) or d["up"] < 0:
        raise SchemaError(f"gecersiz up: {d['up']!r}")

    return d


# ---------------------------------------------------------------------------
# effective_ts — kontrat §2.3
# ---------------------------------------------------------------------------
def compute_effective_ts(d: dict[str, Any], server_ts: dt.datetime) -> dt.datetime:
    """
    ts != null           -> effective_ts = ts          (RTC güvenilir)
    ts == null, buf == 0 -> effective_ts = server_ts   (canlı, gecikme ~ms)
    ts == null, buf == 1 -> effective_ts = server_ts - (up_tx - up)
    """
    raw_ts = d.get("ts")
    if raw_ts:
        try:
            parsed = dt.datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            log.warning("ts cozulemedi, server_ts'e dusuluyor: %r", raw_ts)

    if not d.get("buf"):
        return server_ts

    # Buffer'dan geldi: olayın yaşını düğümün kendi saatinden hesapla.
    # up_tx kontrat v1.1'de eklendi; yoksa telafi yapılamaz.
    up = int(d["up"])
    up_tx = d.get("up_tx")
    if up_tx is None:
        log.warning("buf=1 ama up_tx yok (eski firmware?) — telafi yapilamiyor")
        return server_ts

    age_ms = max(0, int(up_tx) - up)
    return server_ts - dt.timedelta(milliseconds=age_ms)


# ---------------------------------------------------------------------------
# Karar — kontrat §4
# ---------------------------------------------------------------------------
async def resolve_decision(
    db: AsyncSession, node: Node, cred_type: CredentialType, identifier: str
) -> tuple[EventDecision, Credential | None]:
    if node.status == NodeStatus.disabled:
        return EventDecision.disabled_node, None

    cred = (
        await db.execute(
            select(Credential).where(
                Credential.tenant_id == node.tenant_id,
                Credential.type == cred_type,
                Credential.identifier == identifier,
            )
        )
    ).scalar_one_or_none()

    if cred is None:
        # Hata değil — enrollment akışının yakıtı (§3.4)
        return EventDecision.unknown_credential, None
    if cred.status != CredentialStatus.active:
        return EventDecision.revoked, cred
    return EventDecision.granted, cred


def build_display(
    decision: EventDecision, cred: Credential | None, direction: str | None = None
) -> str:
    """Düğümün ekranında görünecek metin (kontrat §2.6: "Ayşe Y. · GİRİŞ")."""
    if decision == EventDecision.granted and cred is not None:
        return f"{cred.person.full_name} · {direction or 'OKUNDU'}"
    if decision == EventDecision.duplicate and cred is not None:
        return f"{cred.person.full_name} · zaten okutuldu"
    if decision == EventDecision.unknown_credential:
        return "Kayıtsız kart"
    if decision == EventDecision.revoked:
        return "Kart iptal edilmiş"
    if decision == EventDecision.disabled_node:
        return "Okuyucu devre dışı"
    return "-"


# ---------------------------------------------------------------------------
# Tek mesajın işlenmesi
# ---------------------------------------------------------------------------
async def handle_event(
    db: AsyncSession,
    d: dict[str, Any],
    *,
    tenant_id: uuid.UUID | None = None,
    effective_ts_override: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """
    İşlenen olayın `cmd` yanıtını döndürür. Düğüm bilinmiyorsa None.

    `tenant_id` verilirse düğüm YALNIZCA o kurumda aranır (Faz 13a-2/13a-4).
    Kenar cihazından gelen olaylarda kurum **jetondan** belirlenir; bu
    parametre olmadan bir kurumun kenarı, başka kurumun `node_key`'ini
    göndererek onun kaydına olay yazabilirdi.

    `effective_ts_override` kenar için: kesinti sonrası senkron olan olaylar
    bulutun varış saatiyle damgalanırsa hepsi aynı ana yığılır ve o günün
    devam kaydı çöp olur (mimari §10.3-1). Kenar zamanı kendisi hesaplar.
    """
    node_key = str(d["node"])
    seq = int(d["seq"])

    conds = [Node.node_key == node_key]
    if tenant_id is not None:
        conds.append(Node.tenant_id == tenant_id)
    node = (await db.execute(select(Node).where(*conds))).scalar_one_or_none()

    if node is None:
        # Bilinmeyen düğüm: reddet + logla (§4). Ack GÖNDERİLMEZ; düğüm
        # tekrar deneyecektir. Operatör düğümü tanımlayınca olay kurtarılır.
        log.warning("bilinmeyen dugum, olay reddedildi: node_key=%s seq=%s", node_key, seq)
        return None

    # --- dedup: aynı (node, seq) daha önce işlendi mi? (§1.2, §4) ---
    existing = (
        await db.execute(
            select(Event).where(Event.node_id == node.id, Event.seq == seq)
        )
    ).scalar_one_or_none()

    if existing is not None:
        log.info("tekrar eden olay, ack yineleniyor: node=%s seq=%s", node_key, seq)
        return {
            "v": 1,
            "ack": seq,
            "result": existing.decision.value,
            "display": "TEKRAR",
            "feedback": _FEEDBACK.get(existing.decision, "ok"),
            "relay_ms": 0,
        }

    cred_type = _CRED_TYPE[d["cred"]["t"]]
    identifier = str(d["cred"]["id"]).upper()   # kontrat: büyük harf, ayraçsız

    decision, cred = await resolve_decision(db, node, cred_type, identifier)

    server_ts = dt.datetime.now(dt.timezone.utc)
    effective_ts = effective_ts_override or compute_effective_ts(d, server_ts)

    # Çift okutma koruması (§4.1) — INSERT'ten ÖNCE, çünkü `event` değişmez
    # ve yazıldıktan sonra kararı değiştirmek mümkün değil.
    if decision == EventDecision.granted and cred is not None:
        if await sessions.is_duplicate_read(db, node, cred.person_id, effective_ts):
            decision = EventDecision.duplicate
            log.info("cift okutma yok sayildi: node=%s uid=%s", node_key, identifier)

    event = Event(
        tenant_id=node.tenant_id,
        node_id=node.id,
        seq=seq,
        cred_type=cred_type,
        cred_identifier=identifier,
        credential_id=cred.id if cred else None,
        person_id=cred.person_id if cred else None,
        decision=decision,
        device_uptime_ms=int(d["up"]),
        device_tx_uptime_ms=d.get("up_tx"),
        device_ts=None,
        server_ts=server_ts,
        effective_ts=effective_ts,
        from_buffer=bool(d.get("buf")),
        raw=d,
    )
    db.add(event)

    # Düğüm sağlığı (§3.5) — olaydan da güncellenir, heartbeat beklenmez
    node.last_seen_at = server_ts
    node.status = NodeStatus.online

    # Oturum motoru (§4.1). event.id gerekiyor, önce flush.
    # Olay ve oturum AYNI işlemde yazılır: biri yazılıp diğeri yazılmadan
    # kalırsa "içeride kim var" listesi ham veriyle çelişir.
    direction: str | None = None
    try:
        await db.flush()
        direction = await sessions.apply(db, node, event)

        # Veli bildirimi (§Faz 8) — aynı işlemde kuyruğa alınır.
        # Olay yazılmazsa bildirim de yazılmaz; veli olmayan bir giriş için
        # mesaj gitmesi mümkün değil.
        if direction is not None:
            zone = (
                await db.execute(select(Zone).where(Zone.id == node.zone_id))
            ).scalar_one_or_none()
            if zone is not None:
                queued = await notify.enqueue_for_event(db, event, zone, direction)
                if queued:
                    log.info("bildirim kuyruga alindi: %d veli", queued)
    except IntegrityError:
        # Aynı kişi/mekân için eşzamanlı açık oturum — kısmi tekil indeks
        # engelledi. Olay yine de yazılmalı; oturumu bir sonraki okuma toparlar.
        await db.rollback()
        log.warning("oturum yazilamadi (eszamanli acik oturum): node=%s seq=%s",
                    node_key, seq)
        db.add(event)
        node.last_seen_at = server_ts
        node.status = NodeStatus.online

    try:
        await db.commit()
    except IntegrityError:
        # Yarış durumu: aynı olay paralel işlendi. UNIQUE(node_id, seq)
        # çift kaydı engelledi — kontrat bunu tam da bunun için koyuyor.
        await db.rollback()
        log.info("yaris durumu, olay zaten yazilmis: node=%s seq=%s", node_key, seq)
        return {
            "v": 1, "ack": seq, "result": decision.value,
            "display": "TEKRAR", "feedback": _FEEDBACK.get(decision, "ok"), "relay_ms": 0,
        }

    log.info(
        "olay yazildi: node=%s seq=%s uid=%s karar=%s yon=%s buf=%s eff=%s",
        node_key, seq, identifier, decision.value, direction or "-",
        bool(d.get("buf")), effective_ts.isoformat(),
    )

    return {
        "v": 1,
        "ack": seq,
        "result": decision.value,
        "display": build_display(decision, cred, direction),
        "feedback": _FEEDBACK.get(decision, "ok"),
        # Kontrat §2.6: prototipte DAİMA 0. Fiziksel kilit yok (Faz 0 kararı).
        "relay_ms": 0,
    }


async def handle_heartbeat(db: AsyncSession, d: dict[str, Any]) -> None:
    """§2.4 — düğüm sağlığını güncelle."""
    node = (
        await db.execute(select(Node).where(Node.node_key == str(d.get("node", ""))))
    ).scalar_one_or_none()
    if node is None:
        return
    node.last_seen_at = dt.datetime.now(dt.timezone.utc)
    node.status = NodeStatus.online
    if d.get("fw"):
        node.firmware_version = str(d["fw"])

    # Kontrat v1.2 — okuyucu sağlığı. Eski firmware bu alanları göndermez;
    # o durumda değere dokunulmaz (NULL = "bilinmiyor" anlamını korur).
    rdr = d.get("rdr")
    if rdr is not None:
        was_ok = node.reader_ok
        node.reader_ok = str(rdr).lower() == "ok"
        if was_ok is not False and node.reader_ok is False:
            log.error("OKUYUCU ARIZASI: node=%s rdr=%s", node.node_key, rdr)
    if d.get("rdr_reinit") is not None:
        try:
            node.reader_reinits = int(d["rdr_reinit"])
        except (TypeError, ValueError):
            pass

    await db.commit()


async def handle_status(db: AsyncSession, d: dict[str, Any]) -> None:
    """§2.5 — LWT. Cihaz sağlığı panelinin kaynağı."""
    node = (
        await db.execute(select(Node).where(Node.node_key == str(d.get("node", ""))))
    ).scalar_one_or_none()
    if node is None:
        return
    state = str(d.get("state", "")).lower()
    if state == "online":
        node.status = NodeStatus.online
        node.last_seen_at = dt.datetime.now(dt.timezone.utc)
    elif state == "offline":
        # disabled bir düğümü LWT ile online/offline'a çevirme
        if node.status != NodeStatus.disabled:
            node.status = NodeStatus.offline
    await db.commit()


# ---------------------------------------------------------------------------
# Ana döngü
# ---------------------------------------------------------------------------
def _cmd_topic(event_topic: str) -> str:
    return event_topic.rsplit("/", 1)[0] + "/cmd"


async def _dispatch(client: aiomqtt.Client, topic: str, payload: bytes) -> None:
    async with SessionLocal() as db:
        if topic.endswith("/event"):
            try:
                d = parse_event(payload)
            except SchemaError as exc:
                # Bozuk mesaj ack'lenmez; kuyruğu tıkamaması için sadece loglanır.
                log.warning("sema hatasi, mesaj atlandi: %s | %r", exc, payload[:200])
                return
            cmd = await handle_event(db, d)
            if cmd is not None:
                await client.publish(_cmd_topic(topic), json.dumps(cmd), qos=1)

        elif topic.endswith("/hb"):
            try:
                await handle_heartbeat(db, json.loads(payload))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("hb cozulemedi")

        elif topic.endswith("/status"):
            try:
                await handle_status(db, json.loads(payload))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("status cozulemedi")


async def auto_close_loop() -> None:
    """
    Gece kapatma (§4.1) — dakikada bir yoklar.

    Alım hattıyla aynı süreçte: ayrı bir zamanlayıcı konteyneri kurmak
    prototip için gereksiz karmaşıklık.

    İkinci bir kopya kalkarsa danışma kilidi onu devre dışı bırakır
    (bkz. `app/worklock.py`). Alım hattının kendisi kilitlenmez — MQTT
    tarafı `UNIQUE(node_id, seq)` ile zaten idempotent.
    """
    async with worklock.WorkLock(worklock.LOCK_AUTO_CLOSE, "gece kapatma") as got:
        if not got:
            return
        while True:
            try:
                async with SessionLocal() as db:
                    closed = await sessions.auto_close_due(db)
                    if closed:
                        log.info("gece kapatma: %d oturum kapatildi", closed)
            except Exception:
                log.exception("gece kapatma hatasi")
            await asyncio.sleep(60)


async def run() -> None:
    prefix = settings.mqtt_topic_prefix
    topics = [f"{prefix}/+/+/event", f"{prefix}/+/+/hb", f"{prefix}/+/+/status"]

    backoff = 1
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_user or None,
                password=settings.mqtt_pass or None,
                identifier=settings.mqtt_client_id,
                # ⚠️ Faz 3'te bulundu: abone yokken yayınlanan mesajları broker
                # düşürüyor. Kalıcı oturum, ingest yeniden başlarken gelen
                # olayların kaybolmamasını sağlar.
                clean_session=False,
            ) as client:
                log.info("brokere baglandi: %s:%s", settings.mqtt_host, settings.mqtt_port)
                backoff = 1
                for t in topics:
                    await client.subscribe(t, qos=1)
                log.info("abone olundu: %s", topics)

                async for message in client.messages:
                    try:
                        await _dispatch(client, str(message.topic), bytes(message.payload))
                    except Exception:
                        # Tek bir bozuk mesaj tüm alım hattını düşürmesin.
                        log.exception("mesaj islenirken hata: %s", message.topic)

        except aiomqtt.MqttError as exc:
            log.error("broker baglantisi koptu (%s) — %ss sonra tekrar", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def main_async() -> None:
    # Gece kapatma, broker bağlantısından bağımsız çalışmalı: ağ koparsa da
    # açık oturumlar kapatılmaya devam etsin.
    # Gece kapatma ve bildirim işçisi broker bağlantısından bağımsız çalışır:
    # ağ koparsa da oturumlar kapanmaya, kuyruk boşalmaya devam etsin.
    closer = asyncio.create_task(auto_close_loop())
    notifier = asyncio.create_task(notify.worker_loop())
    try:
        await run()
    finally:
        closer.cancel()
        notifier.cancel()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
