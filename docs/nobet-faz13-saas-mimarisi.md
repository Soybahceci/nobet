# NÖBET — Faz 13: SaaS Mimarisi

**Sürüm:** 1.0 · **Tarih:** 2026-08-10 · **Durum:** onay bekliyor

> Bu doküman **dağıtım mimarisini** tanımlar. Veri modeli ve MQTT şeması hâlâ
> `nobet-faz1-sistem-sozlesmesi.md`'nin sorumluluğunda; buradaki yeni tablolar
> oraya da işlenir.

---

## 0. Karar

NÖBET **aylık abonelikli SaaS** olarak satılacak. Kurumlar merkezî bir bulut
kurulumuna bağlanır; okuyucular kurumun duvarında kalır.

Bu, tek kurumlu on-prem modelin tersi bir karardır. Gerekçesi ticari
(abonelik geliri, merkezî güncelleme, veli panelinin herkese açık olması).
Teknik maliyeti bu dokümanda açıkça sayılmıştır.

---

## 1. Katmanlar

```
  KURUM (her biri için ayrı)              BULUT (tek kurulum)
  ─────────────────────────               ───────────────────
  ESP32 okuyucular                        PostgreSQL
     │ MQTT (yerel ağ, TLS yok)           FastAPI + web paneli
     ↓                                    Veli / öğrenci PWA
  Raspberry Pi 3B — KENAR                 Abonelik & kota
     • Mosquitto                          Koçluk içeriği
     • kart kopyası (SQLite)              Raporlar
     • olay kuyruğu (SQLite)                    ↑
     • senkron istemcisi ──────────────────────┘
                          HTTPS (giden bağlantı)
```

**Neden kenar cihazı var?** İnternet kesildiğinde okulun kapısı çalışmaya
devam etmeli. Okuyucular doğrudan buluta bağlansaydı, ESP32'nin 64 olaylık
tamponu sabah yoğunluğunda yarım saatlik bir kesintide taşar ve **veri
kaybolurdu**. Ayrıca kart kararı bulutta verildiği için ışık/buzzer geri
bildirimi susardı.

**Neden okuyucular TLS kullanmıyor?** Kullanmasına gerek yok: MQTT trafiği
kurumun yerel ağından çıkmıyor. TLS yükü bulut bağlantısında, kenar cihazının
HTTPS istemcisinde. ESP32 firmware'i **hiç değişmiyor.**

---

## 2. Kenar cihazı

### 2.1 Sorumluluklar

| # | İş | Neden kenarda |
|---|---|---|
| 1 | Mosquitto | Okuyucular yerel ağdan bağlanır |
| 2 | Kart kopyası (UID → kişi, durum) | Kesintide `granted`/`revoked` kararı doğru verilsin, ışık yalan söylemesin |
| 3 | Dayanıklı olay kuyruğu | Kesintide hiçbir okuma kaybolmasın |
| 4 | Senkron istemcisi | Kuyruğu boşalt, kart kopyasını tazele |

**Kenarda OLMAYAN:** rapor, oturum geçmişi, koçluk içeriği, veli paneli,
kullanıcı hesapları, bildirim gönderimi. Hepsi bulutta.

### 2.2 ⭐ Ack kenardan verilir

Kenar cihazı olayı **diske yazar yazmaz** ESP32'ye `cmd` ack'i gönderir —
bulutu beklemez.

Sonuç: okuyucunun tamponu hiç dolmaz, internet kesintisi okuyucu için
**görünmez** olur. Bu, "tampon taşarsa veri kaybolur" riskini tamamen
ortadan kaldırır ve firmware'de tek satır değişiklik gerektirmez.

### 2.3 Veritabanı: SQLite

Faz 0'da "SQLite kullanılmayacak" kararı vardı; o karar **asıl veritabanı**
içindi ve bulutta aynen geçerli. Kenarda tutulan şey bir veritabanı değil,
**dayanıklı bir kuyruk + küçük bir önbellek**.

Pi 3B'de (1 GB RAM, SD kart) PostgreSQL ~200 MB tabanı hiçbir karşılığı
olmadan yer; eşzamanlılık ve karmaşık sorgu kenarda kullanılmıyor. SQLite
tek dosya, sunucu süreci yok, atomik yazma, SD karta belirgin biçimde az
yazar.

> Güncellenen kural: **bulutta PostgreSQL, kenarda yalnızca kuyruk (SQLite).**

### 2.3b Kenar servisi makineden bağımsız yazılır

Varsayılan donanım **adanmış kutu** (Pi). Ama servis düz **Python + SQLite +
Mosquitto** olarak yazılır; Docker'a ya da Linux'a bağımlı bir tasarım
kullanılmaz. Böylece kurumun girişindeki bilgisayarda da koşabilir.

**Kutu neden varsayılan:**

| Konu | Adanmış kutu | Girişteki PC |
|---|---|---|
| Sürekli açık | ✅ tasarımı gereği | ⚠️ akşam kapatılıyorsa **sabahki okumalar kaybolur** |
| Ortam kontrolü | ✅ her kurumda aynı | ❌ antivirüs, Windows Update, farklı IP, kapatılan pencere |
| Güvenlik | ✅ tek amaçlı | ⚠️ ortak makine; bulut jetonu ve kart okumaları orada durur |
| Destek maliyeti | ✅ Tailscale ile uzaktan, tek tip | ❌ her kurumda farklı makine, farklı hikâye |
| Elektrik | ~2-3 W | ~60-100 W → yılda ~600-800 kWh fark |

