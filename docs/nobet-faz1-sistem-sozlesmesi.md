# NÖBET — Faz 1: Sistem Sözleşmesi

**Sürüm:** 2.1
**Kapsam:** Veri modeli + Olay şeması + API kontratı
**Durum:** Onay bekliyor

> Bu doküman firmware ile backend arasındaki **tek doğruluk kaynağıdır.** Onaylandıktan sonra iki taraf paralel yazılabilir. Kontrat değişirse sürüm numarası artar.

### Sürüm Geçmişi

| Sürüm | Tarih | Değişiklik |
|---|---|---|
| 2.1 | 2026-08-16 | **`notification.direction` eklendi** — v2.0'daki bir kusurun düzeltmesi. `notification_once_session` benzersiz indeksi `(session_id, guardian_id)` idi; ama **bir oturum iki bildirim üretir** (giriş ve çıkış) ve ikisi de aynı satıra bağlanır. Kart yolunda bunlar ayrı `event` satırı olduğu için sorun çıkmıyordu. ⚠️ Sonucu yalnızca "bildirim gitmez" değildi: `enqueue`, elle çıkış ucunun **işlemi içinde** çağrılıyor; benzersizlik ihlali o işlemi geri alır ve **çıkış kaydını tümden düşürürdü** — yani veli bildirimi yüzünden öğrencinin çıkışı kaydedilemezdi. İndeks `(session_id, guardian_id, direction)` oldu. Yan fayda: yön artık `body` metnine gömülü değil, sorgulanabilir. Kart kaynaklı bildirimlerde de dolduruluyor. |
| 2.0 | 2026-08-12 | **Elle giriş/çıkış** (Faz 13a-5, kullanıcı onayı). Öğrenci kartını unutur, kart bozulur ya da okuyucu arıza yaparsa kapıdaki görevli kaydı elle açabilmeli — bugüne kadar hiçbir yolu yoktu ve kart okunmazsa öğrenci sistemde **hiç görünmüyordu**. `attendance_session.entry_event_id` **NULL olabilir** hâle geldi; `entry_source` (`card`\|`manual`) ve `created_by` eklendi. `notification.event_id` NULL olabilir, `session_id` eklendi. ⭐ **`event` tablosuna DOKUNULMADI** — alternatif, elle giriş için sahte olay satırı üretmekti ve reddedildi: `event`'in güvenilir olmasının tek sebebi *"bir okuyucu bir kart okudu"* demesidir. İnsan müdahalesi **türetilmiş katmanda** kalır (§0). |
| 1.9 | 2026-08-10 | **`lesson` tablosu eklendi** (§1.2). Derslik yoklaması "geldi" saymak için bir zaman aralığı istiyor ve bu aralık her yoklamada **elle** giriliyordu — bir dakikalık kayma öğrencileri devamsız gösterebiliyordu. Saatler **yerel saat** olarak (`time`) saklanır; UTC çevrimi `tenant.timezone` ile **sunucuda** yapılır, tarayıcının diliminden değil. `weekday` ISO (1=Pazartesi…7=Pazar), `isoweekday()` ile aynı. Çakışma kontrolü uç noktaları dışlar: 09:00–09:50 ile 09:50–10:40 çakışmaz. Mevcut tabloların hiçbiri değişmedi. |
| 1.7 | 2026-08-10 | **`password_reset` tablosu eklendi, `notify_setting`'e SMTP alanları geldi** (§1.2). Gerekçe: parola yönetimi tamamen yöneticiye bağlıydı — kullanıcı parolasını unutursa yöneticiyi bulmak, yönetici de yeni parolayı **düz metin iletmek** zorundaydı; kullanıcı kendi parolasını hiç değiştiremiyordu. Jetonlar **sha256 ile hash'lenerek** saklanır, tek kullanımlıktır, süreleri vardır ve parola değişince bekleyenler iptal olur. `notify_setting.channel` enum'una `email` eklendi (dördüncü bildirim kanalı). Mevcut tabloların hiçbiri değişmedi. |
| 1.6 | 2026-08-09 | **`notify_setting` tablosu eklendi.** Bildirim kanalı ve SMS sağlayıcı bilgileri `.env` yerine veritabanında: kurum bunları **arayüzden** değiştirebilmeli ("sıfır CLI"). Sağlayıcı kimlik bilgileri **Fernet ile şifreli** (`secret_enc`); şifreleme anahtarı yoksa sır saklanmaz. |
| 1.5 | 2026-08-09 | **`notification`, `wa_thread`, `wa_message` tabloları eklendi.** Veli bildirimi (Faz 8) ve panelden iki yönlü WhatsApp yazışması için. Mevcut tabloların hiçbiri değişmedi. Mahremiyet kuralları §6'da tanımlandı. |
| 1.4 | 2026-08-09 | **`person` tablosuna 5 kayıt alanı eklendi** (§1.2): `grade`, `started_at`, `address`, `title`, `department`. Kurumun gerçek kayıt bilgilerini tutabilmesi için. Veli 2, acil durum kişisi ve koç ataması **yeni kolon gerektirmedi** — `person_guardian` çoka-çok ve `coach_assignment` zaten vardı, yalnızca arayüzleri yoktu. |
| 1.3 | 2026-08-09 | **§4 hat sırası düzeltildi.** Adım listesi çift okutma kontrolünü `event INSERT`'ten sonra gösteriyordu, ama §4.1 sözde kodu orada `decision = "duplicate"` atıyordu — `event` değişmez olduğu için yazıldıktan sonra karar değiştirilemez. Kontrol INSERT öncesine alındı. **Veri modeli ve payload şeması değişmedi**, yalnızca adım sırası netleşti. Faz 7 uygulamasında tespit edildi. |
| 1.2 | 2026-08-09 | **`hb.rdr` ve `hb.rdr_reinit` alanları eklendi** (§2.4). Sahada RC522'nin sessizce askıda kaldığı görüldü: WiFi/MQTT/heartbeat çalışmaya devam ederken okuyucu hiçbir kart algılamıyordu ve panel düğümü `online` gösteriyordu. Düğüm sağlığı artık okuyucunun durumunu da taşıyor. Şema sürümü `v` **1'de kaldı**. |
| 1.1 | 2026-08-08 | **`event.up_tx` alanı eklendi** (§2.2). §2.3'teki `effective_ts` formülü `uptime_at_flush` değerine ihtiyaç duyuyordu ama payload şemasında bu değeri taşıyan alan yoktu — formül hesaplanamıyordu. Faz 3 firmware yazımında tespit edildi, kullanıcı onayıyla eklendi. Şema sürümü `v` **1'de kaldı** (alan eklemek geriye dönük uyumludur; eski alanların hiçbiri değişmedi). |
| 1.0 | — | İlk teslim |

