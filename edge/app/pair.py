"""
NÖBET Kenar — eşleştirme (mimari §10.3-4)
==========================================
Kurulumda **bir kez** çalışır:

    python -m app.pair ABCD-EFGH-JKLM

Tek kullanımlık kodu kalıcı jetonla takas eder ve jetonu kenarın kendi
SQLite dosyasına yazar. Kod tüketilir; ikinci kez kullanılamaz.

Jeton bulutta **hash'lenerek** saklanıyor — bulut veritabanı sızsa bile
kenar taklit edilemez. Kenarda ise düz metin durmak zorunda (istek imzalamak
için gerekiyor); bu yüzden kutunun fiziksel güvenliği önemlidir ve mimari
§2.3b'de adanmış kutunun ortak PC'ye tercih edilme sebeplerinden biri budur.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from app.cloud import Cloud, CloudError
from app.queue import Queue

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s | %(message)s")
log = logging.getLogger("edge.pair")


async def run(code: str) -> int:
    cloud_url = os.environ.get("CLOUD_URL", "")
    if not cloud_url:
        log.error("CLOUD_URL tanimli degil")
        return 2

    q = Queue(os.environ.get("QUEUE_PATH", "/data/edge.sqlite"))
    if q.get_meta("token"):
        log.error(
            "Bu kenar ZATEN eslesmiş (kurum=%s). Yeniden eslestirmek icin "
            "once kuyruk dosyasindaki jetonu silin — kuyrukta bekleyen "
            "olaylar varsa ONCE senkron olmalarini bekleyin.",
            q.get_meta("tenant_slug", "?"),
        )
        return 4

    try:
        res = await Cloud(cloud_url).pair(code.strip().upper())
    except CloudError as exc:
        log.error("eslestirme basarisiz: %s", exc)
        return 1

    q.set_meta("token", res["token"])
    q.set_meta("tenant_id", str(res["tenant_id"]))
    q.set_meta("tenant_slug", res["tenant_slug"])
    q.set_meta("device_id", str(res["device_id"]))
    q.close()

    log.info("Eslestirme tamam: kurum=%s cihaz=%s",
             res["tenant_slug"], res["device_name"])
    log.info("Jeton kenara yazildi. Servis artik baslatilabilir.")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("kullanim: python -m app.pair <ESLESTIRME-KODU>", file=sys.stderr)
        return 2
    return asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
