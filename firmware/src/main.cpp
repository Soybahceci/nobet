/*
 * NÖBET — Node Firmware (Faz 3)
 * ==============================
 * ESP32 DevKit V1 + RC522 · WiFi · MQTT · offline buffer · OTA
 *
 * Kontrat: docs/nobet-faz1-sistem-sozlesmesi.md  (§2 Olay Şeması)
 * Yapılandırma: include/config.h · Sırlar: include/secrets.h
 *
 * Tasarım notları:
 *  - Olay kaybı kabul edilemez: her okuma önce kuyruğa girer, ancak sunucudan
 *    `ack` gelince kuyruktan düşer. Ağ koparsa kuyrukta bekler.
 *  - Kuyruk RAM'de. Elektrik kesilirse gönderilmemiş olaylar kaybolur.
 *    (Bilinen sınır — Faz 11 dayanıklılık kapsamı.)
 *  - `seq` NVS'de kalıcı, blok blok rezerve edilir (bkz. SEQ_RESERVE_BLOCK).
 *  - Hiçbir yerde delay() yok; okuyucu her an cevap verir.
 */

#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <MQTT.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <ArduinoOTA.h>

#include "config.h"
#include "secrets.h"

// ===========================================================================
// Global durum
// ===========================================================================
MFRC522      mfrc(PIN_RC522_SS, PIN_RC522_RST);
WiFiClient   net;
MQTTClient   mqtt(MQTT_BUFFER_SIZE);
Preferences  nvs;

// Topic'ler setup()'ta bir kez kurulur
String topicEvent, topicHb, topicStatus, topicCmd, clientId;

// ===========================================================================
// seq — kalıcı sıra numarası (kontrat §1.2: UNIQUE(node_id, seq))
// ===========================================================================
// NVS'e her olayda yazmak flash'ı yıpratır. Bunun yerine blok rezerve edilir:
// boot'ta bir sonraki blok baştan yazılır, seq bloğu tüketene kadar RAM'de
// artar. Reboot sonrası seq ileri sıçrar — boşluk oluşur, bu sorun değil;
// kontrat benzersizlik istiyor, kesintisiz artış değil.
uint32_t seqNext = 1;   // bir sonraki kullanılacak seq
uint32_t seqHwm  = 1;   // NVS'e yazılmış üst sınır

void seqLoad() {
  nvs.begin("nobet", false);
  seqHwm  = nvs.getUInt("seq_hwm", 1);
  seqNext = seqHwm;
  seqHwm += SEQ_RESERVE_BLOCK;
  nvs.putUInt("seq_hwm", seqHwm);
  Serial.printf("[seq] baslangic=%lu  rezerve_ust=%lu\n",
                (unsigned long)seqNext, (unsigned long)seqHwm);
}

uint32_t seqTake() {
  uint32_t s = seqNext++;
  if (seqNext >= seqHwm) {
    seqHwm = seqNext + SEQ_RESERVE_BLOCK;
    nvs.putUInt("seq_hwm", seqHwm);
    Serial.printf("[seq] yeni blok rezerve edildi -> %lu\n",
                  (unsigned long)seqHwm);
  }
  return s;
}

// ===========================================================================
// Geri bildirim — LED + buzzer (kontrat §2.6)
// ===========================================================================
static inline void drive(uint8_t pin, bool on, bool activeHigh) {
  digitalWrite(pin, (on == activeHigh) ? HIGH : LOW);
}

#define BUZZER_CH 0

void buzzerTone(bool on) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWriteTone(PIN_BUZZER, on ? BUZZER_FREQ_HZ : 0);
#else
  ledcWriteTone(BUZZER_CH, on ? BUZZER_FREQ_HZ : 0);
#endif
}

void ledSet(bool r, bool g, bool b) {
  drive(PIN_LED_R, r, LED_ACTIVE_HIGH);
  drive(PIN_LED_G, g, LED_ACTIVE_HIGH);
  drive(PIN_LED_B, b, LED_ACTIVE_HIGH);
}

// Bloklamayan desen oynatıcı
uint32_t fbLedUntil   = 0;
uint8_t  fbBeepsLeft  = 0;
bool     fbBeepOn     = false;
uint32_t fbBeepNext   = 0;
uint32_t fbBeepOnMs   = 0;
uint32_t fbBeepOffMs  = 0;
uint32_t relayUntil   = 0;