---

## 0. Tasarım İlkeleri

| İlke | Karar | Gerekçe |
|---|---|---|
| **Olaylar değişmez** | `event` tablosuna yazılan hiçbir satır güncellenmez/silinmez | Denetim izi, KVKK, veri bütünlüğü |
| **Oturumlar türetilir** | `attendance_session`, olaylardan hesaplanır ve düzeltilebilir | Unutulan çıkışlar ham veriyi bozmadan düzeltilir |
| **Kimlik soyut** | Backend `credential` görür, "parmak izi" veya "kart" bilmez | RFID ↔ biyometrik geçişi kod değişikliği gerektirmez |
| **Idempotent alım** | `(node_id, seq)` benzersiz | Offline buffer tekrar gönderirse çift kayıt olmaz |
| **Tenant izolasyonu** | Her tabloda `tenant_id` | Çok kurumlu satış sonradan yeniden yazım gerektirmez |

---

## 1. Veri Modeli (PostgreSQL 16)

### 1.1 Şema Diyagramı

```
tenant
 ├── person ──┬── credential
 │            ├── person_guardian ── guardian
 │            └── attendance_session
 ├── zone ────── node
 └── event ───── (person, node, credential)

app_user (login) ── coach_assignment ── person
```

### 1.2 Tablolar

#### `tenant` — Kurum

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `name` | text | "Örnek Eğitim Kurumu" |
| `slug` | text UNIQUE | MQTT topic'te kullanılır, `[a-z0-9-]` |
| `timezone` | text | varsayılan `Europe/Istanbul` |
| `created_at` | timestamptz | |

---

#### `person` — Kişi (öğrenci / personel / koç)

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `full_name` | text | |
| `person_type` | enum | `student` \| `staff` \| `coach` |
| `birth_date` | date NULL | **<18 bildirim mantığı buna bakar** |
| `external_ref` | text NULL | Kurumun kendi öğrenci no'su |
| `phone` | text NULL | |
| `email` | text NULL | |
| `status` | enum | `active` \| `passive` |
| `created_at` / `updated_at` | timestamptz | |

**Kayıt alanları** *(v1.4)*

| Alan | Tip | Not |
|---|---|---|
| `grade` | text NULL | Öğrenci sınıf/seviye — "11-A", "Mezun" |
| `started_at` | date NULL | **Kuruma katılma tarihi.** Öğrencide kayıt, personelde işe başlama. Tek kolon: ikisi aynı anlamda ve birbirini dışlıyor, ayrı kolon gereksiz olurdu. Arayüz etiketi `person_type`'a göre değişir. |
| `address` | text NULL | ⚠️ Kişisel veri — kurumun aydınlatma metninde yer almalı |
| `title` | text NULL | Personel görev/unvan |
| `department` | text NULL | Personel departman |

**Veri minimizasyonu:** TC kimlik no **saklanmaz.** Kurum eşleştirme isterse `external_ref` kullanılır.

> **Veli 2 / acil durum kişisi / koç ataması için yeni kolon YOKTUR.**
> `person_guardian` çoka-çok olduğu için bir öğrenciye istenen sayıda veli
> bağlanır; acil durum kişisi `relation = 'acil_durum'` ile aynı tabloda
> tutulur. Koç ataması `coach_assignment` tablosundadır.

**Türetilen alan (kolon değil, sorgu):**
```sql
is_minor := (birth_date IS NOT NULL AND age(birth_date) < interval '18 years')
```

---

#### `guardian` — Veli

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `full_name` | text | |
| `phone` | text | Bildirim kanalı |
| `email` | text NULL | |

#### `person_guardian` — Öğrenci ↔ Veli (çoka-çok)

| Alan | Tip | Not |
|---|---|---|
| `person_id` | uuid FK | |
| `guardian_id` | uuid FK | |
| `relation` | text | `anne` \| `baba` \| `vasi` |
| `is_primary` | bool | |
| `notify_enabled` | bool | Veli bazında bildirim aç/kapa |
| | PK(`person_id`,`guardian_id`) | |

> Çoka-çok, çünkü bir velinin 2 çocuğu, bir öğrencinin 2 velisi olabilir.

