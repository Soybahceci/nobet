# NÖBET Kenar Servisi
# Adanmış kutu (Pi) varsayılan paketleme. Kod Docker'a bağımlı DEĞİL —
# düz Python + SQLite; Windows'ta exe olarak paketlenebilir (mimari §2.3b).
FROM python:3.12-slim

WORKDIR /srv
COPY edge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY edge/app ./app

# Kuyruk dosyası bind mount ile dışarıda tutulur; konteyner yenilense de
# bekleyen olaylar kaybolmaz.
VOLUME ["/data"]
ENV QUEUE_PATH=/data/edge.sqlite

RUN useradd --create-home --uid 10002 nobet-edge && mkdir -p /data && chown nobet-edge /data
USER nobet-edge

CMD ["python", "-m", "app.main"]
