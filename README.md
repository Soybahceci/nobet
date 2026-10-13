# NÖBET

**Eğitim kurumları için açık kaynak geçiş kontrol ve yoklama sistemi.**
ESP32 tabanlı RFID okuyucular, MQTT ve PostgreSQL üzerine kurulu; kurum personelinin terminale hiç girmeden, yalnızca web arayüzünden yönettiği bir sistem.

*[English summary below](#english)*

> **Durum:** Prototip. Çekirdek akış (kart okutma → olay → oturum → rapor ve veli bildirimi) gerçek donanımla uçtan uca çalışıyor. Üretim kullanımından önce [Bilinen sınırlar](#bilinen-sınırlar) bölümünü okuyun.

---

## Neler yapıyor

- **Giriş/çıkış kaydı:** Öğrenci ve personel kartını okuyucuya okutur; olay anında kaydedilir, giriş/çıkış oturumları olaylardan türetilir.
- **Bağlantı kopsa da veri kaybolmaz:** Okuyucu olayları kendi tamponunda tutar, bağlantı gelince yeniden gönderir. Her olay `node_id + seq` ile benzersiz olduğu için tekrar gönderimde çift kayıt oluşmaz.
- **Saat donanımı gerektirmez:** Olay zamanı, cihazın çalışma süresi farkından hesaplanır (RTC modülü yok).
- **Arayüzden kart kaydı:** Tanınmayan bir kart okutulunca arayüzde görünür ve oradan bir kişiye bağlanır.
- **Veli bildirimi:** 18 yaş altı öğrencinin giriş ve çıkışında veliye mesaj (WhatsApp ağ geçidi veya SMS sağlayıcıları; varsayılan `dryrun`).
- **Roller ve çok kurum:** Sistem yöneticisi, kurum yöneticisi, görevli ve koç rolleri; tek hesapla birden fazla kuruma üyelik; PostgreSQL satır düzeyi güvenliği (RLS) ile kurumlar arası yalıtım.
- **Raporlar ve yoklama:** Anlık "içeride kim var", oturum geçmişi, sınıf yoklaması, elle giriş/çıkış düzeltmesi.
- **Kenar cihazı (SaaS modu):** Kurumun içinde çalışan küçük bir servis olayları yerelde kuyruğa alır ve buluta iletir; kurumun modeminde port açmak gerekmez.

## Mimari

```
ESP32 + RC522  ──MQTT──►  Mosquitto  ──►  ingest  ──►  PostgreSQL
 (okuyucu düğüm)                                          ▲
                                                          │
                          Tarayıcı  ◄──HTTP──►  api (FastAPI + React arayüz)
                                                          │
                                         wa-gateway / SMS sağlayıcıları (bildirim)
```

| Dizin | İçerik |
|---|---|
| `firmware/` | ESP32 düğüm yazılımı (PlatformIO, Arduino çatısı) |
| `backend/` | FastAPI uygulaması, MQTT alım hattı (`ingest`), Alembic migration'ları |
| `frontend/` | React + TypeScript web arayüzü (Vite) |
| `edge/` | Kurum içi kenar servisi (SQLite kuyruk, buluta senkron) |
| `wa-gateway/` | WhatsApp ağ geçidi (bkz. [uyarı](#bilinen-sınırlar)) |
| `postgres/` | Şema (`init/`) ve yalnızca geliştirme için örnek veri (`seed-dev/`) |
| `mosquitto/` | MQTT broker yapılandırması |
| `tests/` | Yetki, RLS ve gecikmeli bildirim uçtan uca testleri |
| `tools/` | Sahte MQTT sunucusu ve donanım doğrulama araçları |
| `docs/` | Sistem sözleşmesi, SaaS mimarisi, tasarım kararları, güvenlik denetimi |

## Kurulum

Gereksinimler: Docker ve Docker Compose. Sunucu tarafı x86_64 ve ARM64 (ör. Raspberry Pi 5) üzerinde çalışır.

**1. Ortam değişkenleri**

```bash
cp .env.example .env
# .env içindeki DEGISTIR değerlerini doldurun (üretme komutları dosyada yazılı)
```

**2. MQTT kullanıcısı** (broker anonim bağlantıyı kabul etmez)

```bash
docker run --rm -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c -b /mosquitto/config/passwd nobet-node 'MQTT_PASS_DEGERINIZ'
```

**3. Yığını başlatın ve uygulama rolünü açın**

```bash
docker compose up -d
./nobet-app-rolu-ac.sh                         # süper olmayan veritabanı rolü
docker compose up -d --force-recreate api ingest
```

**4. İlk kurum ve yönetici**

```bash
docker compose run --rm \
  -e BOOTSTRAP_TENANT_NAME='Örnek Kurum' \
  -e BOOTSTRAP_TENANT_SLUG=ornek-kurum \
  -e BOOTSTRAP_EMAIL=yonetici@ornek.com \
  -e BOOTSTRAP_PASSWORD='en-az-12-karakter' \
  api python -m app.bootstrap
```

Arayüz: `http://<sunucu>:8080`. Mekânlar, okuyucular, kişiler, kartlar ve kullanıcılar buradan eklenir.

WhatsApp bildirimi kullanacaksanız `compose.yml` içindeki `wa-gateway` notlarını okuyun (oturum dizininin izinleri).

### Firmware

Donanım: ESP32 DevKit V1 + RC522 RFID okuyucu. Pin bağlantıları `firmware/include/config.h` içinde.

```bash
cd firmware
cp include/secrets.h.example include/secrets.h   # Wi-Fi, broker adresi, MQTT ve OTA parolası
# include/config.h: TENANT_SLUG ve NODE_KEY arayüzdeki kurum ve düğümle aynı olmalı
pio run -t upload
```

Kablosuz güncelleme: `NOBET_OTA_PASS=... pio run -e ota -t upload`

### Testler

```bash
./tests/13b3-yetki.sh            # rol ve yetki matrisi
./tests/13b3b-rls.sh             # kurumlar arası yalıtım (RLS)
./tests/gecikmeli-bildirim.sh    # gecikmeli olayların bildirimi
```

Testler `compose.test.yml` ile ayrı ve geçici bir yığın kurar; veri diske yazılmaz.

## Bilinen sınırlar

- **WhatsApp ağ geçidi resmî değildir.** `wa-gateway`, kişisel bir WhatsApp hesabını gayriresmî bir kütüphane (Baileys) ile sürer. Bu, WhatsApp kullanım koşullarına aykırı olabilir ve hesabın kapatılmasına yol açabilir. Gerçek bir kurumda resmî WhatsApp Cloud API veya SMS kanalı kullanılmalıdır. Varsayılan kanal `dryrun`'dır: mesajlar üretilir ama gönderilmez.
- **MQTT'de TLS yok.** Okuyucularla broker arasındaki trafik şifrelenmez; broker'ı yalnızca güvenilen yerel ağa açın.
- **Biyometri varsayılan olarak kapalı.** Kimlik katmanı parmak izi okuyucuyu destekleyecek şekilde soyutlanmıştır, ancak varsayılan ve önerilen yöntem RFID karttır. Türkiye'de KVKK Kurulu'nun biyometrik verilerle yoklama alınmasına ilişkin kararları nedeniyle biyometriyi etkinleştirmeden önce hukuki görüş alın.
- **Kişisel veri.** Sistem öğrenci, personel ve veli bilgisi işler. Kurulumu yapan, ilgili mevzuata (KVKK) uyumdan sorumludur. `postgres/seed-dev/` içindeki örnek veriyi üretimde çalıştırmayın.

## Dokümanlar

- [Sistem sözleşmesi](docs/nobet-faz1-sistem-sozlesmesi.md): veri modeli, MQTT olay şeması, API ve alım hattı
- [SaaS mimarisi](docs/nobet-faz13-saas-mimarisi.md): kenar cihazı, senkronizasyon, çok kurum, abonelik
- [Karar: sırasız olaylar](docs/nobet-karar-sirasiz-olaylar.md)
- [Kod ve plan denetimi](docs/nobet-denetim-2026-08-10.md): bulunan güvenlik açıkları ve kapatılışları

## Lisans

[GNU Affero General Public License v3.0](LICENSE). Kodu değiştirip ağ üzerinden hizmet olarak sunarsanız, değiştirdiğiniz kaynak kodu da kullanıcılarınıza açmanız gerekir.

Geliştiren: [Arda Murat Soybahçeci](https://ardamuratsoybahceci.com.tr)

---

## English

**NÖBET** is an open-source access control and attendance system for educational institutions, built on ESP32-based RFID readers, MQTT and PostgreSQL. Staff manage everything from a web UI; nobody at the institution ever needs a terminal.

Highlights: immutable event log with sessions derived from it; offline buffering on the reader with idempotent replay (`node_id + seq`); timestamps without an RTC module; card enrollment from the UI; guardian notifications; multi-tenant with PostgreSQL row-level security; an optional edge service that queues events locally and syncs to the cloud.

Setup is in the Turkish sections above (Docker Compose; the commands are language-neutral). The codebase comments and docs are in Turkish.

Status: prototype. The WhatsApp gateway uses an unofficial library and should be replaced with the official Cloud API or SMS in real deployments. MQTT has no TLS yet.

Licensed under [AGPL-3.0](LICENSE).