---

#### `credential` — Kimlik Aracı

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `person_id` | uuid FK | |
| `type` | enum | `rfid` \| `fingerprint` |
| `identifier` | text | RFID: UID hex (`04A2B3C4`) · Biyometrik: template ref |
| `label` | text NULL | "Mavi kart", "Sağ işaret parmağı" |
| `status` | enum | `active` \| `lost` \| `revoked` |
| `issued_at` / `revoked_at` | timestamptz | |

```sql
UNIQUE (tenant_id, type, identifier)  -- bir kart iki kişide olamaz
```

**Çok-credential desteği:** Bir kişinin hem kartı hem parmak izi olabilir; kart kaybolursa `lost` işaretlenir, yenisi eklenir. Geçmiş olaylar bozulmaz.

---

#### `zone` — Mekân

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `name` | text | "Ana Giriş", "Kütüphane", "Derslik A" |
| `kind` | enum | `entrance` \| `library` \| `classroom` |
| `parent_zone_id` | uuid NULL | Hiyerarşi (bina → kat → derslik) |
| `auto_close_at` | time NULL | Açık oturumların gece kapatılma saati |

---

#### `node` — Okuyucu Cihaz

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `zone_id` | uuid FK | |
| `node_key` | text UNIQUE | `giris-01` — MQTT topic ve firmware config |
| `name` | text | "Ana Giriş Turnikesi" |
| `direction` | enum | `in` \| `out` \| `toggle` |
| `reader_type` | enum | `rfid` \| `fingerprint` |
| `firmware_version` | text | |
| `last_seen_at` | timestamptz | Heartbeat'ten güncellenir |
| `status` | enum | `online` \| `offline` \| `disabled` |

> `direction`: Çift okuyuculu kapıda `in`/`out`, tek okuyucuda `toggle`. **Prototip: `toggle`.**

---

#### `event` — Ham Okuma Olayı (DEĞİŞMEZ)

| Alan | Tip | Not |
|---|---|---|
| `id` | bigserial PK | |
| `tenant_id` | uuid FK | |
| `node_id` | uuid FK | |
| `seq` | bigint | Düğüm-yerel sıra no |
| `cred_type` | enum | `rfid` \| `fingerprint` |
| `cred_identifier` | text | **Ham okunan değer** — kayıtlı olmasa bile yazılır |
| `credential_id` | uuid NULL FK | Alım anında çözülür |
| `person_id` | uuid NULL FK | Alım anında çözülür |
| `decision` | enum | `granted` \| `unknown_credential` \| `revoked` \| `duplicate` \| `disabled_node` |
| `device_uptime_ms` | bigint | **Offline zaman hesabı için** |
| `device_ts` | timestamptz NULL | RTC varsa dolu (prototipte NULL) |
| `server_ts` | timestamptz | Sunucuya varış |
| `effective_ts` | timestamptz | **Olayın gerçek zamanı** (aşağıdaki formül) |
| `raw` | jsonb | Ham payload — ileri analiz/debug |

```sql
UNIQUE (node_id, seq)  -- idempotency: buffer replay çift kayıt yapmaz
INDEX (tenant_id, effective_ts DESC)
INDEX (person_id, effective_ts DESC)
```

**`unknown_credential` olayları da yazılır.** Bu bir hata değil, **enrollment akışının yakıtıdır** (§3.4).

---

#### `attendance_session` — Türetilmiş Oturum

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `person_id` | uuid FK | |
| `zone_id` | uuid FK | |
| `entry_event_id` | bigint **NULL** FK | *(v2.0)* Elle açılan oturumda **YOKTUR** — kart okunmadı |
| `exit_event_id` | bigint NULL FK | |
| `entered_at` | timestamptz | |
| `exited_at` | timestamptz NULL | |
| `duration_seconds` | int NULL | Kapanışta hesaplanır |
| `state` | enum | `open` \| `closed` \| `auto_closed` \| `corrected` |
| `corrected_by` | uuid NULL | Düzeltme yapan kullanıcı |
| `note` | text NULL | |
| `entry_source` | text | *(v2.0)* `card` \| `manual` — kayıt nereden doğdu |
| `created_by` | uuid NULL FK | *(v2.0)* Elle açan kullanıcı |

```sql
-- Bir kişi aynı mekânda aynı anda tek açık oturuma sahip olabilir
CREATE UNIQUE INDEX ON attendance_session (person_id, zone_id) WHERE state = 'open';

-- v2.0 — kaynak ile olay tutarlı olmak ZORUNDA
CHECK (entry_source IN ('card','manual'))
CHECK ((entry_source = 'card'   AND entry_event_id IS NOT NULL) OR
       (entry_source = 'manual' AND entry_event_id IS NULL))
CHECK (entry_source <> 'manual' OR created_by IS NOT NULL)
```

> **Elle giriş neden `event` üretmez.** Sahte olay satırı üretmek de
> mümkündü; reddedildi. `event`'in denetim değeri, her satırının
> *"bir okuyucu bir kart okudu"* demesinden geliyor. İçine insan eliyle
> yazılan kayıtlar karıştığında o güvence kaybolur.
>
> Bu yol §0 ile uyumlu: **olaylar değişmez, oturumlar türetilir.** İnsan
> müdahalesi her zaman türetilmiş katmanda kalır — `corrected_by`
> mekanizmasının kardeşi.
>
> Sonuç: elle giriş **ham olay akışında görünmez** (doğrusu da bu, kart
> okunmadı) ama **yoklamada, raporda ve "şu an içeride" listesinde
> görünür.**
>
> Kayıt **kim tarafından** açıldığı `created_by` ile zorunlu tutulur:
> kartsız kayıt açmak kötüye kullanılabilir bir yetkidir, izsiz bırakılamaz.

