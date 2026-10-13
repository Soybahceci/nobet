# NÖBET — Backend + Web arayüzü tek imajda
# Çok mimarili: sunucu x86_64, nihai hedef Raspberry Pi 5 (aarch64).
#   docker buildx build --platform linux/amd64,linux/arm64 -t nobet-backend .
#
# ⚠️ Derleme bağlamı ÜST dizindir (backend/ ve frontend/ birlikte gerekiyor):
#   docker build -f backend/Dockerfile .

# --- 1. aşama: web arayüzünü derle -----------------------------------------
FROM node:20-slim AS web

WORKDIR /web
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- 2. aşama: çalışma imajı ------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# argon2-cffi ve asyncpg için derleme araçları gerekebilir (arm64 tekerlek yoksa)
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
# Şemayı açılışta yükseltir (denetim O-2). chmod: Windows'tan gelen
# dosyalarda çalıştırma biti olmayabilir.
COPY backend/entrypoint.sh .
RUN chmod +x entrypoint.sh

# Derlenmiş SPA — FastAPI statik olarak servis eder, ek konteyner yok
COPY --from=web /web/dist ./static

# Kök olarak çalıştırma
RUN useradd --create-home --uid 10001 nobet
USER nobet

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
