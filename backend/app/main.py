"""NÖBET — FastAPI uygulaması (Faz 5)"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.routers import (
    admin, auth, chat, edge, enroll, infra, notifications, people, read, reports,
    users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("nobet.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    log.info("veritabani baglantisi dogrulandi")
    yield
    await engine.dispose()


# Denetim O-4: API dokümanı varsayılan olarak KAPALI. Açmak için
# DOCS_ENABLED=true (ya da DEBUG=true). Kapalıyken yollar 404 döner.
_docs = settings.docs_enabled or settings.debug
if not _docs:
    log.info("API dokumani kapali (DOCS_ENABLED=true ile acilir)")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# Denetim O-1: CORS yalnızca AÇIKÇA izin verilen kökenler için kurulur.
# Arayüz API ile aynı kökenden servis edildiği için normalde hiç gerekmez;
# eski `["*"]` + `allow_credentials=True` bileşimi hem şartnameye aykırıydı
# hem de SaaS'ta savunulamazdı.
if settings.cors_origins:
    log.info("CORS izinli kokenler: %s", ", ".join(settings.cors_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

for r in (auth.router, users.router, people.router, enroll.router, infra.router,
          notifications.router, chat.router, reports.router, read.router,
          edge.router, admin.router):
    app.include_router(r, prefix=settings.api_prefix)


def _expected_revision() -> str | None:
    """
    Kodun beklediği migration sürümü (alembic 'head').

    Okunamazsa `None` döner ve şema kontrolü atlanır — paketleme sorunu
    yüzünden sağlıklı bir sistemi `unhealthy` göstermek istemiyoruz. Ama
    sessiz kalmıyoruz: günlüğe uyarı düşer.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        return ScriptDirectory.from_config(Config(str(ini))).get_current_head()
    except Exception as exc:  # pragma: no cover
        log.warning("beklenen sema surumu okunamadi, kontrol atlaniyor: %s", exc)
        return None


EXPECTED_REVISION = _expected_revision()


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """
    Sağlık kontrolü — **şema sürümü dahil** (denetim bulgusu O-2).

    Eskiden yalnızca `SELECT 1` yapıyordu. Bu bir kör noktaydı: yarım
    migrate edilmiş bir veritabanında konteyner `healthy` raporluyor, hata
    ancak eksik tabloya ilk dokunulduğunda çıkıyordu. Aynı kör nokta
    2026-08-10'da `UserOut` çakışmasının fark edilmesini de geciktirmişti.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        db_rev = await conn.scalar(text("SELECT version_num FROM alembic_version"))

    if EXPECTED_REVISION and db_rev != EXPECTED_REVISION:
        # İki yön de mümkün ve sebepleri farklı; mesaj hangisi olduğunu
        # söylemeli. "Şema eski" demek, veritabanının ileride olduğu
        # durumda yanlış yere baktırır (2026-08-10'da tam bu oldu).
        if db_rev and EXPECTED_REVISION and db_rev > EXPECTED_REVISION:
            detail = (
                f"veritabanı '{db_rev}', bu konteynerin kodu '{EXPECTED_REVISION}' "
                "bekliyor — ESKİ İMAJ çalışıyor. Konteyner yeniden oluşturulmalı."
            )
        else:
            detail = (
                f"veritabanı '{db_rev}', kod '{EXPECTED_REVISION}' bekliyor — "
                "MIGRATION çalışmamış olabilir."
            )
        # 503: konteyner sağlıksız sayılsın, trafik almasın.
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ok", "schema": db_rev or "bilinmiyor"}


# ---------------------------------------------------------------------------
# Web arayüzü (Faz 6)
# ---------------------------------------------------------------------------
# Derlenmiş SPA imajın içinde /srv/static altında. Ayrı bir web sunucusu
# konteyneri açmak yerine buradan servis ediliyor: tek imaj, CORS derdi yok,
# Pi'ye taşımak da tek parça.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Sınır bir kez çözülür — her istekte disk erişimi yapmaya gerek yok.
_STATIC_ROOT = STATIC_DIR.resolve()


def _within_static(p: Path) -> bool:
    """Çözümlenmiş yol statik klasörün altında mı? (dizin aşımı koruması)"""
    return _STATIC_ROOT == p or _STATIC_ROOT in p.parents


if STATIC_DIR.is_dir():
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """
        İstemci tarafı yönlendirme: /kisiler gibi yollar sunucuda yok,
        index.html döndürülür ve React Router devralır.
        """
        # API yolları buraya düşerse gerçek 404 dönmeli — index.html değil,
        # aksi hâlde yanlış uç adresi sessizce HTML sayfası döndürür.
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
            raise HTTPException(status_code=404, detail="bulunamadı")

        # ⚠️ DİZİN AŞIMI KORUMASI — 2026-08-10 denetiminde bulundu (K-1).
        #
        # `full_path` istemciden geliyor. Eskiden doğrudan STATIC_DIR'e
        # ekleniyordu; `..` parçalarıyla statik klasörün DIŞINA çıkılıp
        # sunucudaki herhangi bir dosya okunabiliyordu. Denendi ve
        # doğrulandı: /%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd → 200.
        #
        # Yukarıdaki startswith kontrolü bunu engellemez — aşım denemesi
        # "api/" ile başlamaz.
        #
        # resolve() `..` parçalarını ve sembolik bağları çözer; sonuç
        # gerçekten kökün altında mı diye ayrıca bakılır. İkisi birlikte
        # gerekli: yalnız resolve() yolu normalleştirir ama sınırı zorlamaz.
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and _within_static(candidate):
            return FileResponse(candidate)

        # Aşım denemesi de dahil, eşleşmeyen her yol index.html alır:
        # 403/404 ayrımı saldırgana hangi dosyaların var olduğunu söylerdi.
        return FileResponse(STATIC_DIR / "index.html")

else:  # pragma: no cover
    log.warning("static/ bulunamadi — web arayuzu servis edilmiyor")
