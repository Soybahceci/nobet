"""
NÖBET Kenar Servisi (Faz 13a-3)
================================
Mimari: docs/nobet-faz13-saas-mimarisi.md
Karar:  docs/nobet-karar-sirasiz-olaylar.md

    ESP32 --MQTT--> [kenar]  --HTTPS--> bulut
                       │
                       ├── olayı SQLite kuyruğa yaz
                       ├── ⭐ ack'i HEMEN gönder (bulut beklenmez)
                       └── arka planda buluta senkronla

⭐ **Ack kenardan verilir.** Olay diske yazılır yazılmaz ESP32'ye ack gider;
bulut beklenmez. Sonuç: okuyucunun 1000'lik tamponu normal işleyişte hiç
dolmaz ve internet kesintisi okuyucu için **görünmez** olur. Firmware'de tek
satır değişiklik gerekmedi.

**Kararı bulut verir, ışığı kenar yakar** (§10.3-2). Kenardaki kart kopyası
bayat olabilir; bulutta iptal edilmiş bir kart kesinti sırasında burada hâlâ
geçerli görünür ve ışık yeşil yanar. `event.decision` için **bulut
yetkilidir**. Fiziksel kilit olmadığı için (Faz 0) etkisi yalnızca ışığın
yanlış yanmasıdır.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import signal
from typing import Any

import aiomqtt

from app.cloud import AuthError, Cloud, CloudError
from app.queue import Queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("edge")

VERSION = "0.1.0"

MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "nobet/v1")

CLOUD_URL = os.environ.get("CLOUD_URL", "")
QUEUE_PATH = os.environ.get("QUEUE_PATH", "/data/edge.sqlite")

SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "10"))       # sn
CARD_INTERVAL = int(os.environ.get("CARD_INTERVAL", "60"))       # sn
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "60"))
BATCH = int(os.environ.get("BATCH", "200"))                      # bulut sınırı 500

_stop = asyncio.Event()


# ---------------------------------------------------------------------------
# Kart kopyası — kesintide kararı bu veriyor (yalnızca ışık için)
# ---------------------------------------------------------------------------
class CardCache:
    def __init__(self, q: Queue) -> None:
        self.q = q
        self.cards: dict[str, dict[str, Any]] = {}
        raw = q.get_meta("cards", "")
        if raw:
            try:
                self.cards = json.loads(raw)
            except ValueError:
                log.warning("kart kopyasi bozuk, sifirdan indirilecek")
        self.version = int(q.get_meta("card_version", "0") or 0)

    def replace(self, version: int, cards: list[dict[str, Any]]) -> None:
        self.cards = {c["identifier"].upper(): c for c in cards}
        self.version = version
        self.q.set_meta("cards", json.dumps(self.cards))
        self.q.set_meta("card_version", str(version))
        log.info("kart kopyasi guncellendi: surum=%s adet=%d", version, len(self.cards))

    def decide(self, identifier: str) -> str:
        """
        Yalnızca LED/buzzer için. Gerçek karar bulutta verilir.
        Kopya boşsa (henüz indirilmedi) `granted` denir: kapıda kimseyi
        gereksiz yere kırmızıyla karşılamayalım, kayıt zaten tutuluyor.
        """
        if not self.cards:
            return "granted"
        c = self.cards.get(identifier.upper())
        if c is None:
            return "unknown_credential"
        return "granted" if c.get("active") else "revoked"


_FEEDBACK = {
    "granted": "ok",
    "unknown_credential": "unknown",
    "revoked": "denied",
}


# ---------------------------------------------------------------------------
# MQTT: olayı al, diske yaz, ACK GÖNDER
# ---------------------------------------------------------------------------
async def mqtt_loop(q: Queue, cache: CardCache) -> None:
    while not _stop.is_set():
        try:
            async with aiomqtt.Client(
                hostname=MQTT_HOST, port=MQTT_PORT,
                username=MQTT_USER or None, password=MQTT_PASS or None,
                identifier="nobet-edge",
            ) as client:
                await client.subscribe(f"{TOPIC_PREFIX}/+/+/evt")
                log.info("MQTT bagli: %s:%s", MQTT_HOST, MQTT_PORT)

                async for msg in client.messages:
                    try:
                        await _on_event(q, cache, client, str(msg.topic),
                                        bytes(msg.payload))
                    except Exception:
                        log.exception("olay islenemedi")
        except aiomqtt.MqttError as exc:
            log.warning("MQTT koptu (%s) — 5 sn sonra yeniden", exc)
            await asyncio.sleep(5)


async def _on_event(q: Queue, cache: CardCache, client: aiomqtt.Client,
                    topic: str, payload: bytes) -> None:
    d = json.loads(payload.decode())
    node_key = str(d["node"])
    seq = int(d["seq"])
    identifier = str(d["cred"]["id"]).upper()

    # ⭐ Zaman damgasını KENAR koyar (§10.3-1). Kesinti sonrası senkron olan
    # olaylar bulutun varış saatiyle damgalansaydı hepsi aynı ana yığılır ve
    # o günün devam kaydı çöp olurdu.
    now = dt.datetime.now(dt.timezone.utc)

    ok = q.put({
        "node_key": node_key, "seq": seq,
        "cred_type": d["cred"].get("t", "rfid"), "cred_id": identifier,
        "up": d.get("up", 0), "up_tx": d.get("up_tx"), "buf": d.get("buf"),
        "ts": now.isoformat(),
        "clock_unsynced": _clock_unsynced(),
    })

    if not ok:
        # Diske yazılamadıysa ACK GÖNDERİLMEZ. Düğüm tekrar dener, olay
        # onun tamponunda güvende kalır. Ack gönderip kaybetmek en kötüsü.
        log.error("kuyruga yazilamadi, ack GONDERILMIYOR: %s/%s", node_key, seq)
        return

    decision = cache.decide(identifier)
    ack = {
        "v": 1, "ack": seq, "result": decision,
        "display": "OK" if decision == "granted" else "KAYITSIZ",
        "feedback": _FEEDBACK.get(decision, "ok"),
        "relay_ms": 0,                      # Faz 0: fiziksel kilit yok
    }
    cmd_topic = topic.rsplit("/", 1)[0] + "/cmd"
    await client.publish(cmd_topic, json.dumps(ack).encode())


def _clock_unsynced() -> bool:
    """
    Saat güvenilir mi? Pi'de RTC yok; elektrik kesilip internetsiz açılırsa
    saat 1970'e düşer. Böyle olayları işaretliyoruz ki bulut ayırt edebilsin.
    """
    return dt.datetime.now(dt.timezone.utc).year < 2020


# ---------------------------------------------------------------------------
# Senkron: kuyruğu boşalt (KESİNLİKLE SIRALI)
# ---------------------------------------------------------------------------
async def sync_loop(q: Queue, cloud: Cloud) -> None:
    while not _stop.is_set():
        try:
            await _drain(q, cloud)
        except AuthError as exc:
            # Yeniden denemek düzeltmez; insan müdahalesi gerek.
            log.error("KIMLIK HATASI: %s — eslestirme yenilenmeli", exc)
            await asyncio.sleep(60)
        except CloudError as exc:
            log.info("senkron ertelendi: %s", exc)
        except Exception:
            log.exception("senkron dongusu hatasi")
        await asyncio.sleep(SYNC_INTERVAL)


async def _drain(q: Queue, cloud: Cloud) -> None:
    """
    ⭐ Kuyruk **en eskiden** boşalır ve aynı anda TEK toplu istek uçar.

    Sıra garantisi bulut tarafındaki oturum kurgusu için şart: olaylar
    kuyruğa oluş sırasıyla girdiği için, FIFO boşaltma bulutun onları
    kronolojik görmesini sağlıyor (karar dokümanı).
    """
    while not _stop.is_set():
        rows = q.peek(BATCH)
        if not rows:
            return

        payload = [{
            "node_key": r["node_key"], "seq": r["seq"],
            "cred_type": r["cred_type"], "cred_id": r["cred_id"],
            "up": r["up"], "up_tx": r["up_tx"], "buf": r["buf"],
            "ts": r["ts"], "clock_unsynced": bool(r["clock_unsynced"]),
        } for r in rows]

        res = await cloud.push_events(payload)

        by_seq = {(r["node_key"], r["seq"]): r for r in rows}
        done: list[tuple[str, int]] = []

        # Kabul edilen ve zaten var olanlar kuyruktan çıkar.
        for s in res.get("accepted", []) + res.get("duplicate", []):
            for (nk, sq) in by_seq:
                if sq == s:
                    done.append((nk, sq))
        q.drop(done)

        # §3.1b: kalıcı ret ölü mektuba. ASLA kuyrukta bırakılmaz.
        for rej in res.get("rejected", []):
            row = by_seq.get((rej.get("node_key", ""), rej.get("seq", -1)))
            if row is not None:
                q.to_dead_letter(row, rej.get("reason", "bilinmiyor"))

        sent = len(res.get("accepted", [])) + len(res.get("duplicate", []))
        if sent or res.get("rejected"):
            log.info("senkron: %d gonderildi, %d ret, kuyruk=%d",
                     sent, len(res.get("rejected", [])), q.depth())

        # Hiçbiri işlenmediyse sonsuz döngüye girmeyelim.
        if not done and not res.get("rejected"):
            log.warning("toplu istek hicbir sonuc uretmedi, bekleniyor")
            return
        if len(rows) < BATCH:
            return


# ---------------------------------------------------------------------------
# Kart kopyası ve heartbeat
# ---------------------------------------------------------------------------
async def card_loop(q: Queue, cloud: Cloud, cache: CardCache) -> None:
    while not _stop.is_set():
        try:
            res = await cloud.fetch_cards(cache.version)
            if res.get("changed"):
                cache.replace(int(res["version"]), res.get("cards", []))
        except AuthError as exc:
            log.error("kart kopyasi alinamadi (kimlik): %s", exc)
            await asyncio.sleep(60)
        except CloudError as exc:
            log.info("kart kopyasi ertelendi: %s", exc)
        except Exception:
            log.exception("kart kopyasi dongusu hatasi")
        await asyncio.sleep(CARD_INTERVAL)


async def heartbeat_loop(q: Queue, cloud: Cloud, cache: CardCache) -> None:
    while not _stop.is_set():
        try:
            res = await cloud.heartbeat(
                q.depth(), q.dead_count(), cache.version, VERSION
            )
            if res.get("clock_warning"):
                log.warning(
                    "SAAT SAPMASI: %s ms — NTP kontrol edilmeli",
                    res.get("clock_skew_ms"),
                )
        except (CloudError, AuthError) as exc:
            log.info("heartbeat ertelendi: %s", exc)
        except Exception:
            log.exception("heartbeat dongusu hatasi")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
async def main_async() -> int:
    if not CLOUD_URL:
        log.error("CLOUD_URL tanimli degil")
        return 2

    q = Queue(QUEUE_PATH)
    token = q.get_meta("token")
    if not token:
        log.error(
            "Kenar eslesmemis. Once: python -m app.pair <ESLESTIRME-KODU>"
        )
        return 3

    cache = CardCache(q)
    cloud = Cloud(CLOUD_URL, token)
    log.info("kenar servisi basliyor — kuyruk=%d olu=%d kart surumu=%d",
             q.depth(), q.dead_count(), cache.version)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop.set)
        except NotImplementedError:      # Windows
            pass

    await asyncio.gather(
        mqtt_loop(q, cache),
        sync_loop(q, cloud),
        card_loop(q, cloud, cache),
        heartbeat_loop(q, cloud, cache),
    )
    q.close()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