void feedbackStart(bool r, bool g, bool b, uint32_t ledMs,
                   uint8_t beeps, uint32_t onMs, uint32_t offMs) {
  ledSet(r, g, b);
  fbLedUntil  = millis() + ledMs;
  fbBeepsLeft = beeps;
  fbBeepOnMs  = onMs;
  fbBeepOffMs = offMs;
  fbBeepOn    = false;
  fbBeepNext  = millis();   // ilk bip hemen
}

// Kontrat §2.6 tablosu
void feedbackForResult(const char *result) {
  if      (!strcmp(result, "granted"))            feedbackStart(0,1,0, 1000, 1,  80, 120);
  else if (!strcmp(result, "unknown_credential")) feedbackStart(1,1,0, 1000, 2,  80, 120);
  else if (!strcmp(result, "revoked"))            feedbackStart(1,0,0, 2000, 3, 300, 150);
  else if (!strcmp(result, "duplicate"))          feedbackStart(0,0,1,  500, 0,   0,   0);
  else                                            feedbackStart(1,1,1,  400, 0,   0,   0);
}

void feedbackTick() {
  uint32_t now = millis();

  if (fbLedUntil && (int32_t)(now - fbLedUntil) >= 0) {
    ledSet(0, 0, 0);
    fbLedUntil = 0;
  }

  if ((fbBeepsLeft || fbBeepOn) && (int32_t)(now - fbBeepNext) >= 0) {
    if (fbBeepOn) {
      buzzerTone(false);
      fbBeepOn   = false;
      fbBeepNext = now + fbBeepOffMs;
    } else if (fbBeepsLeft > 0) {
      buzzerTone(true);
      fbBeepOn   = true;
      fbBeepsLeft--;
      fbBeepNext = now + fbBeepOnMs;
    }
  }

  if (relayUntil && (int32_t)(now - relayUntil) >= 0) {
    drive(PIN_RELAY, false, RELAY_ACTIVE_HIGH);
    relayUntil = 0;
  }
}

// ===========================================================================
// Outbox — ack'lenene kadar olayları tutan halka tampon
// ===========================================================================
struct OutboxItem {
  uint32_t seq;
  char     uid[21];     // en fazla 10 byte UID -> 20 hex hane + '\0'
  uint32_t upMs;        // okuma anındaki uptime (kontrat: event.up)
  uint32_t lastSentMs;  // 0 = henüz yayınlanmadı
  uint16_t tries;
  bool     buffered;    // kontrat: event.buf
};

OutboxItem outbox[OUTBOX_SIZE];
uint16_t   obHead  = 0;   // OUTBOX_SIZE > 255 olduğu için uint16_t
uint16_t   obCount = 0;
uint32_t   droppedTotal = 0;

void outboxPush(uint32_t seq, const String &uid, uint32_t upMs, bool buffered) {
  if (obCount == OUTBOX_SIZE) {
    // Taşma: en eskiyi düşür. Kapıda bekleyen kişinin okutması,
    // saatler önceki bir kayıttan daha önemli.
    Serial.printf("[outbox] TASMA — seq=%lu dusuruldu\n",
                  (unsigned long)outbox[obHead].seq);
    obHead = (obHead + 1) % OUTBOX_SIZE;
    obCount--;
    droppedTotal++;
  }
  uint16_t slot = (obHead + obCount) % OUTBOX_SIZE;
  OutboxItem &it = outbox[slot];
  it.seq        = seq;
  strncpy(it.uid, uid.c_str(), sizeof(it.uid) - 1);
  it.uid[sizeof(it.uid) - 1] = '\0';
  it.upMs       = upMs;
  it.lastSentMs = 0;
  it.tries      = 0;
  it.buffered   = buffered;
  obCount++;
}

void outboxPopHead() {
  if (obCount == 0) return;
  obHead = (obHead + 1) % OUTBOX_SIZE;
  obCount--;
}

// ===========================================================================
// MQTT yayınları
// ===========================================================================
void publishStatus(const char *state) {
  JsonDocument d;
  d["v"]     = SCHEMA_V;
  d["node"]  = NODE_KEY;
  d["state"] = state;
  String out;
  serializeJson(d, out);
  // retained + QoS 1 — kontrat §2.5
  mqtt.publish(topicStatus, out, true, 1);
}