**PC seçeneği şu koşullarda savunulabilir:** makine gerçekten 7/24 açık
(güvenlik/DVR bilgisayarı gibi), kilitlenebiliyor ve kurum bunu kabul ediyor.
Karar kurum bazında verilir; kod her iki durumda da aynıdır.

#### ⚠️ Paketleme çelişkisi çözüldü (denetim bulgusu P-7)

Bu bölüm "Docker'a bağımlı bir tasarım kullanılmaz" diyordu ama §10.2
`edge/compose.yml` + `Dockerfile` gösteriyordu. Çelişki görünürdeydi:
**kod** gerçekten bağımsız (düz Python + SQLite + bir MQTT kütüphanesi),
ama **paketleme** yalnızca Docker için tarifliydi.

Windows'lu bir resepsiyon bilgisayarında Docker Desktop ağır bir bağımlılık
ve pratikte kabul ettirilemez (lisans, WSL2, yeniden başlatma, kaynak).

**Karar — iki paketleme, tek kod tabanı:**

| Ortam | Paket | Nasıl çalışır | Güncelleme |
|---|---|---|---|
| Adanmış kutu (**varsayılan**) | Docker Compose | `edge/compose.yml` | `docker compose pull` |
| Windows PC | **PyInstaller ile tek exe + Windows servisi** | açılışta otomatik | exe'nin kendi güncelleyicisi |

Windows tarafında Mosquitto ayrıca kurulur (resmî Windows kurulumu var ve
servis olarak çalışır) — kenar servisi ona bağlanır.