---

#### `app_user` — Sisteme Giriş Yapan Kullanıcı

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | |
| `person_id` | uuid NULL FK | Koç hem `person` hem `app_user` olabilir |
| `email` | text UNIQUE | |
| `password_hash` | text | **argon2id** |
| `role` | enum | `super_admin` \| `kurum_admin` \| `operator` \| `coach` |
| `is_active` | bool | |
| `last_login_at` | timestamptz | |

#### `password_reset` — Parola Sıfırlama / Davet Jetonu *(v1.7)*

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK → `app_user` | `ON DELETE CASCADE` |
| `token_hash` | text UNIQUE | **sha256(token)** — düz metin jeton ASLA saklanmaz |
| `purpose` | enum | `reset` \| `invite` |
| `expires_at` | timestamptz | `reset` 1 saat, `invite` 72 saat |
| `used_at` | timestamptz NULL | dolduysa jeton tüketilmiştir |
| `created_at` | timestamptz | |

**Neden hash?** Veritabanını okuyabilen biri (yedek dosyası, sızıntı, DBA)
düz metin jetonla herkesin hesabını ele geçirebilirdi. Jeton yalnızca
e-postada var; sistem onu bir daha göremez.

**Tek kullanımlık ve süreli.** Kullanılan jeton `used_at` ile kapanır.
Parola değiştiği anda o kullanıcının **bekleyen tüm jetonları iptal edilir** —
aksi hâlde eski bir sıfırlama e-postasına erişen biri parolayı geri alabilirdi.

**Kullanıcı sayımı sızdırılmaz.** `POST /auth/forgot` e-posta kayıtlı olsun
olmasın **daima 204** döner. Aksi hâlde uç, kurumun kullanıcı listesini
çıkarmak için kullanılırdı.

**Hız sınırı:** kullanıcı başına dakikada bir jeton. Yoksa uç, birinin gelen
kutusunu bombalamak için kullanılabilir.

#### `coach_assignment` — Koç ↔ Öğrenci

| Alan | Tip |
|---|---|
| `coach_person_id` | uuid FK |
| `student_person_id` | uuid FK |
| PK(ikisi) | |

> Koç **yalnızca** kendisine atanmış öğrencileri görür. Yetki sorgusu bu tablodan geçer.

---

#### `notification` — Veli Bildirimi *(v1.5)*

| Alan | Tip | Not |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` / `person_id` / `guardian_id` | uuid FK | Kime |
| `event_id` | bigint **NULL** FK | *(v2.0)* Kart okumasından doğduysa |
| `session_id` | uuid **NULL** FK | *(v2.0)* Elle açılan oturumdan doğduysa |
| `channel` | enum | `whatsapp` \| `sms` \| `email` \| `dryrun` |
| `direction` | text NULL | *(v2.1)* `GİRİŞ` \| `ÇIKIŞ` — oturum kaynaklı bildirimlerde **benzersizlik anahtarının parçası** |
| `recipient` | text | **Gönderim anındaki numara** — veli sonradan değiştirse de kayıt bozulmaz |
| `body` | text | Gönderilen metin |
| `status` | enum | `pending` \| `sent` \| `failed` \| `skipped` |
| `attempts` / `last_error` / `scheduled_at` / `sent_at` | | Yeniden deneme durumu |

```sql
-- v2.0: kaynak İKİSİNDEN TAM BİRİ olmalı
CHECK ((event_id IS NOT NULL AND session_id IS NULL) OR
       (event_id IS NULL AND session_id IS NOT NULL))

-- v2.0: mükerrer engeli iki KISMİ indekse bölündü
CREATE UNIQUE INDEX notification_once_event
    ON notification (event_id, guardian_id)   WHERE event_id   IS NOT NULL;
-- v2.1: yön anahtara girdi (bir oturum İKİ bildirim üretir)
CREATE UNIQUE INDEX notification_once_session
    ON notification (session_id, guardian_id, direction)
    WHERE session_id IS NOT NULL;