// Gözcü tarafından doldurulur (aşağıda tanımlı)
extern bool     readerOk;
extern uint32_t readerReinits;

void publishHeartbeat() {
  JsonDocument d;
  d["v"]          = SCHEMA_V;
  d["node"]       = NODE_KEY;
  d["up"]         = millis();
  d["rssi"]       = WiFi.RSSI();
  d["heap"]       = ESP.getFreeHeap();
  d["buf_len"]    = obCount;
  d["fw"]         = FW_VERSION;
  // Kontrat v1.2 — okuyucunun sessiz arızası panelde görünsün
  d["rdr"]        = readerOk ? "ok" : "fail";
  d["rdr_reinit"] = readerReinits;
  String out;
  serializeJson(d, out);
  mqtt.publish(topicHb, out, false, 0);   // QoS 0 — kontrat §2.1
}

void publishEvent(OutboxItem &it) {
  JsonDocument d;
  d["v"]        = SCHEMA_V;
  d["node"]     = NODE_KEY;
  d["seq"]      = it.seq;
  JsonObject c  = d["cred"].to<JsonObject>();
  c["t"]        = "rfid";
  c["id"]       = it.uid;
  d["up"]       = it.upMs;      // okuma anındaki uptime
  d["up_tx"]    = millis();     // ⚠ yayın anındaki uptime — bkz. aşağıdaki not
  d["ts"]       = nullptr;      // RTC yok (kontrat §2.3)
  d["buf"]      = it.buffered ? 1 : 0;
  String out;
  serializeJson(d, out);

  bool ok = mqtt.publish(topicEvent, out, false, 1);   // QoS 1 — kontrat §2.1
  Serial.printf("[event] %s seq=%lu uid=%s buf=%d deneme=%u\n",
                ok ? "yayinlandi" : "YAYIN BASARISIZ",
                (unsigned long)it.seq, it.uid, it.buffered ? 1 : 0,
                (unsigned)it.tries + 1);
}

/* ⚠ KONTRAT AÇIĞI — `up_tx`
 * Kontrat §2.3'teki formül:
 *     effective_ts = server_ts - (uptime_at_flush - up)
 * "uptime_at_flush" = düğümün mesajı YAYINLADIĞI andaki uptime. Ancak §2.2'deki
 * payload şemasında yalnızca `up` (okuma anı) var; yayın anı taşınmıyor.
 * O alan olmadan sunucu formülü hesaplayamaz.
 * Bu firmware alanı `up_tx` adıyla ekliyor. Kontratın v1.1'e çıkması ve
 * §2.2 tablosuna bu satırın yazılması gerekiyor — kullanıcı onayı bekliyor.
 * Canlı olaylarda (buf=0) alan kullanılmaz, effective_ts = server_ts.
 */

// ===========================================================================
// Outbox pompası — sırayla, ack bekleyerek
// ===========================================================================
void outboxPump() {
  if (!mqtt.connected() || obCount == 0) return;

  OutboxItem &it = outbox[obHead];
  uint32_t now = millis();

  if (it.lastSentMs != 0 && (now - it.lastSentMs) < ACK_TIMEOUT_MS) return;

  if (it.lastSentMs != 0) {
    // Tekrar gönderim: olay gecikti, sunucu zaman telafisi uygulamalı
    it.buffered = true;
  }
  publishEvent(it);
  it.lastSentMs = now;
  it.tries++;
}

