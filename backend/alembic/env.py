"""Alembic ortamı — bağlantı bilgisi app.config'ten gelir, ini'de sır yok."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  — modeller Base.metadata'ya kaydolsun

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include(obj, name, type_, reflected, compare_to) -> bool:
    # v_* görünümleri elle yönetiliyor, autogenerate onlara dokunmasın
    if type_ == "table" and name.startswith("v_"):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_include,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # DDL komutları ACCESS EXCLUSIVE kilit ister. Başka bir oturum tabloyu
    # tutuyorsa migration SÜRESİZ bekler ve PostgreSQL'in kilit kuyruğu sıralı
    # olduğu için arkasındaki tüm okumaları da bloke eder — sistem sessizce
    # kilitlenir. 2026-08-09'da tam olarak bu yaşandı: 8.5 saat asılı kaldı.
    #
    # ⚠️ Bu ayar `connect_args` ile veriliyor, `_do_run` içinde
    # `exec_driver_sql` ile DEĞİL: run_sync bağlamında sürücüye doğrudan
    # komut göndermek migration'ı veritabanına hiç ulaşmadan askıda bıraktı.
    # ⚠️ DDL için SAHİP rol. Uygulama rolünün tablo değiştirme yetkisi yok
    # (Faz 13b-3) — migration'ı onunla koşmak başarısız olurdu.
    engine = create_async_engine(
        settings.migration_database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {
            "lock_timeout": "15000",        # ms
            "statement_timeout": "300000",
        }},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