```

> Mükerrer engeli uygulamaya değil **veritabanına** yaptırıldı. İşçi çökse,
> yeniden başlasa, iki kopya aynı anda çalışsa bile veli tek mesaj alır.
> `UNIQUE(node_id, seq)` ile aynı felsefe.
>
> ⚠️ **v2.0'da neden kısmi indeks:** eski `UNIQUE(event_id, guardian_id)`
> kısıtı, `event_id` NULL olabilir hâle gelince işlevini kaybediyordu —
> PostgreSQL'de NULL değerler benzersizlik kontrolüne **girmez**, dolayısıyla
> aynı oturum için **sınırsız** bildirim üretilebilirdi. Faz 8'de özenle
> kurulan garanti böylece korunuyor.

---

#### `wa_thread` / `wa_message` — WhatsApp Yazışması *(v1.5)*

`wa_thread`: telefon numarası başına tek konuşma.
`guardian_id` **NULL ise numara tanınmıyor** demektir.

| Alan | Tip | Not |
|---|---|---|
| `phone` | text | Normalize edilmiş (yalnızca rakam) — `+90 555…` ve `0555…` aynı konuşmaya düşer |
| `guardian_id` | uuid NULL FK | NULL → bilgi verilmez |
| `needs_attention` | bool | Yönetici müdahalesi bekliyor |

`wa_message`: `direction` (`in`/`out`), `body`, `is_auto`, `sent_by`, `error`.

> `is_auto` **denetim için zorunlu**: hangi bilginin makine tarafından
> verildiği sonradan sorgulanabilmeli.

#### `lesson` — Ders Programı *(v1.9)*

| Alan | Tip | Not |
|---|---|---|
| `zone_id` | uuid FK | derslik (`zone.kind = classroom`) |
| `grade` | text | `person.grade` ile eşleşir — ayrı şube tablosu yok |
| `weekday` | int | **ISO: 1=Pazartesi … 7=Pazar** (`isoweekday()` ile aynı) |
| `starts_at` / `ends_at` | time | **kurumun YEREL saati**, dilim yok |
| `name` | text | "1. Ders", "Matematik" |
| `is_active` | bool | |

**Saat neden yerel?** Ders "her Pazartesi 09:00" diye tanımlanır; UTC olarak
saklamak yaz saati uygulaması değişince programı kaydırırdı. Dilim
`tenant.timezone`'da; UTC çevrimi `GET /lessons/today` içinde **sunucuda**
yapılır. Tarayıcının diliminden hesaplamak, yurt dışından ya da saati yanlış
ayarlı bir cihazdan bakan yöneticide yanlış aralık üretirdi.

**Çakışma kuralı:** aynı derslik + sınıf + gün içinde
`yeni.başlangıç < var.bitiş AND yeni.bitiş > var.başlangıç`.
Uç noktalar **dışlanır** — arka arkaya dersler (09:00–09:50, 09:50–10:40)
çakışma sayılmaz. Farklı sınıf ya da farklı derslik aynı saatte olabilir.

Kısıtlar: `weekday BETWEEN 1 AND 7`, `ends_at > starts_at` (gece yarısını
aşan ders yok; olsaydı iki satıra bölünmeli).

#### `notify_setting` — Bildirim Yapılandırması *(v1.6, SMTP v1.7)*

Kurum başına tek satır. Kanal ve sağlayıcı bilgileri `.env`'de değil burada,
çünkü kurum bunları **arayüzden** değiştirebilmeli ("sıfır CLI").

| Alan | Tip | Not |
|---|---|---|
| `tenant_id` | uuid FK UNIQUE | kurum başına tek satır |
| `channel` | text | `dryrun` \| `whatsapp` \| `sms` \| `email` *(v1.7)* |
| `sms_provider` | text NULL | ön tanımlı sağlayıcı anahtarı |
| `sms_config` | jsonb | sağlayıcı uçları, gövde şablonu |
| `secret_enc` | bytea NULL | **Fernet** — SMS sağlayıcı sırrı |
| `smtp_host` | text NULL | *(v1.7)* |
| `smtp_port` | int NULL | *(v1.7)* 587 (STARTTLS) \| 465 (SSL) \| 25 |
| `smtp_security` | text NULL | *(v1.7)* `starttls` \| `ssl` \| `none` |
| `smtp_from` | text NULL | *(v1.7)* gönderen adresi |
| `smtp_user` | text NULL | *(v1.7)* boşsa kimlik doğrulama yapılmaz |
| `smtp_secret_enc` | bytea NULL | *(v1.7)* **Fernet** — SMTP parolası |

**Sırlar için ayrı sütun.** SMS sırrı ve SMTP parolası tek alanda tutulsaydı
birini değiştirmek diğerini silerdi.

**Şifreleme anahtarı yoksa sır SAKLANMAZ.** `settings_store` düz metne
düşmez, hata verir — yanlışlıkla açık kaydetmektense kaydetmemek yeğdir.

---

### 1.3 Rol Yetki Matrisi

| Kaynak | super_admin | kurum_admin | operator | coach |
|---|:---:|:---:|:---:|:---:|
| Kurum yönetimi | ✅ | ❌ | ❌ | ❌ |
| Kişi CRUD | ✅ | ✅ | ✅ okuma+ekleme | ❌ |
| Credential atama | ✅ | ✅ | ✅ | ❌ |
| Düğüm/mekân config | ✅ | ✅ | ❌ | ❌ |
| Tüm olaylar | ✅ | ✅ | ✅ | ❌ |
| Kendi öğrencisinin oturumları | ✅ | ✅ | ✅ | ✅ |
| Oturum düzeltme | ✅ | ✅ | ❌ | ❌ |
| Veli bildirim ayarı | ✅ | ✅ | ❌ | ❌ |

---

## 2. Olay Şeması (MQTT)

### 2.1 Topic Yapısı

```
nobet/v1/{tenant_slug}/{node_key}/event     ← düğüm → sunucu  (QoS 1)
nobet/v1/{tenant_slug}/{node_key}/hb        ← düğüm → sunucu  (QoS 0, 30sn)
nobet/v1/{tenant_slug}/{node_key}/status    ← LWT             (QoS 1, retained)
nobet/v1/{tenant_slug}/{node_key}/cmd       → sunucu → düğüm  (QoS 1)
```

### 2.2 `event` — Okuma Bildirimi

```json
{
  "v": 1,
  "node": "giris-01",
  "seq": 1042,
  "cred": { "t": "rfid", "id": "04A2B3C4" },
  "up": 3821044,
  "up_tx": 3825100,
  "ts": null,
  "buf": 0
}
```

| Alan | Tip | Açıklama |
|---|---|---|
| `v` | int | Şema sürümü |
| `node` | string | `node_key` |
| `seq` | int | **NVS'de kalıcı**, reboot'ta sıfırlanmaz |
| `cred.t` | string | `rfid` \| `fp` |
| `cred.id` | string | UID hex (büyük harf, ayraçsız) |
| `up` | int | **Okuma anındaki** uptime (ms) |
| `up_tx` | int | **Yayın anındaki** uptime (ms) — §2.3 formülünün `uptime_at_flush` değeri. Canlı olayda `up`'a yakındır; buffer'dan gönderimde aradaki fark olayın yaşıdır. *(v1.1'de eklendi)* |
| `ts` | string\|null | ISO8601 — RTC varsa, prototipte `null` |
| `buf` | int | `0` = canlı, `1` = offline buffer'dan |

> **Not:** `seq` kesintisiz artmaz. Düğüm NVS aşınmasını azaltmak için sayacı
> bloklar hâlinde rezerve eder; reboot sonrası sayaç ileri sıçrar ve
> numaralarda boşluk oluşur. Kontrat yalnızca **benzersizlik** garanti eder
> (`UNIQUE(node_id, seq)`), süreklilik değil. Sunucu boşlukları veri kaybı
> olarak yorumlamamalıdır.

### 2.3 ⭐ Zaman Damgası Çözümü (RTC'siz)

Prototipte düğümde RTC yok. Offline buffer'daki olayların doğru zamanı **uptime farkından** hesaplanır:

```
effective_ts = server_ts - (up_tx - up)
```

Düğüm her mesajda yayın anındaki uptime'ı (`up_tx`) da taşır; sunucu iki uptime'ın farkını alarak olayın yaşını bulur ve kendi saatinden geriye gider. Saatlerce süren kesintide sapma birkaç saniyedir — yoklama için fazlasıyla yeterli.

> `up_tx - up` = olayın yaşı (ms). Bu fark yalnızca düğümün kendi saatinden
> hesaplandığı için sunucu ile düğüm arasında saat senkronizasyonu gerekmez.

```
ts != null           →  effective_ts = ts              (RTC güvenilir)
ts == null, buf == 0 →  effective_ts = server_ts       (canlı, gecikme ~ms)
ts == null, buf == 1 →  effective_ts = formül          (offline telafi)
```

> **Sonuç:** DS3231 prototipte gereksiz, v1'de opsiyonel iyileştirme.

### 2.4 `hb` — Heartbeat (30 sn)

```json
{ "v":1, "node":"giris-01", "up":3821044, "rssi":-62,
  "heap":184320, "buf_len":0, "fw":"0.1.0",
  "rdr":"ok", "rdr_reinit":0 }