// ===========================================================================
// cmd — sunucu yanıtı (kontrat §2.6)
// ===========================================================================
void onMqttMessage(String &topic, String &payload) {
  JsonDocument d;
  if (deserializeJson(d, payload)) {
    Serial.println("[cmd] JSON cozulemedi, yok sayildi");
    return;
  }

  uint32_t ack = d["ack"] | 0UL;
  const char *result = d["result"] | "";

  if (ack == 0) {
    Serial.println("[cmd] ack alani yok, yok sayildi");
    return;
  }

  if (obCount > 0 && outbox[obHead].seq == ack) {
    Serial.printf("[cmd] ack=%lu result=%s -> kuyruktan dusuruldu (kalan=%u)\n",
                  (unsigned long)ack, result, (unsigned)obCount - 1);
    outboxPopHead();
  } else {
    // Sunucu duplicate ack yollamış olabilir (idempotency). Zararsız.
    Serial.printf("[cmd] ack=%lu bekleyenle eslesmedi, yok sayildi\n",
                  (unsigned long)ack);
  }

  feedbackForResult(result);

  const char *display = d["display"] | "";
  if (strlen(display)) Serial.printf("[cmd] ekran: %s\n", display);

  // Röle — kontrat §2.6: prototipte sunucu daima relay_ms=0 gönderir.
  uint32_t relayMs = d["relay_ms"] | 0UL;
  if (relayMs > 0) {
    drive(PIN_RELAY, true, RELAY_ACTIVE_HIGH);
    relayUntil = millis() + relayMs;
    Serial.printf("[cmd] role %lu ms tetiklendi\n", (unsigned long)relayMs);
  }
}

// ===========================================================================
// Bağlantı yönetimi — bloklamayan
// ===========================================================================
uint32_t wifiNextTry = 0;
uint32_t mqttNextTry = 0;
bool     otaStarted  = false;

uint16_t wifiTries = 0;
bool     wifiScanned = false;

// Bağlanamadığımızda çevredeki ağları listele. SSID'de görünmeyen karakter
// (kıvrık kesme işareti, Türkçe İ, baştaki/sondaki boşluk) varsa tahmin
// etmek yerine gerçek adı gözle görürüz.
void wifiScanDiagnostic() {
  Serial.println("[wifi] --- baglanti kurulamadi, cevre taraniyor ---");
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    Serial.println("[wifi] hicbir ag gorunmuyor (anten/menzil?)");
  } else {
    Serial.printf("[wifi] %d ag bulundu:\n", n);
    for (int i = 0; i < n; i++) {
      String s = WiFi.SSID(i);
      Serial.printf("  %2d) rssi=%4d  \"%s\"  [", i + 1, WiFi.RSSI(i), s.c_str());
      // Ham baytlar: ASCII disi karakterleri boylece ayirt ederiz
      for (size_t k = 0; k < s.length(); k++) {
        uint8_t b = (uint8_t)s[k];
        if (b >= 0x20 && b < 0x7F) Serial.printf("%c", b);
        else                       Serial.printf("\\x%02X", b);
      }
      Serial.println("]");
    }
    Serial.printf("[wifi] aradigimiz: \"%s\"\n", WIFI_SSID);
  }
  WiFi.scanDelete();
  Serial.println("[wifi] --- tarama sonu ---");
}

void wifiEnsure() {
  if (WiFi.status() == WL_CONNECTED) {
    if (wifiTries) {   // yeni bağlandı
      Serial.printf("[wifi] BAGLANDI  ip=%s  rssi=%d dBm\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      wifiTries = 0;
    }
    return;
  }
  uint32_t now = millis();
  if (now < wifiNextTry) return;
  wifiNextTry = now + WIFI_RETRY_MS;

  // Ağ yoksa saatlerce her 5 sn'de bir satır basmak seri monitörü
  // kullanılamaz hâle getirir. İlk denemeler görünsün, sonrası seyrelsin.
  wifiTries++;
  if (wifiTries <= 3 || wifiTries % 12 == 0) {
    Serial.printf("[wifi] baglaniliyor: %s (deneme %u)\n", WIFI_SSID, wifiTries);
  }
  if (wifiTries == 4 && !wifiScanned) {   // birkaç deneme tutmadıysa teşhis
    wifiScanned = true;
    wifiScanDiagnostic();
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);          // MQTT gecikmesini düşürür
  WiFi.setHostname(NODE_KEY);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void otaEnsure() {
  if (otaStarted || WiFi.status() != WL_CONNECTED) return;
  ArduinoOTA.setHostname(NODE_KEY);
  ArduinoOTA.setPassword(OTA_PASS);
  ArduinoOTA
    .onStart([]() {
      Serial.println("[ota] guncelleme basladi — okuyucu durduruldu");
      ledSet(0, 0, 1);
    })
    .onEnd([]() { Serial.println("[ota] tamam, yeniden baslatiliyor"); })
    .onError([](ota_error_t e) { Serial.printf("[ota] HATA %u\n", e); });
  ArduinoOTA.begin();
  otaStarted = true;
  Serial.printf("[ota] hazir — hostname=%s ip=%s\n",
                NODE_KEY, WiFi.localIP().toString().c_str());
}

void mqttEnsure() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  uint32_t now = millis();
  if (now < mqttNextTry) return;
  mqttNextTry = now + MQTT_RETRY_MS;

  Serial.printf("[mqtt] baglaniliyor: %s:%d\n", MQTT_HOST, MQTT_PORT);

  bool ok = (strlen(MQTT_USER) > 0)
              ? mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)
              : mqtt.connect(clientId.c_str());

  if (!ok) {
    Serial.printf("[mqtt] basarisiz (hata=%d)\n", mqtt.lastError());
    return;
  }

  Serial.println("[mqtt] BAGLANDI");
  publishStatus("online");
  mqtt.subscribe(topicCmd, 1);      // QoS 1 — kontrat §2.1
  Serial.printf("[mqtt] abone: %s\n", topicCmd.c_str());
}