⚠️ **Windows paketi Faz 13a'da YAPILMAZ.** Kutu ile başlanır; exe paketi
gerçek bir kurum talep ettiğinde açılır. Sebep: iki paketleme yolunu
baştan sürdürmek, henüz tek kurumu bile devreye almamışken erken
maliyettir. Kodun bağımsız yazılması bu kapıyı açık tutmaya yeter —
**yapılması gereken tek şey, koda Docker'a özgü varsayım sızdırmamak**
(dosya yolları yapılandırmadan gelir, ağ adresleri sabit değildir,
günlük stdout'a yazılır).

> Not: PC seçeneğinin en büyük riski (sabah geç açılma) §2.6'daki tampon
> büyütmesiyle büyük ölçüde karşılandı.

### 2.6 Okuyucu tamponu 64 → 1000 olay

Kenar cihazı olayı alır almaz ack verdiği için normal işleyişte tampon
neredeyse hiç dolmaz. Bu boyut **kenar cihazı kapalıyken** geçen süre için:
resepsiyon bilgisayarı sabah geç açılırsa ya da kutu yeniden başlarsa hiçbir
okuma kaybolmasın.

Ölçülen maliyet (gerçek derleme, 2026-08-10):

| | Önce | Sonra |
|---|---|---|
| RAM | 52 088 B (%15.9) | 89 528 B (%27.3) |
| Boşta kalan | 275 KB | **238 KB** |

Yuva başına 40 bayt. WiFi yığını için fazlasıyla yer kalıyor.

⚠️ **Tuzak — derlenir ama sessizce bozar:** `obHead`, `obCount` ve `slot`
`uint8_t` idi (en fazla 255). Yalnızca `OUTBOX_SIZE`'ı büyütmek, `obCount ==
OUTBOX_SIZE` koşulunu hiç doğru olmayacak hâle getirir, sayaç 255'te sarar ve
halka tampon bozulur — hata mesajı vermeden, sahada veri kaybettirerek.
Üçü de `uint16_t` yapıldı.

⚠️ **Tampon RAM'de.** ESP32 elektriği keserse boyutu ne olursa olsun kaybolur.
Kabul edilebilir: binanın elektriği giderse okuyucular da çalışmıyor, kimse
kart okutmuyor. Yalnızca okuyucunun kablosu tek başına çekilirse kayıp olur.
Kalıcılık gerekirse NVS'e yazma eklenebilir ama flash aşınması getirir —
şimdilik gereksiz.

### 2.4 Kimlik ve güven

Her kenar cihazının **kendi jetonu** vardır (`edge_device.token_hash`).
Buluta giden her istek bu jetonla imzalanır; bulut olayı **jetonun ait olduğu
kuruma** yazar — istekteki hiçbir alana değil.

⚠️ Bugünkü alım hattı kurumu payload'daki `node` alanından çözüyor. SaaS'ta
bu, bir kurumun düğümünün başka kurumun kaydına olay yazabilmesi demektir.
**Kurum, yalnızca jetondan belirlenir.**

### 2.5 Uzaktan yönetim

Kenar cihazları Tailscale ile tailnet'e katılır (2026-08-10'da Pi'de
doğrulandı). Kurumun modeminde port açılmaz, ayar yapılmaz.

---

## 3. Senkronizasyon

### 3.1 Yukarı — olaylar

Kenar → bulut, toplu (batch) ve **idempotent**:

```
POST /edge/events        Authorization: Bearer <edge-token>
{ "events": [ { "node_key", "seq", "cred", "up", "up_tx", "buf", "ts" }, … ] }
→ { "accepted": [seq…], "duplicate": [seq…], "rejected": [{seq, reason}…] }
```

Tekillik zaten şemada: `UNIQUE(node_id, seq)`. Aynı toplu istek iki kez
gitse de çift kayıt oluşmaz — Faz 3'te offline buffer için kurulan aynı
felsefe.

Kuyruktan silme **yalnızca bulut kabul ettikten sonra**. Ağ ortada koparsa
olay kuyrukta kalır ve yeniden gönderilir; tekillik kısıtı fazlalığı yutar.

### 3.1b ⭐ `rejected` — kalıcı ret (denetim bulgusu P-2)

İlk tasarımda yanıtın yalnızca `accepted` ve `duplicate` kovaları vardı.
Üçüncü sonuç eksikti: **bulutun hiçbir zaman kabul edemeyeceği olay.**

Silinmiş bir `node_key`, bozuk kayıt, şema uyuşmazlığı… Kenar bunu kuyruktan
silemez (kural: yalnızca kabul edilince sil), sonsuza kadar yeniden gönderir
ve **arkasındaki bütün olaylar sıkışır.** Klasik zehirli mesaj / baş tıkanması.

En kötüsü sessiz olması: kenar "çalışıyor" görünür, kurum aylarca veri
göndermez, kimse fark etmez.

**Karar:**

| Kova | Kenar ne yapar |
|---|---|
| `accepted` | kuyruktan siler |
| `duplicate` | kuyruktan siler (zaten yazılmış) |
| `rejected` | **ölü mektup tablosuna taşır**, kuyruktan çıkarır, sayacı artırır |

`reason` alanı zorunlu ve makine tarafından okunabilir
(`unknown_node`, `malformed`, `schema_mismatch`, `tenant_mismatch`).

Ölü mektup **sessizce silinmez** — kenarın yerel tablosunda durur ve
heartbeat'te sayısı bildirilir. Bulut panelinde sıfırdan büyükse uyarı
çıkar. Veri kaybı olabilecek tek yer burası; görünmez olmamalı.

> Kural: **kuyruk asla tek bir kayıt yüzünden durmaz.** Tıkanan bir kuyruk,
> kaybedilen tek bir olaydan çok daha pahalıdır.

### 3.2 Aşağı — kart kopyası

```
GET /edge/credentials?since=<versiyon>
→ { "version": 412, "changes": [ { "identifier", "person_id", "full_name", "status" }, … ] }
```

Artımlı: yalnızca değişenler iner. Kart iptal edildiğinde kenar en geç bir
sonraki turda öğrenir; kritik iptallerde bulut anlık tetikleyebilir.

### 3.3 Kesinti davranışı

| Durum | Okuyucu | Kenar | Bulut |
|---|---|---|---|
| Her şey çalışıyor | ✅ | ✅ | ✅ |
| İnternet kopuk | ✅ ışık doğru | ✅ kuyrukta biriktirir | — |
| Kenar cihazı kapalı | ⚠️ 64 olay tamponlar | ❌ | — |
| Elektrik kesik | ❌ | ❌ | — |

---

## 3b. ⭐ Kimlik modeli — tek hesap, çok kurum üyeliği

**Karar: 2026-08-10.** Denetim bulgusu P-1 üzerine alındı.

### Sorun

`app_user.email` **global UNIQUE** ve `/auth/login` kullanıcıyı yalnızca
e-postadan buluyor, kurum sormuyor. Yani bugünkü giriş akışı global
benzersizliğe *bağımlı*. İki sonucu var:

1. Aynı kişi birden fazla kurumda var olamaz — iki dershanede çalışan koç,
   ya da **çocukları iki kurumda olan veli** (13c'de kitlesel durum).
2. **Kurumlar arası sızıntı:** B kurumu, A'da kayıtlı bir e-postayla hesap
   açmaya çalışınca `409 bu e-posta zaten kayıtlı` alıyor — yani o kişinin
   başka bir kurumda bulunduğu ele veriliyor.

### Karar

Kimlik ile üyelik ayrılır:

```
app_user  (KİMLİK — kişi kim)
    id, email UNIQUE, password_hash, password_changed_at, is_active

membership  (ÜYELİK — hangi kurumda, hangi sıfatla)   ← YENİ
    id, user_id → app_user, tenant_id → tenant,
    role, person_id → person, is_active
    UNIQUE (user_id, tenant_id)
```

`tenant_id`, `role`, `person_id` **`app_user`'dan çıkar**, `membership`'e
geçer. Bir kişi bir kurumda **en fazla bir** üyeliğe sahip olur (aynı kurumda
hem koç hem operatör olması gerekirse rol matrisi genişletilir, ikinci üyelik
açılmaz).

### Giriş akışı

```
e-posta + parola
   ├── etkin üyelik 1 tane → doğrudan giriş, token.tid = o kurum
   ├── birden fazla        → "hangi kurum?" ekranı → seçim → token
   └── hiç yok             → 403 "hesabınız hiçbir kuruma bağlı değil"
```

Token'daki `tid` alanı **zaten var** (bkz. `create_access_token`); bugüne
kadar sadece bilgi amaçlıydı, artık **hangi üyelikle çalışıldığını** söyler.

### Uygulama — 101 çağrı yeri nasıl korunuyor

Kodda `user.tenant_id` 83, `user.role` 10, `user.person_id` 8 yerde geçiyor.
Bunları tek tek değiştirmek hem büyük hem hataya açık bir iş olurdu.

Çözüm: `current_user` artık ham `AppUser` değil, **aynı alan adlarını taşıyan
bir oturum nesnesi** (`Principal`) döndürür:

```python
@dataclass
class Principal:
    user: AppUser            # kimlik
    membership: Membership   # aktif üyelik
    # --- eski AppUser arayüzü, olduğu gibi ---
    id, email, is_active     → user'dan
    tenant_id, role, person_id → membership'ten
```

Böylece yetki kapıları (`require_roles`, `StaffUser`, `AdminUser`) ve 101
çağrı yerinin tamamı **değişmeden** çalışır. Gerçek iş `auth.py` (giriş +
kurum seçimi), `users.py` (hesap yerine üyelik yönetimi) ve arayüzde toplanır.

> Bu, güvenlik açısından da doğru olan: **kurum artık kullanıcının
> kendisinden değil, jetondaki üyelikten geliyor.** §2.4'te kenar cihazı için
> konan kural ("kurum yalnızca jetondan belirlenir") burada insan
> kullanıcılara da uygulanmış oluyor.

### Yan kararlar

| Soru | Karar |
|---|---|
| Parola sıfırlama e-postası hangi kurumun SMTP'siyle gider? | Kullanıcının **en eski etkin üyeliğinin** kurumu. Kimlik kuruma değil kişiye ait; jeton da öyle. |
| Parola değişince hangi oturumlar düşer? | **Hepsi, tüm kurumlarda.** `password_changed_at` kimlikte (`app_user`), üyelikte değil. |
| Yönetici, başka kurumdaki üyeliği görebilir mi? | **Hayır.** `/users` yalnızca kendi kurumunun üyeliklerini listeler; kişinin başka kurumda üyeliği olduğu **hiçbir yerde görünmez** (P-1'deki sızıntının kapanması). |
| Var olan e-postaya üyelik eklemek? | Hesap zaten varsa **yeni kimlik açılmaz, üyelik eklenir** ve kullanıcıya mevcut parolasıyla girebileceği bildirilir. Yönetici o kişinin başka kurumda olduğunu öğrenmez — mesaj her iki durumda da aynıdır. |
| Son yönetici koruması | Kurum bazında sayılır (`membership` üzerinden), kimlik bazında değil. |

### Dilim

Bu iş **13a-0** olur — `13a-1` (kenar şeması) öncesine girer, çünkü
`edge_device` ve abonelik tabloları bu modelin üstüne oturacak.

---

## 4. Çok kuruma geçişte kapatılması gereken açıklar

Tek kurumda zararsız, SaaS'ta değil. **Hepsi 2026-08-10'da koddan
doğrulandı.**

| # | Sorun | Bugünkü hâli | Çözüm |
|---|---|---|---|
| 1 | MQTT'de ACL yok | `mosquitto.conf`'ta yalnızca `password_file` | Kenar kendi Mosquitto'sunu çalıştırıyor — sorun **ortadan kalkıyor** |
| 2 | Kurum payload'dan çözülüyor | `handle_event` → `d["node"]` | Kurum **kenar jetonundan** belirlenir (§2.4) |
| 3 | `node_key` global UNIQUE | `node_key text NOT NULL UNIQUE` | `UNIQUE(tenant_id, node_key)` |
| 4 | Gelen mesaj rastgele kuruma | `select(Tenant).limit(1)` | Alıcı numaradan kuruma çözümleme |
| 5 | Tek WhatsApp ağ geçidi | tek konteyner, tek oturum | SaaS'ta **SMS** kullanılacak (karar 2026-08-10); ayarlar zaten kurum başına |
| 6 | Global `.env` ayarları | `admin_whatsapp`, `notify_channel` | `notify_setting`'e taşınır |
| 7 | Kurum oluşturma yok | yalnızca bootstrap | Süper yönetici konsolu |

> **1 numaranın kendiliğinden çözülmesi, kenar cihazı kararının yan
> faydasıdır:** her kurumun Mosquitto'su kendi ağında ve dışarı açık değil.
> Okuyucular birbirinin kurumuna erişemez, çünkü aynı ağda bile değiller.

---

## 5. Abonelik ve kesinti

### 5.1 İlke

**Kurumun kendi kaydı hiçbir aşamada durdurulmaz veya rehin alınmaz.**

SaaS'ta işletmeci *veri işleyen*, kurum *veri sorumlusu* olur. Devam kayıtları
hukuken kuruma aittir. Ödenmemiş fatura yüzünden kayıt tutmayı durdurmak, o
dönemin verisini kalıcı olarak yok eder — faturadan çok daha büyük bir sorun
doğurur. Kesilen şey **hizmet**tir, veri değil.

### 5.2 Kademeler

| Aşama | Bulut paneli | Veli/öğrenci | SMS | Kenar |
|---|---|---|---|---|
| `active` | ✅ | ✅ | ✅ | ✅ |
| `warning` (ödeme gecikti) | ✅ + bandrol | ✅ | ✅ | ✅ |
| `restricted` | salt okunur | ❌ | ❌ | ✅ kayıt sürer |
| `suspended` | ❌ | ❌ | ❌ | ✅ kuyrukta biriktirir |

Ödeme gelince kuyruk buluta akar; hiçbir şey kaybolmaz.

### 5.2b Kuyruğun sınırı (denetim bulgusu P-3)

"Kuyrukta biriktirir" cümlesinin bir üst sınırı olmalı; yoksa askıdaki bir
kurumda SD kart sessizce dolar ve **dolduğu an her şey durur.**

Kaba hesap: 3000 olay/gün × 200 bayt ≈ 0,6 MB/gün → 6 ayda ~110 MB.
SQLite için sorun değil, ama sınırsız da değil.

| Eşik | Davranış |
|---|---|
| 100 bin olay | kenar heartbeat'te **uyarı** bildirir, panelde görünür |
| 500 bin olay | uyarı **kritik**e çıkar; işletmeciye bildirim |
| Disk %90 dolu | **yazma durur, EN ESKİ olaylar düşürülmez** |

⭐ **En eskiyi düşürmek yerine yazmayı durdurma kararı.** İkisi de veri
kaybı, ama farkı şu: en eskiyi düşürmek kaybı **sessiz** ve **geçmişe
dönük** yapar (kimsenin bakmadığı eski kayıtlar gider). Yazmayı durdurmak
kaybı **gürültülü** ve **anlık** yapar — okuyucu kırmızı yanar, kapıdaki
görevli hemen fark eder, kurum arar. Sessiz veri kaybı bu sistemde en
kötü sonuçtur; devam kaydı hukuki belge.

> Not: bu eşiklerin hiçbirine askıya alınmış bir kurumda **normal şartlarda
> ulaşılmaz** — 500 bin olay ~1,5 yıl demek. Eşikler bir hatanın (senkron
> hiç çalışmıyor) belirtisi olarak da iş görür.

**SMS ilk kesilir** çünkü işletmecinin cebinden çıkar. Kurum, parasını verdiği
şeyleri (veli uygulaması, raporlar, bildirim) kaybeder — kaldıraç budur.

Fiziksel kilit yok (`relay_ms: 0`, Faz 0 kararı), dolayısıyla kesinti hiçbir
senaryoda öğrencinin kapıda kalmasına yol açamaz.

### 5.3 Kota

SMS gerçek para. Kurum başına aylık kota ve aşım davranışı tanımlanır;
kotayı aşan kurumda bildirim durur, panel uyarır.

---

## 6. ⚠️ KVKK — rol değişikliği

On-prem modelde kurum kendi verisinin sorumlusuydu; işletmeci yalnızca
yazılım kuruyordu. SaaS'ta öğrenci verisi işletmecinin sunucusunda işleniyor
ve işletmeci **veri işleyen** oluyor.

Doğan yükümlülükler:

- Her kurumla **veri işleyen sözleşmesi**
- VERBİS kaydı yükümlülüğü doğabilir
- İhlal bildirimi zinciri işletmeciye de bağlanır
- Reşit olmayan öğrenci verisi merkezde toplandığı için denetim çıtası yüksek
- Kurum ayrılırken **veri dışa aktarma** (taşınabilirlik) sağlanmalı

> Bu maddeler teknik değil hukuki. Pilotu aşmadan önce bir hukukçuya
> danışılması gerekir; yazılım tarafı bunları karşılayacak biçimde
> tasarlanıyor ama sözleşme süreci ayrıdır.

### 6.1 Veri dışa aktarma — dilim **13b-2** (denetim bulgusu P-4)

Yukarıda yükümlülük olarak sayılmıştı ama **hiçbir dilimde karşılığı
yoktu.** Yükümlülük ilk kurum ayrılmak istediğinde doğar ve o an
"üç ay sonra" denemez; ayrıca abonelik kesintisiyle doğrudan bağlantılı
(kurum "verimi verin" derken genelde ayrılıyordur).

**Kapsam:** kurumun kendi verisinin tamamı — kişiler, veliler, kartlar,
olaylar, oturumlar, yoklama, koçluk kayıtları, bildirim geçmişi.

**Biçim:** kurum başına tek bir ZIP; her tablo ayrı **CSV** + bir
`manifest.json` (şema sürümü, üretim zamanı, satır sayıları).
CSV, çünkü alıcı taraf genelde Excel'dir. Ek olarak makine okunur
tam bir JSON dökümü.

**Kim başlatır:** kurum yöneticisi kendi panelinden **ve** süper yönetici.
Kurumun kendi verisini almak için işletmeciden izin istemesi gerekmemeli —
taşınabilirlik hakkının anlamı bu.

**Nasıl:** arka plan işi, biter bitmez süreli indirme bağlantısı. Büyük
kurumda milyonlarca satır olabilir, istek içinde üretilemez.

⚠️ Dışa aktarma **anonimleştirilmiş kayıtları da** içerir ama kişisel
alanları zaten silinmiş hâlde (KVKK, Faz 11). Silinen veri geri gelmez.

**Sıraya girdiği yer:** `13b-2`, aboneliğin hemen ardından.

---

## 7. Donanım

| Katman | Donanım | Not |
|---|---|---|
| Okuyucu | ESP32 + RC522 | değişmiyor |
| Kenar | **Raspberry Pi 3B** (varsayılan) | Mosquitto + SQLite kuyruk + senkron. Servis makineden bağımsız yazılır; koşullar sağlanırsa kurumun PC'sinde de koşar — bkz. §2.3b |
| Bulut | Barındırılan sunucu | Pi 5 artık üretim değil, geliştirme/pilot kutusu |

---

## 8. Yeni tablolar (kontrat v2.0'a işlenecek)

| Tablo | İş |
|---|---|
| `edge_device` | Kurum başına kenar cihazı: jeton hash'i, son görülme, sürüm |
| `subscription` | Kurum durumu (`active`/`warning`/`restricted`/`suspended`), dönem, kota |
| `sync_state` | Kart kopyası sürümü — artımlı indirme için |

`tenant`'a: `status`, `suspended_at`. `node`'a: `UNIQUE(tenant_id, node_key)`.

---

## 9. Sıralama

| Dilim | İş | Önkoşul |
|---|---|---|
| **13a-0** | **Kimlik modeli: tek hesap + çok kurum üyeliği** (§3b) | — |
| **13a** | Kenar cihazı + senkron uçları + jeton kimliği | 13a-0 |
| **13a-5** | **Elle giriş/çıkış** — kart unutulduğunda kapıdaki görevli kaydı açabilsin | 13a-1 |
| **13b** | Süper yönetici konsolu, kurum açma, abonelik ve kesinti | 13a |
| **13c** | Veli/öğrenci girişi (SMS kodu + e-posta), görünürlük kapısı | 13b |
| **13d** | Koçluk içeriği (ödev, program, deneme, değerlendirme) | 13c |
| **13e** | PWA kabuğu, veli ve öğrenci panelleri | 13d |
| **13f** | Bulut dağıtımı, Cloudflare Tunnel, yük testi | 13e |

> **MQTT TLS artık gerekmiyor.** Faz 11'in o maddesi, okuyucuların internete
> açılacağı varsayımıyla yazılmıştı. Kenar cihazı kararıyla MQTT kurumun
> yerel ağından çıkmıyor; TLS yükü kenar↔bulut HTTPS bağlantısında.
> **Madde kapanmadı, kapsam dışı kaldı.**

---

## 10. Uygulama planı

### 10.1 Mevcut kodda değişecekler — tam liste

Koddan çıkarıldı (2026-08-10), tahmin değil:

| Dosya / satır | Bugün | Olacak |
|---|---|---|
| `01-schema.sql:158` | `node_key text NOT NULL UNIQUE` | `UNIQUE (tenant_id, node_key)` |
| `ingest.py:186, 312, 341` | `select(Node).where(Node.node_key == …)` | kurum **kenar jetonundan**; `node_key` o kurum içinde aranır |
| `routers/chat.py:79` | `select(Tenant).limit(1)` | alıcı numaradan kuruma çözümleme |
| `config.py` | `admin_whatsapp`, `notify_channel` global | `notify_setting`'e taşınır (kurum başına) |

`notify.py:257` zaten `event.tenant_id` kullanıyor — doğru, dokunulmayacak.
`bootstrap.py` yalnızca ilk kurulumda çalışıyor, etkilenmiyor.

> **Kapsam küçük.** Şema baştan `tenant_id` taşıdığı için çok kuruma geçiş
> bir yeniden yazım değil, dört noktalı bir düzeltme. Faz 0'daki "tenant
> izolasyonu" kararı burada karşılığını veriyor.

### 10.2 Yeni bileşen: `edge/`

Depoya yeni bir dağıtılabilir bileşen girer. Bulut yığınından **ayrı**
imaj ve compose dosyası:

```
edge/
├── compose.yml          # mosquitto + edge servisi
├── Dockerfile
├── mosquitto/config/
└── app/
    ├── main.py          # MQTT dinle → kuyruğa yaz → ack gönder
    ├── queue.py         # SQLite dayanıklı kuyruk
    ├── cache.py         # kart kopyası (UID → kişi, durum)
    ├── sync.py          # buluta gönder / kart kopyasını tazele
    └── pair.py          # ilk eşleştirme
```

Bulut tarafındaki `ingest.py`'nin MQTT dinleme kısmı kenara taşınır;
karar ve yazma kısmı bulutta kalır.

### 10.3 ⭐ Çözülmesi gereken dört tasarım sorusu — kararlar

**1) Zaman damgası kenarda hesaplanır.**
Üç saatlik bir kesintiden sonra senkron olan olaylar, bulutun varış saatiyle
damgalanırsa **hepsi aynı ana yığılır** ve o günün devam kaydı çöp olur.

Karar: kenar cihazı olayı kuyruğa alırken `effective_ts`'i **kendisi**
hesaplar (kontrat §2.3 formülü, `server_ts` yerine kenarın saati) ve buluta
açıkça gönderir. Bulut bu değere güvenir.

Yan koşul: kenar, saatini heartbeat'te bildirir; bulut **sapma > 60 sn** ise
uyarı üretir. Pi'de RTC yok ama çalışırken saat korunuyor; elektrik kesilip
internetsiz açılırsa saat yanlış olur — bu durumda kenar, NTP gelene kadar
olayı `clock_unsynced` bayrağıyla kuyruğa alır ve bulut o kayıtları işaretler.

**2) Kararı bulut verir, ışığı kenar yakar.**
Kenardaki kart kopyası bayat olabilir: bulutta iptal edilmiş bir kart,
kesinti sırasında kenarda hâlâ geçerli görünür ve **ışık yeşil yanar**.

Karar: `event.decision` için **bulut yetkilidir**. Kenarın kararı yalnızca
LED/buzzer'ı sürer. Kayıt buluta ulaştığında doğru karar yazılır.

Kabul edilen sınır: kesinti penceresinde iptal edilmiş bir kartla giriş
kaydı oluşabilir — ama **fiziksel kilit olmadığı için** (Faz 0, `relay_ms: 0`)
kimse zaten engellenmiyordu; etkisi yalnızca ışığın yanlış yanması. Bağlantı
varken kart kopyası 60 sn'de bir tazelendiği için pencere pratikte çok dar.

**3) Kenar, olayı yazar yazmaz ack verir** (§2.2). Bulut beklenmez.

**4) Eşleştirme, parola jetonlarıyla aynı desende.**
```
1. Süper yönetici konsolda kurumu açar
2. Konsol tek kullanımlık eşleştirme kodu üretir (24 saat, hash'lenerek saklanır)
3. Teknisyen Pi'ye imajı yazar, kurulum ekranında bulut adresi + kodu girer
4. POST /edge/pair {code} → kalıcı jeton + kurum bilgisi
5. Jeton kenarın SQLite'ında; kod tüketilir
```
Jeton **hash'lenerek** saklanır (`edge_device.token_hash`) — `password_reset`
ile aynı gerekçe: bulut veritabanı sızsa bile jetonlarla kenar taklit edilemez.

### 10.4 Dilimler ve doğrulama

| Dilim | İş | Nasıl doğrulanır |
|---|---|---|
| **13a-1** | Şema: `edge_device`, `sync_state`, `UNIQUE(tenant_id,node_key)` | migration + mevcut veri bozulmadı |
| **13a-2** | Bulut uçları: `/edge/pair`, `/edge/events`, `/edge/credentials`, `/edge/heartbeat` | jetonsuz 401, başka kurumun jetonuyla veri sızmıyor |
| **13a-3** | Kenar servisi (SQLite kuyruk + ack + senkron) | **gerçek kesinti testi**: internet kesilir, kart okutulur, ışık doğru yanar, internet gelince olay buluta akar |
| **13a-4** | `ingest.py` kurumu jetondan çözer | kurum A'nın kenarı, kurum B'nin `node_key`'iyle olay yazamaz |
| **13b** | Süper yönetici konsolu + abonelik + kesinti kademeleri | `suspended` kurumun paneli kapanır, kenarı kayda devam eder |
| **13c** | Veli/öğrenci girişi (SMS kodu + e-posta) | veli yalnızca kendi çocuğunu görür |
| **13d** | Koçluk içeriği | koç girer, veli görür, `visible_to` kapısı çalışır |
| **13e** | PWA | ana ekrana kurulur, çevrimdışı kabuk açılır |
| **13f** | Bulut dağıtımı + Cloudflare Tunnel | yük testi |

### 10.5 Mevcut kurulumun geçişi

Bugünkü Pi 5, gerçek veri taşıyor (56 olay, 18 oturum, 6 kişi). Yol:

1. Pi 5'in veritabanı **buluta taşınır** (pg_dump/restore) — kurum #1 olur
2. Pi 5 **kenar cihazına dönüşür**: PostgreSQL/API/ingest kaldırılır, yerine
   `edge/` yığını kurulur, eşleştirme koduyla buluta bağlanır
3. ESP32'ye dokunulmaz — Mosquitto aynı adreste, aynı kimlikle

Pi 3B'ler yeni kurumlar için; Pi 5 ilk kurumun kenarı olarak kalır (fazlasıyla
yeterli).

### 10.6 Bulut boyutlandırma

Kurum başına 1500 öğrenci × 2 hareket = **3000 olay/gün**.

| Kurum | Olay/gün | Olay/yıl | Not |
|---|---|---|---|
| 1 | 3 bin | ~1,1 M | tek sunucu rahat |
| 10 | 30 bin | ~11 M | rahat |
| 50 | 150 bin | ~55 M | `event` tablosunda **aylık bölümleme** (partition) gerekir |

Yazma yükü düşük ve toplu geliyor (kenar batch gönderiyor) — asıl yük veli
panelinin okuma trafiği. Cloudflare kenar önbelleği PWA kabuğunu üstlenir.

**Not:** `event` tablosu değişmez ve hiç silinmiyor. 50 kurumda 3 yılda ~165 M
satır olur; bölümleme baştan planlanmalı, sonradan eklemek acı verir.

---

## 10.7 Bulut tarafı sertleştirme (denetim bulgusu P-6)

Planın güvenlik bölümü pratikte §2.4 (kenar jetonu) ile sınırlıydı — o iyi
tasarlanmıştı ama **kenar tarafı düşünülmüş, bulut tarafı düşünülmemişti.**
13f panelin internete çıktığı dilim.

| # | İş | Durum |
|---|---|---|
| 1 | Girişte kaba kuvvet koruması | ✅ **yapıldı** 2026-08-10 (kademeli kilit, e-posta bazlı) |
| 2 | Oturum iptali (parola değişince token ölsün) | ✅ **yapıldı** (`password_changed_at`) |
| 3 | `/docs` + `/openapi.json` kapalı | ✅ **yapıldı** (`DOCS_ENABLED`) |
| 4 | CORS açık liste | ✅ **yapıldı** (varsayılan boş) |
| 5 | **IP/ağ başına hız sınırı** | ⚪ 13f — ters vekil katmanında |
| 6 | **Güvenlik başlıkları** (HSTS, CSP, X-Frame-Options) | ⚪ 13f |
| 7 | **Yönetici işlemlerinin denetim kaydı** | ⚪ 13b |
| 8 | HTTPS zorunlu + `Secure` çerezler | ⚪ 13f |

**5 neden ters vekilde:** uygulama içi IP sınırı, ters vekil arkasında
gerçek istemci IP'sini göremez (hepsi vekilin IP'si görünür) ve çok
örnekli kurulumda sayaç bölünür. Cloudflare Tunnel arkasına geçildiğinde
oradan konmalı.

**7 neden 13b:** çok kurumlu kurulumda "kim neyi değiştirdi" sorusunun
cevabı olmalı — kişi silme, rol değiştirme, kart iptali, oturum düzeltme.
Bugün yalnızca `attendance_session.corrected_by` var, o da tek bir işlem
için. Süper yönetici konsoluyla birlikte gelmeli, çünkü asıl riskli
yetkiler orada toplanıyor.

---

## 11. ⭐ Yedekleme ve felaket kurtarma (denetim bulgusu P-5)

On-prem modelde her kurumun verisi kendi Pi'sindeydi; yedekleme onların
sorunuydu. **SaaS'ta bu tamamen size geçiyor:** elli kurumun reşit olmayan
öğrenci verisi tek veritabanınızda ve siz *veri işleyen*siniz.

§10.6 satır sayısını ve bölümlemeyi planlamıştı ama yedeği hiç anmıyordu.
Bölümleme planlanmışken yedeğin planlanmamış olması dengesizdi.

### 11.1 Hedefler — önce sayı, sonra çözüm

| | Hedef | Anlamı |
|---|---|---|
| **RPO** (kabul edilebilir veri kaybı) | **≤ 5 dakika** | Felakette en fazla 5 dakikalık kayıt kaybolur |
| **RTO** (kabul edilebilir kesinti) | **≤ 4 saat** | Bu süre içinde hizmet geri gelmeli |

RPO'nun 5 dakika olabilmesinin sebebi mimarinin kendisi: **kenar cihazları
kuyruk tutuyor.** Bulut çökerse okumalar kaybolmuyor, kenarlarda birikiyor
ve dönünce akıyor. Yani gerçek risk "yeni olaylar" değil, **geçmiş**tir.

### 11.2 Katmanlar

| Katman | Ne | Sıklık | Saklama | Nerede |
|---|---|---|---|---|
| 1 | WAL arşivi (sürekli) | sürekli | 7 gün | ayrı depolama |
| 2 | Tam yedek | günlük | 30 gün | ayrı depolama |
| 3 | Aylık arşiv | aylık | 12 ay | soğuk depolama |

**Kural: yedek asıl veritabanıyla aynı makinede ve aynı sağlayıcıda
durmaz.** Aynı diskteki yedek disk arızasını, aynı sağlayıcıdaki yedek
hesap kapanmasını kurtarmaz.

WAL arşivi (katman 1) RPO'yu dakikalara indiren şey; yalnız günlük tam
yedek olsaydı RPO 24 saat olurdu.

### 11.3 ⚠️ Denenmemiş yedek, yedek değildir

**Üç ayda bir geri dönüş provası zorunlu:** yedekten boş bir sunucuya geri
yükleme, satır sayısı ve şema sürümü karşılaştırması, geçen sürenin
ölçülmesi. Sonuç tarihiyle birlikte kaydedilir.

Yedeklemenin sessizce bozulması yaygındır (dolan disk, süresi geçmiş
kimlik bilgisi, değişen şema). Fark edildiği an, genelde ona ihtiyaç
duyulan andır.

### 11.4 Şifreleme ve sırlar

- Yedekler **durağan hâlde şifreli** — içinde reşit olmayan öğrenci verisi var.
- ⚠️ **`SETTINGS_KEY` yedekten ayrı saklanır.** Sağlayıcı sırlarını
  (SMS/SMTP hesapları) o şifreliyor; aynı yerde durursa şifrelemenin
  anlamı kalmaz. Kaybolursa kayıtlı sırlar çözülemez ve **yeniden
  girilmeleri gerekir** — veritabanı yedeği bunu kurtarmaz.
- Yedek geri yükleme yetkisi denetim kaydına düşer.

### 11.5 Kurum bazında geri alma

Tam geri yükleme (herkesi eski hâline döndürmek) çoğu olayda **yanlış
araçtır**: bir kurumun hatası yüzünden diğer 49'unun verisi geri
alınamaz.

Bu yüzden kurum bazında geri alma yolu gerekir: yedek ayrı bir örneğe
açılır, yalnızca o `tenant_id`'nin satırları çıkarılır ve içeri alınır.
§6.1'deki dışa aktarma altyapısı bunun için de kullanılır — aynı işin
tersi.

### 11.6 Dilim

**13f-1**, bulut dağıtımıyla birlikte. Ama **pilot kurumdan sonra ikinci
kurum alınmadan önce** çalışır durumda olmalı: tek kurumda veri kaybı
kötü, elli kurumda iş bitiricidir.
