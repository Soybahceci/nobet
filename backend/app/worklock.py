"""
NÖBET — Tekil işçi kilidi
=========================
Gece kapatma ve bildirim işçisi **tek bir kopya** varsayıyor. İkinci bir
`ingest` konteyneri kalkarsa (ölçekleme, yanlışlıkla `docker compose up
--scale`, ya da eski konteyner tam ölmeden yenisi başlarsa) ikisi de aynı
kuyruğu işler:

- aynı bildirim iki kez gönderilir → veli çift mesaj alır
- aynı oturumu iki kopya kapatmaya çalışır

`notification` tablosundaki `UNIQUE(event_id, guardian_id)` bildirimin
**üretilmesini** tekilleştiriyor ama **gönderilmesini** değil: iki işçi de
aynı `pending` satırı okuyup gönderebilir.

**Çözüm: PostgreSQL danışma kilidi (advisory lock).**
Neden bu, tabloya "ben çalışıyorum" satırı yazmak yerine:
  - Kilit **bağlantıya bağlıdır**. Konteyner çökerse bağlantı düşer ve kilit
    ANINDA serbest kalır. Satır tabanlı kilitte, çöken kopyanın bıraktığı
    satırı temizlemek için zaman aşımı ve "acaba gerçekten öldü mü"
    tahmini gerekir — dağıtık sistemlerin klasik tuzağı.
  - Ek tablo, ek migration, temizlik işi yok.

⚠️ Kilidi tutan bağlantı **açık kalmalı**. Havuzdan alınıp iade edilen bir
bağlantı kilidi de bırakır; bu yüzden burada ayrı, adanmış bir bağlantı
açılıyor ve süreç boyunca tutuluyor.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import engine

log = logging.getLogger("nobet.worklock")

# Danışma kilidi anahtarları. Sabit ve benzersiz olmaları yeter; başka bir
# uygulama aynı veritabanında aynı sayıyı kullanmadıkça çakışma olmaz.
LOCK_AUTO_CLOSE = 8_150_001
LOCK_NOTIFY = 8_150_002


class WorkLock:
    """
    Adanmış bir bağlantı üzerinde tutulan danışma kilidi.

    Kullanım:
        async with WorkLock(LOCK_NOTIFY, "bildirim isçisi") as got:
            if not got:
                return          # başka kopya çalışıyor
            ...
    """

    def __init__(self, key: int, label: str) -> None:
        self._key = key
        self._label = label
        self._conn = None

    async def __aenter__(self) -> bool:
        self._conn = await engine.connect()
        got = (
            await self._conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": self._key}
            )
        ).scalar_one()
        if not got:
            log.warning(
                "%s: baska bir kopya calisiyor, bu kopya devre disi", self._label
            )
            await self._conn.close()
            self._conn = None
        return bool(got)

    async def __aexit__(self, *exc) -> None:
        if self._conn is not None:
            # Bağlantı kapanınca kilit zaten düşer; yine de açıkça bırakıyoruz
            # ki kapanış gecikirse başka kopya beklemesin.
            try:
                await self._conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": self._key}
                )
            except Exception:
                pass
            await self._conn.close()
            self._conn = None