// ===========================================================================
// Sistem LED'i — bakılınca durum anlaşılsın
//   sabit yanık  = MQTT bağlı
//   yavaş yanıp sönme = WiFi var, MQTT yok
//   hızlı yanıp sönme = WiFi yok
// ===========================================================================
void sysLedTick() {
  uint32_t period;
  if (mqtt.connected())                    { digitalWrite(PIN_SYS_LED, HIGH); return; }
  else if (WiFi.status() == WL_CONNECTED)  period = 1000;
  else                                     period = 200;
  digitalWrite(PIN_SYS_LED, (millis() / (period / 2)) % 2);
}

// ===========================================================================
// RC522
// ===========================================================================
String lastUid;
uint32_t lastReadMs = 0;

String uidToHex(MFRC522::Uid *uid) {
  String s;
  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) s += "0";
    s += String(uid->uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void readerSelfTest() {
  byte v = mfrc.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.printf("[rc522] VersionReg = 0x%02X ", v);
  if (v == 0x00 || v == 0xFF) {
    Serial.println("-> HATA: okuyucuya ulasilamiyor (kablolama/besleme)");
  } else {
    Serial.printf("-> OK (%s)\n", v == 0x91 ? "v1.0" : v == 0x92 ? "v2.0" : "klon");
  }
}

// ---------------------------------------------------------------------------
// Okuyucu gözcüsü
// ---------------------------------------------------------------------------
// 2026-08-09: RC522'nin askıda kaldığı görüldü — SPI cevap veriyordu ama
// hiçbir kart algılanmıyordu. Sistemin geri kalanı sağlıklı olduğu için
// panelde arıza görünmüyordu. İki şeye bakıyoruz:
//   1. VersionReg hâlâ okunabiliyor mu (SPI ayakta mı)
//   2. Anten sürücüsü açık mı (TxControlReg bit0/bit1) — RC522'nin bilinen
//      arızası: RF alanı sessizce kapanır, okuyucu "çalışır" görünür.
uint32_t readerCheckNext = 0;
uint32_t readerReinits   = 0;   // kontrat v1.2: hb.rdr_reinit
bool     readerOk        = true; // kontrat v1.2: hb.rdr

bool readerHealthy() {
  byte v = mfrc.PCD_ReadRegister(MFRC522::VersionReg);
  if (v == 0x00 || v == 0xFF) return false;
  byte tx = mfrc.PCD_ReadRegister(MFRC522::TxControlReg);
  return (tx & 0x03) == 0x03;      // Tx1RFEn + Tx2RFEn açık olmalı
}

void readerReinit() {
  readerReinits++;
  Serial.printf("[rc522] ARIZA ALGILANDI — yeniden baslatiliyor (#%lu)\n",
                (unsigned long)readerReinits);
  SPI.end();
  delay(10);
  SPI.begin();
  mfrc.PCD_Init();
  delay(50);
  mfrc.PCD_SetAntennaGain(MFRC522::RxGain_max);
  byte v = mfrc.PCD_ReadRegister(MFRC522::VersionReg);
  readerOk = readerHealthy();
  Serial.printf("[rc522] yeniden baslatildi, VersionReg=0x%02X %s\n",
                v, readerOk ? "-> saglikli" : "-> HALA ARIZALI");
}

void readerWatchdog() {
  if (millis() < readerCheckNext) return;
  readerCheckNext = millis() + READER_CHECK_MS;

  readerOk = readerHealthy();
  if (!readerOk) readerReinit();   // readerOk'i yeniden değerlendirir
}

void readerTick() {
  if (!mfrc.PICC_IsNewCardPresent()) return;
  if (!mfrc.PICC_ReadCardSerial())   return;

  String uid   = uidToHex(&mfrc.uid);
  uint32_t now = millis();

  if (uid == lastUid && (now - lastReadMs) < READ_DEBOUNCE_MS) {
    mfrc.PICC_HaltA();
    mfrc.PCD_StopCrypto1();
    return;
  }
  lastUid    = uid;
  lastReadMs = now;

  uint32_t seq = seqTake();
  bool offline = !mqtt.connected();
  outboxPush(seq, uid, now, offline);

  Serial.printf(">> OKUMA seq=%lu uid=%s %s (kuyruk=%u)\n",
                (unsigned long)seq, uid.c_str(),
                offline ? "[CEVRIMDISI — tamponlandi]" : "[canli]",
                (unsigned)obCount);

  // Çevrimdışıysak kullanıcıya "okundu" geri bildirimi ver; ağ varsa
  // geri bildirimi sunucunun cmd yanıtı belirler (kontrat §2.6).
  if (offline) feedbackStart(0, 0, 1, 300, 1, 60, 0);

  mfrc.PICC_HaltA();
  mfrc.PCD_StopCrypto1();
}

// ===========================================================================
// setup / loop
// ===========================================================================
uint32_t hbNext = 0;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("========================================");
  Serial.printf("  NOBET Node Firmware v%s\n", FW_VERSION);
  Serial.printf("  tenant=%s node=%s\n", TENANT_SLUG, NODE_KEY);
  Serial.println("========================================");

  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  pinMode(PIN_SYS_LED, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  ledSet(0, 0, 0);
  drive(PIN_RELAY, false, RELAY_ACTIVE_HIGH);   // röle daima pasif başlar

#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_BUZZER, BUZZER_FREQ_HZ, 10);
#else
  ledcSetup(BUZZER_CH, BUZZER_FREQ_HZ, 10);
  ledcAttachPin(PIN_BUZZER, BUZZER_CH);
#endif
  buzzerTone(false);

  SPI.begin();
  mfrc.PCD_Init();
  delay(50);
  readerSelfTest();
  mfrc.PCD_SetAntennaGain(MFRC522::RxGain_max);

  seqLoad();

  // Topic'ler — kontrat §2.1
  String base  = String("nobet/v1/") + TENANT_SLUG + "/" + NODE_KEY;
  topicEvent   = base + "/event";
  topicHb      = base + "/hb";
  topicStatus  = base + "/status";
  topicCmd     = base + "/cmd";
  clientId     = String("nobet-") + NODE_KEY + "-" +
                 String((uint32_t)(ESP.getEfuseMac() & 0xFFFFFF), HEX);

  Serial.printf("[mqtt] topic tabani: %s\n", base.c_str());

  // LWT — kontrat §2.5: retained, QoS 1
  {
    JsonDocument d;
    d["v"]     = SCHEMA_V;
    d["node"]  = NODE_KEY;
    d["state"] = "offline";
    String lwt;
    serializeJson(d, lwt);
    mqtt.setWill(topicStatus.c_str(), lwt.c_str(), true, 1);
  }

  mqtt.begin(MQTT_HOST, MQTT_PORT, net);
  mqtt.onMessage(onMqttMessage);

  wifiEnsure();
  Serial.println("----------------------------------------");
}

void loop() {
  wifiEnsure();
  otaEnsure();
  mqttEnsure();

  if (otaStarted) ArduinoOTA.handle();
  mqtt.loop();

  readerWatchdog();
  readerTick();
  outboxPump();
  feedbackTick();
  sysLedTick();

  if (mqtt.connected() && millis() >= hbNext) {
    hbNext = millis() + HB_INTERVAL_MS;
    publishHeartbeat();
  }
}
