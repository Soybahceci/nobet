#!/usr/bin/env python3
"""
NÖBET — Sahte Sunucu (Faz 3 test koşumu)
=========================================
Gerçek backend DEĞİL. Faz 5'e kadar firmware'i tek başına doğrulamak için
kontrat §4'teki alım hattının en sade hâlini taklit eder:

    event al -> dedup -> credential çöz -> effective_ts hesapla -> cmd (ack) yayınla

Kullanım (PowerShell):
    $env:NOBET_MQTT_PASS='...'
    python tools/mock-server/mock_server.py
    python tools/mock-server/mock_server.py --drop 1   # ilk olayı ack'leme (tekrar testi)

Sırlar ortam değişkeninden okunur, dosyaya yazılmaz.
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

HOST = os.environ.get("NOBET_MQTT_HOST", "localhost")
PORT = int(os.environ.get("NOBET_MQTT_PORT", "1883"))
USER = os.environ.get("NOBET_MQTT_USER", "nobet-node")
PASS = os.environ.get("NOBET_MQTT_PASS", "")

# Faz 2'de kayda geçen kartlar. Gerçek sistemde bu bilgi `credential` tablosundan gelir.
KNOWN = {
    "A1B2C3D4": ("Ayşe Y.", "student"),
    "B5C6D7E8": ("Personel K.", "staff"),
}

seen = {}          # (node, seq) -> result   · kontrat §4 dedup
drop_left = 0      # ack'lenmeden bırakılacak olay sayısı (tekrar testi)


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"[{ts()}] BAGLANTI REDDEDILDI: {reason_code}")
        return
    print(f"[{ts()}] brokere baglandi: {HOST}:{PORT}")
    for suffix in ("event", "hb", "status"):
        client.subscribe(f"nobet/v1/+/+/{suffix}", qos=1)
    print(f"[{ts()}] abone: nobet/v1/+/+/{{event,hb,status}}")
    print("-" * 72)


def handle_event(client, topic, d):
    global drop_left

    node = d.get("node", "?")
    seq  = d.get("seq")
    cred = d.get("cred", {})
    uid  = cred.get("id", "")
    up     = d.get("up", 0)
    up_tx  = d.get("up_tx", up)      # kontrat v1.1
    buf    = d.get("buf", 0)

    # --- effective_ts (kontrat §2.3) ---
    server_ts = datetime.now(timezone.utc)
    age_ms = max(0, up_tx - up)
    if d.get("ts"):
        eff, how = d["ts"], "ts (RTC)"
    elif buf == 0:
        eff, how = server_ts.isoformat(), "server_ts (canli)"
    else:
        eff = datetime.fromtimestamp(
            server_ts.timestamp() - age_ms / 1000.0, timezone.utc).isoformat()
        how = f"server_ts - {age_ms}ms (buffer telafisi)"

    key = (node, seq)
    dup = key in seen

    if dup:
        result = seen[key]
        display = "TEKRAR"
        print(f"[{ts()}] << event seq={seq} uid={uid} — ZATEN ISLENDI, ack tekrarlaniyor")
    else:
        if uid in KNOWN:
            name, ptype = KNOWN[uid]
            result  = "granted"
            display = f"{name} · GIRIS"
        else:
            name, ptype = "-", "-"
            result  = "unknown_credential"
            display = "Kayitsiz kart"
        seen[key] = result

        print(f"[{ts()}] << event  seq={seq}  uid={uid}  buf={buf}")
        print(f"          kisi     : {name} ({ptype})")
        print(f"          karar    : {result}")
        print(f"          up={up}  up_tx={up_tx}  yas={age_ms}ms")
        print(f"          eff_ts   : {eff}")
        print(f"                     ^ {how}")

    if drop_left > 0:
        drop_left -= 1
        print(f"          !! ack BILEREK gonderilmedi (tekrar testi, kalan={drop_left})")
        print("-" * 72)
        return

    cmd = {
        "v": 1,
        "ack": seq,
        "result": result,
        "display": display,
        "feedback": "ok",
        "relay_ms": 0,          # kontrat §2.6: prototipte daima 0
    }
    client.publish(topic.replace("/event", "/cmd"), json.dumps(cmd), qos=1)
    print(f"          >> cmd ack={seq} result={result}")
    print("-" * 72)


def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except Exception:
        print(f"[{ts()}] JSON cozulemedi: {msg.topic} {msg.payload[:80]!r}")
        return

    if msg.topic.endswith("/event"):
        handle_event(client, msg.topic, d)
    elif msg.topic.endswith("/hb"):
        print(f"[{ts()}] .. hb   up={d.get('up')}ms rssi={d.get('rssi')}dBm "
              f"heap={d.get('heap')}B kuyruk={d.get('buf_len')} fw={d.get('fw')}")
    elif msg.topic.endswith("/status"):
        state = d.get("state")
        mark = "ONLINE " if state == "online" else "OFFLINE"
        print(f"[{ts()}] ** status[{mark}] node={d.get('node')}  (retained/LWT)")


def main():
    global drop_left
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", type=int, default=0,
                    help="ilk N olayi bilerek ack'leme (firmware tekrar gonderimi testi)")
    args = ap.parse_args()
    drop_left = args.drop

    if not PASS:
        print("HATA: NOBET_MQTT_PASS ortam degiskeni bos.", file=sys.stderr)
        return 1

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nobet-mock-server")
    c.username_pw_set(USER, PASS)
    c.on_connect = on_connect
    c.on_message = on_message

    print("=" * 72)
    print("  NOBET — Sahte Sunucu (Faz 3 test kosumu)")
    if drop_left:
        print(f"  ilk {drop_left} olay BILEREK ack'lenmeyecek")
    print("=" * 72)

    c.connect(HOST, PORT, keepalive=60)
    try:
        c.loop_forever()
    except KeyboardInterrupt:
        print("\nkapatiliyor...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