```

| Alan | Tip | Açıklama |
|---|---|---|
| `up` | int | Uptime (ms) |
| `rssi` | int | WiFi sinyal gücü (dBm) |
| `heap` | int | Boştaki bellek (bayt) — sızıntı takibi |
| `buf_len` | int | Gönderilmemiş olay sayısı |
| `fw` | string | Firmware sürümü |
| `rdr` | string | `ok` \| `fail` — okuyucunun **o anki** durumu *(v1.2)* |
| `rdr_reinit` | int | Açılıştan beri okuyucunun kaç kez yeniden başlatıldığı *(v1.2)* |

> **⚠️ `rdr` neden gerekli:** RC522 askıda kalabiliyor — SPI cevap vermeye
> devam ederken RF alanı sessizce kapanıyor. Bu durumda düğüm ağa bağlı,
> heartbeat düzenli, panel `online`, ama **hiçbir kart okunmuyor.** Yoklama
> verisi sessizce eksik kalır. `rdr` bu sessiz arızayı görünür kılar.
>
> `rdr_reinit` sıfırdan büyükse okuyucu kendini toparlamış demektir; sürekli
> artıyorsa donanım arızası vardır (kablo, besleme, kart).

### 2.5 `status` — LWT (retained)

```json
{ "v":1, "node":"giris-01", "state":"offline" }
```
Bağlanınca `online` yayınlanır. Admin panelindeki cihaz sağlığı bunu okur.

### 2.6 `cmd` — Sunucu Yanıtı

```json
{ "v":1, "ack":1042, "result":"granted",
  "display":"Ayşe Y. · GİRİŞ", "feedback":"ok", "relay_ms":0 }
