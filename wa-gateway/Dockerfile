# NÖBET — WhatsApp ağ geçidi
# Baileys saf WebSocket kullanır; Chromium gerekmez, arm64'te de çalışır.
FROM node:20-slim

WORKDIR /srv
COPY package.json ./

# Baileys'in bağımlılıklarından biri git deposundan çekiliyor; node:20-slim'de
# git yok. Kurulumdan sonra temizleniyor ki imaj şişmesin.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && npm install --omit=dev --no-audit --no-fund \
 && apt-get purge -y git \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /root/.npm

COPY server.js ./

# Oturum bilgileri volume'de kalıcı — konteyner yeniden başlayınca
# QR tekrar okutulmasın.
RUN mkdir -p /data/auth && useradd --uid 10002 --create-home wa \
 && chown -R wa:wa /data /srv
USER wa

ENV AUTH_DIR=/data/auth PORT=3000
EXPOSE 3000
CMD ["node", "server.js"]
