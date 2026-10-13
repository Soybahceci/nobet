/*
 * NÖBET — Düğüm Yapılandırması
 * =============================
 * Sırlar burada DEĞİL. WiFi/MQTT parolaları `secrets.h` içinde.
 * Bu dosya versiyon kontrolüne girer, `secrets.h` girmez.
 *
 * Kontrat: docs/nobet-faz1-sistem-sozlesmesi.md
 */
#pragma once

// ---------------------------------------------------------------------------
// Düğüm kimliği — kontrat §1.2 `node`, §2.1 topic yapısı
// ---------------------------------------------------------------------------
#define TENANT_SLUG   "ornek-kurum"   // [a-z0-9-] · MQTT topic'te kullanılır
#define NODE_KEY      "giris-01"      // node.node_key ile birebir aynı olmalı
#define FW_VERSION    "0.1.0"         // hb.fw alanı

#define SCHEMA_V      1               // payload "v" alanı

// ---------------------------------------------------------------------------
// Pinler
// ---------------------------------------------------------------------------
// RC522 — Faz 2'de doğrulandı, KİLİTLİ
#define PIN_RC522_SS   5
#define PIN_RC522_RST  22
// SCK=18, MOSI=23, MISO=19 (VSPI varsayılan, tanımlamaya gerek yok)

// Geri bildirim — kontrat §2.6 tablosu
// Not: Prototipte bu bileşenler henüz lehimli değil. Pinler ayrıldı,
// kod çalışıyor, takıldığında ek değişiklik gerekmiyor.
#define PIN_LED_R      25
#define PIN_LED_G      26
#define PIN_LED_B      27
#define LED_ACTIVE_HIGH  1            // ortak katot = 1, ortak anot = 0

#define PIN_BUZZER     4              // pasif buzzer (LEDC ile ton üretilir)
#define BUZZER_FREQ_HZ 2700           // pasif buzzerların rezonans tepesi

// Onboard mavi LED (DevKit V1) — sistem durumu: WiFi/MQTT
#define PIN_SYS_LED    2

// Röle — kontrat §2.6: prototipte DAİMA pasif (`relay_ms: 0`)
#define PIN_RELAY      13
#define RELAY_ACTIVE_HIGH 1

// ---------------------------------------------------------------------------
// Zamanlamalar
// ---------------------------------------------------------------------------
#define HB_INTERVAL_MS      30000UL   // kontrat §2.4: 30 sn
#define ACK_TIMEOUT_MS       5000UL   // ack gelmezse tekrar yayınla
#define WIFI_RETRY_MS        5000UL
#define MQTT_RETRY_MS        3000UL
#define READ_DEBOUNCE_MS     2000UL   // Faz 2'de doğrulandı

// RC522 gözcüsü — 2026-08-09'da sahada görülen arızaya karşı.
// Okuyucu askıda kalabiliyor: WiFi/MQTT/heartbeat çalışmaya devam ediyor,
// düğüm panelde "çevrimiçi" görünüyor, ama hiçbir kart okunmuyor. Sessiz
// arıza olduğu için fark edilmesi çok zor. Periyodik sağlık kontrolü ile
// okuyucu yeniden başlatılır.
#define READER_CHECK_MS      5000UL

// Olay kuyruğu (RAM). Taşarsa EN ESKİ olay düşer — kapıda bekleyen
// kişinin okutması, saatler önceki bir kayıttan daha değerlidir.
// Kenar cihazı (Faz 13) olayı alır almaz ack verdiği için normal işleyişte
// tampon neredeyse hiç dolmaz. Bu boyut, KENAR CİHAZI KAPALIYKEN geçen süre
// için: resepsiyon bilgisayarı sabah geç açılırsa ya da kutu yeniden
// başlarsa hiçbir okuma kaybolmasın.
// ⚠️ 255'ten büyük yapılacaksa obHead/obCount/slot uint16_t OLMALI —
//    uint8_t ile sayaç sarar ve halka tampon sessizce bozulur.
#define OUTBOX_SIZE          1000

// NVS yazma aşınmasını azaltmak için seq blok blok rezerve edilir.
// Reboot'ta seq ileri sıçrar (boşluk oluşur) — kontrat yalnızca
// benzersizlik istiyor (§1.2 UNIQUE(node_id, seq)), süreklilik değil.
#define SEQ_RESERVE_BLOCK    20

// MQTT payload tamponu — event ~200B, hb ~140B. 1 KB fazlasıyla yeter.
#define MQTT_BUFFER_SIZE     1024