```

| `result` | LED | Buzzer |
|---|---|---|
| `granted` | Yeşil 1sn | 1× kısa bip |
| `unknown_credential` | Sarı 1sn | 2× bip |
| `revoked` | Kırmızı 2sn | 3× uzun bip |
| `duplicate` | Mavi 0.5sn | sessiz |

> `relay_ms > 0` → kuru kontak röle tetiklenir. **Prototipte daima `0`.**
> `ack` alınmayan olay buffer'da kalır, tekrar gönderilir → `UNIQUE(node_id,seq)` çift kaydı engeller.

---

## 3. API Kontratı

**Base:** `/api/v1` · **Auth:** `Authorization: Bearer <JWT>` · **Format:** JSON

### 3.1 Kimlik Doğrulama

```
POST   /auth/login          {email, password} → {access_token, refresh_token, user}
POST   /auth/refresh        {refresh_token}
POST   /auth/logout
GET    /me                  → {id, role, person, tenant}
```

**Parola akışları** *(v1.7)*

```
POST   /auth/forgot         {email}                    → 204 DAİMA
GET    /auth/reset/{token}  → {valid, email, purpose}
POST   /auth/reset          {token, password}          → 204
POST   /auth/change-password {current_password, new_password} → 204
```

| Kural | Gerekçe |
|---|---|
| `/auth/forgot` **daima 204** | Farklı cevap, ucu kullanıcı listesi çıkarmak için kullanılabilir hâle getirir |
| Geçersiz/süresi geçmiş/kullanılmış jeton → **aynı hata** | Ayrıştırmak hangi jetonların var olduğunu sızdırır |
| `valid=false` iken `email=null` | Geçersiz jetonla hedef hesap sızdırılmaz |
| `change-password` mevcut parolayı sorar | Açık bırakılmış bir tarayıcı hesabı devralamasın |
| Parola değişince **bekleyen tüm jetonlar iptal** | Eski bir e-postadaki jeton yeni parolanın üzerine yazamasın |

**Kullanıcı yönetimi** *(v1.7 — yönetici)*

```
GET    /users
POST   /users               {email, password?, role, person_id?}
POST   /users/{id}/invite   → parola belirleme bağlantısı gönderir
POST   /users/{id}/password {password}
PATCH  /users/{id}          {email?, role?, is_active?, person_id?}
DELETE /users/{id}          → yumuşak silme (is_active=false)
```

`password` boş bırakılırsa hesap **davet kipinde** açılır: giriş yapılamayan
rastgele bir hash konur ve kullanıcıya parola belirleme bağlantısı gider.
Yöneticinin parolayı bilmesi ve düz metin iletmesi gerekmez.

**Kilitlenme korumaları:** kimse kendi hesabını pasife alamaz / rolünü
düşüremez; `kurum_admin` `super_admin` üretemez.

**SMTP ayarları** *(v1.7 — yönetici)*

```
PUT    /settings/smtp        {host, port, security, from_addr, user?, password?}
GET    /settings/smtp/check  → bağlanır ve kimlik doğrular, MESAJ GÖNDERMEZ
POST   /settings/smtp/test   {to} → gerçek test e-postası
```

`password` boş bırakılırsa kayıtlı parola **korunur** — arayüz sırrı hiç
görmediği için her kaydetmede yeniden yazmak zorunda kalınmamalı.

### 3.2 Kişi Yönetimi

```
GET    /persons             ?type=&status=&q=&page=&size=
POST   /persons
GET    /persons/{id}        → kişi + credentials + guardians + son 10 olay
PATCH  /persons/{id}
DELETE /persons/{id}        (soft delete → status=passive)

GET    /persons/{id}/guardians
POST   /persons/{id}/guardians
DELETE /persons/{id}/guardians/{guardian_id}
```

### 3.3 Credential Yönetimi

```
GET    /persons/{id}/credentials
POST   /credentials         {person_id, type, identifier, label}
PATCH  /credentials/{id}    {status}         # kayıp bildirimi
DELETE /credentials/{id}
```

### 3.4 ⭐ Enrollment Akışı (Sıfır CLI)

Kurumun kart kaydını **teknik bilgi olmadan** yapabilmesi için:

```
GET    /enroll/pending      ?window=60
       → son 60sn'deki `unknown_credential` olayları
       [{event_id, cred_type, cred_identifier, node_name, seen_at}]

POST   /enroll/claim        {event_id, person_id, label}
       → credential oluşturur + o olayı geriye dönük ilişkilendirir
```

**Kullanıcı deneyimi:**
```
1. Operatör "Kart Ata" der, öğrenciyi seçer
2. Ekran: "Kartı okutucuya okutun..."   (SSE ile bekler)
3. Öğrenci kartı okutur → ekranda UID belirir
4. Operatör onaylar → kayıt tamam
```

### 3.5 Düğüm & Mekân

```
GET    /nodes               → + last_seen_at, status, rssi
POST   /nodes               {node_key, zone_id, name, direction, reader_type}
PATCH  /nodes/{id}
GET    /nodes/{id}/health   → uptime, heap, buffer, son 24s olay sayısı

GET    /zones
POST   /zones
PATCH  /zones/{id}
```

**Ders programı** *(v1.9)*

```
GET    /lessons?zone_id=&grade=&weekday=    → tüm program
GET    /lessons/today?zone_id=&grade=       → bugünküler, saatler UTC'ye çevrilmiş
POST   /lessons          {zone_id, grade, weekday, starts_at, ends_at, name}
PATCH  /lessons/{id}
DELETE /lessons/{id}
```

`/lessons/today` her satıra `starts_at_utc`, `ends_at_utc` ve `is_current`
ekler. Yoklama ekranı bunları doğrudan kullanır; süren dersi ön seçili
getirir, operatör hiçbir saat yazmaz.

**Yetki:** okuma `CurrentUser` (operatör yoklama alacak), yazma `AdminUser`
(program bir yapılandırma kararıdır).

### 3.6 Olaylar & Oturumlar

```
GET    /events              ?from=&to=&person_id=&node_id=&decision=&page=
GET    /events/stream       → Server-Sent Events (canlı akış)

