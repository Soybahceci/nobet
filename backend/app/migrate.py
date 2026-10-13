"""
NÖBET — Açılışta şema yükseltme (denetim bulgusu O-2)
=====================================================

Neden var: migration'ları çalıştıran hiçbir şey yoktu. `compose.yml`'de ve
`Dockerfile`'da `alembic` geçmiyordu; `CMD` doğrudan `uvicorn` idi. Yani her
kurulumda `alembic upgrade head` ELLE çalıştırılmak zorundaydı.

Tek kurumda bir kez yapılıp unutulur. SaaS'ta her yeni kurumda tekrarlanır ve
projenin "Sıfır CLI" kuralına da aykırıdır. Üstelik `/health` yalnızca
`SELECT 1` yaptığı için yarım migrate edilmiş bir veritabanında konteyner
`healthy` raporluyor, hata ancak o tabloya ilk dokunulduğunda çıkıyordu.

İki özel durum ele alınıyor:

1. **Temiz kurulum.** Postgres imajı `docker-entrypoint-initdb.d` üzerinden
   `01-schema.sql`'i çalıştırır ve Faz 1 tablolarını yaratır, ama
   `alembic_version` tablosu oluşmaz. Bu durumda önce `stamp 0001`
   (baseline zaten kurulu), sonra `upgrade head`.

2. **Eşzamanlı açılış.** `api` ve `ingest` aynı imajı paylaşıyor ve birlikte
   kalkıyor. İkisi de migration çalıştırmaya kalkarsa aynı DDL'i aynı anda
   uygularlar. Danışma kilidiyle (advisory lock) sıraya sokuluyorlar;
   ikincisi kilidi aldığında yapacak iş kalmamış olur.

⚠️ Alembic komutları **alt süreçte** çalıştırılıyor. `alembic/env.py` içinde
`asyncio.run()` var; bunu zaten çalışan bir olay döngüsünden çağırmak
`RuntimeError` verir. Alt süreç bu çakışmayı tamamen ortadan kaldırır.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text

from app.db import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("nobet.migrate")

# worklock.py'deki kilitlerle aynı alan; çakışmasın diye sıradaki numara.
LOCK_MIGRATE = 8_150_003

BASE_DIR = Path(__file__).resolve().parent.parent   # /app
ALEMBIC_INI = BASE_DIR / "alembic.ini"


async def _alembic(*args: str) -> None:
    """Alembic'i alt süreçte çalıştırır; hata olursa istisna fırlatır."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args,
        cwd=str(BASE_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    for line in (out or b"").decode(errors="replace").splitlines():
        if line.strip():
            log.info("alembic | %s", line.rstrip())
    if proc.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} basarisiz (kod {proc.returncode})")


async def _table_exists(conn, name: str) -> bool:
    return bool(await conn.scalar(text(f"SELECT to_regclass('public.{name}') IS NOT NULL")))


async def run() -> int:
    async with engine.connect() as lock_conn:
        # Bloklayan kilit: ikinci süreç bekler, sırası gelince yapacak iş
        # kalmadığını görür. `pg_advisory_lock` oturum ömrü boyunca tutulur.
        await lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_MIGRATE})
        try:
            has_alembic = await _table_exists(lock_conn, "alembic_version")
            has_baseline = await _table_exists(lock_conn, "app_user")

            if not has_alembic and not has_baseline:
                # Ne baseline ne de migration geçmişi var. `0001` bilinçli
                # olarak boş bir damga (baseline'ı init SQL kuruyor), dolayısıyla
                # buradan `upgrade head` demek tabloları YARATMAZ — sessizce
                # yarım bir şema bırakırdı. Yüksek sesle duralım.
                log.error(
                    "Veritabani bos ve baseline kurulmamis. "
                    "infra/postgres/init/01-schema.sql calismamis demektir "
                    "(genelde veri dizini onceden dolu oldugu icin). "
                    "Bos bir veri dizini ile baslatin."
                )
                return 2

            if not has_alembic:
                log.info("alembic_version yok, baseline kurulu -> stamp 0001")
                await _alembic("stamp", "0001")

            await _alembic("upgrade", "head")

            rev = await lock_conn.scalar(text("SELECT version_num FROM alembic_version"))
            log.info("sema guncel: %s", rev)
            return 0
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_MIGRATE}
            )


async def _main() -> int:
    try:
        return await run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
