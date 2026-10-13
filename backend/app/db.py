"""
NÖBET — Veritabanı oturumu (+ satır düzeyi güvenlik bağlamı)
"""
from collections.abc import AsyncGenerator
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,   # uzun boşluktan sonra kopmuş bağlantıyı yakala
    pool_size=10,
    max_overflow=5,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Satır düzeyi güvenlik bağlamı (Faz 13b-3b, mimari §10.8)
# ---------------------------------------------------------------------------
# Veritabanındaki politikalar `app.tenant_id` oturum değişkenine bakar. Üç
# durum vardır ve üçü de kasıtlıdır:
#
#   ""    → kısıtlama YOK. Kurum daha çözülmeden koşan yollar: giriş
#           (kimlik hangi kuruma üye, henüz bilinmiyor), alım hattı,
#           bootstrap, migration.
#   uuid  → yalnızca o kurumun satırları görünür.
#   "*"   → super_admin. İşletmeci konsolu tanım gereği kurumlar arasıdır;
#           kurum açan uç kendi kısıtlamasıyla kendini göremezdi.
#
# ⚠️ Boşun "her şey" demesi bir kapı gibi duruyor ama değil: RLS burada
# **ikinci sıra savunma.** Uçlar zaten `tenant_id` süzüyor; bu katman o
# süzgecin bir gün unutulduğu satırı yakalamak için var. Boşu "hiçbir şey"
# yapmak, kurum bilgisi olmayan meşru yolları (giriş dahil) kırardı.
_tenant_ctx: ContextVar[str] = ContextVar("nobet_tenant", default="")

_SET = text("SELECT set_config('app.tenant_id', :t, true)")


@event.listens_for(Session, "after_begin")
def _tenant_after_begin(session, transaction, connection) -> None:
    """
    Her işlemin (transaction) başında değişkeni yeniden kurar.

    ⭐ Neden olay dinleyicisi, neden bir kez `SET LOCAL` değil: `SET LOCAL`
    işlem bitince düşer. Uç `commit()` çağırdıktan sonra okumaya devam
    ederse SQLAlchemy YENİ bir işlem açar ve o işlem kısıtlamasız kalırdı.
    Buraya bağlamak, bağlantı havuzuna sızma riskini de kapatıyor:
    değişken işlem yerel, havuza dönen bağlantıda iz kalmaz.
    """
    tid = _tenant_ctx.get()
    if tid:
        connection.execute(_SET, {"t": tid})


async def set_tenant_scope(session: AsyncSession, tenant: str) -> None:
    """
    İstek bağlamını kurar. `current_user` / `current_edge` çağırır.

    İki iş birden yapar: bundan SONRAKİ işlemler için bağlam değişkenini
    yazar, ve ZATEN AÇIK olan işleme değişkeni hemen uygular — kimlik
    doğrulaması sırasında sorgu koşulduğu için işlem çoktan açılmıştır,
    dinleyicinin o işlem için kaçırdığı anı burası kapatır.
    """
    _tenant_ctx.set(tenant)
    await session.execute(_SET, {"t": tenant})


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI bağımlılığı. İstek başına bir oturum."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