GET    /sessions            ?person_id=&zone_id=&from=&to=&state=
GET    /sessions/open       → şu an içeride olanlar
PATCH  /sessions/{id}       {exited_at, note}   # düzeltme (Faz 7)
```

### 3.7 Dashboard

```
GET    /dashboard/summary
{
  "inside_now":        { "student": 42, "staff": 8 },
  "today_events":      317,
  "nodes":             { "online": 3, "offline": 0 },
  "open_sessions":     50,
  "unknown_reads_24h": 4
}
```

---

## 4. Alım Hattı (Ingest Pipeline)

```
MQTT mesajı
   ↓ şema doğrulama (v==1, zorunlu alanlar)
   ↓ node_key → node_id çözümle   (bilinmeyen düğüm → reddet + logla)
   ↓ dedup: (node_id, seq) var mı? → varsa ack tekrarla, çık
   ↓ credential çözümle → person_id, decision
   ↓ effective_ts hesapla (§2.3)
   ↓ ⭐ çift okutma kontrolü → decision `duplicate` olabilir (§4.1)
   ↓ event INSERT  (değişmez — karar bu noktada KESİNLEŞMİŞTİR)
   ↓ session engine (§4.1) — yalnızca `granted` için oturum açar/kapatır
   ↓ cmd publish   (ack + geri bildirim)
   ↓ SSE broadcast (canlı arayüz)
```

> **⚠️ Çift okutma kontrolü neden INSERT'ten ÖNCE** *(v1.3'te düzeltildi)*
>
> `event` değişmezdir; yazıldıktan sonra `decision` alanı değiştirilemez
> (veritabanı trigger'ı UPDATE'i reddeder). Bu yüzden `duplicate` kararı
> satır yazılmadan önce verilmek zorundadır. Oturum motoru INSERT'ten sonra
> çalışır ama artık yalnızca oturum açar/kapatır, karar üretmez.

### 4.1 Oturum Motoru — `toggle` Mantığı

**Adım A — çift okutma kontrolü (event INSERT'ten ÖNCE):**
```python
# Turnikeye yaslanma koruması. AYNI MEKÂNDAKİ son granted okumaya bakılır,
# aynı düğüme değil: çift okuyuculu kapıda kişi önce giriş sonra çıkış
# okuyucusuna yaslanabilir, ikisi de aynı mekâna aittir.
if decision == "granted" and son_granted_olay(person, zone) < 10 saniye önce:
    decision = "duplicate"
```

**Adım B — oturum motoru (event INSERT'ten SONRA):**
```python
if decision != "granted":
    return  # oturum oluşturma

acik = acik_oturum_bul(person_id, zone_id)

if acik:
    acik.exited_at       = effective_ts
    acik.exit_event_id   = event.id
    acik.duration_seconds = exited_at - entered_at
    acik.state           = "closed"
    yon = "ÇIKIŞ"
else:
    yeni_oturum(person_id, zone_id, entered_at=effective_ts, state="open")
    yon = "GİRİŞ"
```

**Gece kapatma (v1, Faz 7):** `zone.auto_close_at` saatinde açık oturumlar `auto_closed` durumuna alınır, süre hesabına **dahil edilmez**, koç panelinde "eksik çıkış" olarak işaretlenir.

---

## 5. Bilinen Sınırlar (Prototip)

| Sınır | Etki | Çözüm fazı |
|---|---|---|
| Mifare Classic UID klonlanabilir | Vekâleten yoklama mümkün | Faz 11 → DESFire EV2 |
| Unutulan çıkış okutması | Oturum açık kalır | Faz 7 |
| MQTT TLS yok (prototip) | Yerel ağda düz trafik | Faz 11 |
| Tek Pi, tek SSD | Tek nokta arıza | Faz 11 (UPS + yedek) |
| Bildirim yok | Veli bilgilenmiyor | Faz 8 |

---

## 5.1 ⭐ Bildirim ve Yazışma Mahremiyeti *(v1.5)*

Sistem, **reşit olmayan bir çocuğun nerede olduğu** bilgisini dışarı veriyor.
Aşağıdaki kurallar isteğe bağlı değildir; kodda zorlanır.

| # | Kural |
|---|---|
| 1 | Gelen mesaja **yalnızca kayıtlı veli numarasından** geliyorsa bilgi verilir |
| 2 | **Yalnızca o veliye bağlı öğrenciler** hakkında bilgi verilir |
| 3 | Tanınmayan numara **hiçbir bilgi almaz** — yöneticiye yükseltilir |
| 4 | Mesajda başka bir isim geçse bile o kişi hakkında bilgi verilmez |
| 5 | Her otomatik yanıt `wa_message.is_auto` ile kayda geçer |
| 6 | Otomatik yanıtlayıcı **dar** tutulur; anlaşılmayan her şey yöneticiye gider |

**Çıkış okutulmamışsa uydurma saat verilmez.** "Çıkış okutulmamış, son giriş
şu saatte" denir. Tahmin edilen bir saat, veliyi yanlış yönlendirir.

**Ağ geçidi webhook'u paylaşılan sır ile doğrulanır.** Bu uç korumasız
kalırsa sahte "veli mesajı" uydurularak öğrenci konumu sızdırılabilir.

---

## 6. Onay Kontrol Listesi

- [ ] Tablo yapısı ve alanlar
- [ ] `event` değişmez + `session` türetilmiş yaklaşımı
- [ ] MQTT topic yapısı ve payload şeması
- [ ] Uptime tabanlı zaman damgası çözümü (§2.3)
- [ ] Enrollment akışı (§3.4)
- [ ] Rol yetki matrisi (§1.3)
- [ ] API endpoint listesi

**Onay sonrası:** Faz 3 (firmware) ve Faz 4–5 (Pi çekirdek + backend) paralel yazılabilir.
