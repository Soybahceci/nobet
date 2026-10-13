"""
NÖBET Kenar — dayanıklı olay kuyruğu (SQLite)
==============================================
Mimari: §2.2, §2.3, §3.1b · Karar: docs/nobet-karar-sirasiz-olaylar.md

Bu dosya kenar cihazının **tek kritik bileşeni**: buraya yazılan bir olay
kaybolmamalı. ESP32'ye ack, olay diske YAZILDIKTAN sonra gönderiliyor;
dolayısıyla okuyucunun tamponu boşaldığı an sorumluluk bu dosyaya geçiyor.

Neden SQLite: Pi 3B'de PostgreSQL ~200 MB tabanı karşılıksız yer, eşzamanlılık
ve karmaşık sorgu kenarda kullanılmıyor. Burada tutulan şey bir veritabanı
değil, **dayanıklı bir kuyruk**.

⭐ **FIFO ve yalnızca FIFO.** `id` sırasına göre okunur, atlanmaz.
Olaylar kuyruğa oluş sırasıyla girdiği için çıkışta da kronolojik olurlar;
bulut tarafındaki oturum kurgusunun buna ihtiyacı var (karar dokümanı).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger("edge.queue")

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    node_key      TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    cred_type     TEXT    NOT NULL,
    cred_id       TEXT    NOT NULL,
    up            INTEGER NOT NULL DEFAULT 0,
    up_tx         INTEGER,
    buf           INTEGER,
    -- Kenarın KENDİ hesapladığı zaman (§10.3-1). Bulut buna güvenir.
    ts            TEXT    NOT NULL,
    clock_unsynced INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    UNIQUE (node_key, seq)
);

-- §3.1b: bulutun KALICI olarak reddettiği olaylar. Kuyrukta bırakılsalardı
-- arkalarındaki her şey tıkanırdı. Silinmiyorlar: veri kaybı olabilecek
-- tek yer burası, görünmez olmamalı.
CREATE TABLE IF NOT EXISTS dead_letter (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_key   TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    reason     TEXT NOT NULL,
    failed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


class Queue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # WAL: yazma sırasında okuma bloklanmaz ve ani elektrik kesintisinde
        # dosya tutarlı kalır. Kenarda elektrik kesintisi olağan bir durum.
        self.db.execute("PRAGMA journal_mode=WAL")
        # FULL: her commit diske ulaşsın. NORMAL daha hızlı ama elektrik
        # kesilirse son yazmalar kaybolabilir — ack verdiğimiz olaylar için
        # kabul edilemez.
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    # --- yazma -------------------------------------------------------------
    def put(self, ev: dict[str, Any]) -> bool:
        """
        Olayı kuyruğa yazar. **True dönerse olay diskte** ve ESP32'ye ack
        gönderilebilir.

        Aynı `(node_key, seq)` ikinci kez gelirse (düğüm ack'i alamayıp
        yeniden gönderdiyse) sessizce yok sayılır — ama yine True döner,
        çünkü olay zaten güvende ve düğümün ack'e ihtiyacı var.
        """
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            self.db.execute(
                "INSERT INTO outbox (node_key,seq,cred_type,cred_id,up,up_tx,buf,"
                "ts,clock_unsynced,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ev["node_key"], int(ev["seq"]), ev.get("cred_type", "rfid"),
                    ev["cred_id"], int(ev.get("up", 0)), ev.get("up_tx"),
                    ev.get("buf"), ev["ts"], 1 if ev.get("clock_unsynced") else 0,
                    now,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            log.info("kuyrukta zaten var: %s/%s", ev["node_key"], ev["seq"])
            return True
        except sqlite3.Error:
            log.exception("KUYRUGA YAZILAMADI — ack gonderilmemeli")
            return False

    # --- okuma -------------------------------------------------------------
    def peek(self, limit: int) -> list[sqlite3.Row]:
        """En eski `limit` kayıt. ⚠️ Sıra ASLA değiştirilmez."""
        return list(self.db.execute(
            "SELECT * FROM outbox ORDER BY id LIMIT ?", (limit,)
        ))

    def depth(self) -> int:
        return int(self.db.execute("SELECT count(*) FROM outbox").fetchone()[0])

    def dead_count(self) -> int:
        return int(self.db.execute("SELECT count(*) FROM dead_letter").fetchone()[0])

    # --- silme -------------------------------------------------------------
    def drop(self, keys: list[tuple[str, int]]) -> None:
        """Bulut kabul etti (ya da zaten vardı) — kuyruktan çıkar."""
        if not keys:
            return
        self.db.executemany(
            "DELETE FROM outbox WHERE node_key=? AND seq=?", keys
        )

    def to_dead_letter(self, row: sqlite3.Row, reason: str) -> None:
        """
        Kalıcı ret: kuyruktan çıkar ama **sakla**.

        Silmek, sessiz veri kaybı olurdu. Kuyrukta bırakmak, arkasındaki her
        şeyi tıkardı. Üçüncü yol bu.
        """
        self.db.execute(
            "INSERT INTO dead_letter (node_key,seq,payload,reason,failed_at) "
            "VALUES (?,?,?,?,?)",
            (row["node_key"], row["seq"], json.dumps(dict(row)), reason,
             dt.datetime.now(dt.timezone.utc).isoformat()),
        )
        self.db.execute(
            "DELETE FROM outbox WHERE node_key=? AND seq=?",
            (row["node_key"], row["seq"]),
        )
        log.warning("OLU MEKTUP: %s/%s — %s", row["node_key"], row["seq"], reason)

    # --- ayarlar -----------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (k,v) VALUES (?,?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )

    def close(self) -> None:
        self.db.close()
