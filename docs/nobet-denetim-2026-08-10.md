# NÖBET — Kod ve Plan Denetimi

**Tarih:** 2026-08-10 · **Kapsam:** backend (7 469 satır Python), frontend, altyapı,
Faz 13 SaaS mimarisi · **Durum:** **18 bulgunun 18'i ele alındı** — kod
bulgularının tamamı düzeltildi, plan bulgularının tamamı mimari dokümana işlendi

> Bulguların çoğu **çalışan sistemde denenerek** doğrulandı, okuyarak tahmin
> edilmedi. Denenmemiş olanlar açıkça "çıkarım" diye işaretli.

---

## Özet

| Ağırlık | Adet | Durum |
|---|---|---|
| 🔴 Kritik | 1 | K-1 dizin aşımı → ✅ |
| 🟠 Yüksek | 2 | Y-1 oturum iptali · Y-2 kaba kuvvet → ✅ ✅ |
| 🟡 Orta | 5 | O-1 CORS · O-2 migration · O-3 mekân adı · O-4 `/docs` · O-5 koç panosu → ✅ ×5 |
| ⚪ Düşük | 3 | D-1 filtreler · D-2 N+1 · D-3 refresh token → ✅ ×3 |
| 📐 Plan | 7 | P-1…P-7 → ✅ hepsi karara bağlandı ve dokümana işlendi |
| | **18** | **hepsi ele alındı** |

> ⚠️ **Sayım düzeltmesi:** ilk özet tablosunda "Düşük: 2" yazıyordu ama gövdede
> D-1, D-2, D-3 diye üç bulgu var; toplam 17 değil **18**.

**Genel değerlendirme:** kod kalitesi yüksek. Yetki kapıları çalışıyor
(yetkisiz uçlar 401 dönüyor), kilitlenme korumaları düşünülmüş, yorumlar
gerekçe yazıyor. Faz 13 planının koda dair **her iddiası doğru çıktı** — satır
numaraları dahil. Aşağıdakiler bu kalitenin istisnaları.

---

## 🔴 K-1 · Dizin aşımı: sunucudan keyfi dosya okuma — ✅ **KAPATILDI**

> **Durum: düzeltildi ve doğrulandı, 2026-08-10 akşam.** Düzeltme
> `backend/app/main.py`'de, Pi'ye derlenip yüklendi. Doğrulama en altta.

**Yer:** `backend/app/main.py:88-90`

```python
candidate = STATIC_DIR / full_path
if full_path and candidate.is_file():
    return FileResponse(candidate)
```

`full_path` istemciden geliyor ve hiçbir temizlemeden geçmeden dosya yoluna
ekleniyor. `..` parçaları statik klasörün dışına çıkarıyor.

### Kanıt (Pi üzerinde çalıştırıldı)

```
curl --path-as-is "http://127.0.0.1:8080/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd"
→ 200
→ root:x:0:0:root:/root:/bin/bash
```

Üç varyantın üçü de 200 döndü: düz `../`, yüzde kodlu `%2e%2e`, `..%2f`.
Üstteki `full_path.startswith(("api/", ...))` kontrolü bunları engellemiyor.

### Neden kritik

API süreci ne okuyabiliyorsa saldırgan da okuyabilir. Bu, sürecin **kendi
ortam değişkenlerini** de kapsar (`/proc/self/environ`) — orada `JWT_SECRET`,
`POSTGRES_PASSWORD`, `SETTINGS_KEY`, `MQTT_PASS` duruyor.

> ⚠️ Bu son cümle **çıkarımdır, denenmedi** (sondayı güvenlik sınırı
> engelledi). Ama keyfi dosya okuma kanıtlandığına göre çıkarım güçlü.

`JWT_SECRET` ele geçen biri **istediği kurumun yöneticisi olarak geçerli token
üretir.** Parola gerekmez, kayıt düşmez. `SETTINGS_KEY` ise Fernet anahtarı —
sağlayıcı kimlik bilgileri (SMS/SMTP hesapları) onunla şifreleniyor.

**Bugünkü maruziyet sınırlı:** panel yalnızca yerel ağda ve Tailscale'de.
İnternete açık değil. **Faz 13f'te bulut dağıtımıyla bu doğrudan internete
çıkar** — o noktadan önce mutlaka kapanmalı.

### Düzeltme

```python
candidate = (STATIC_DIR / full_path).resolve()
if full_path and candidate.is_file():
    # Çözümlenmiş yol statik klasörün ALTINDA mı? Değilse dizin aşımı.
    if STATIC_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
return FileResponse(STATIC_DIR / "index.html")
```

`resolve()` `..` parçalarını ve sembolik bağları çözer; `parents` kontrolü
sonucun kök dizinin altında kaldığını doğrular. Aşım denemesi 404 yerine
`index.html` alır — saldırgana bilgi vermez.

### Uygulanan hâli

`main.py`'de sınır bir kez çözülüp saklanıyor, kontrol ayrı bir yardımcıda:

```python
_STATIC_ROOT = STATIC_DIR.resolve()

def _within_static(p: Path) -> bool:
    return _STATIC_ROOT == p or _STATIC_ROOT in p.parents
```

`candidate = (STATIC_DIR / full_path).resolve()` sonra
`candidate.is_file() and _within_static(candidate)`.

**İki adım da gerekli.** Yalnız `resolve()` yolu normalleştirir ama sınırı
zorlamaz; yalnız `parents` kontrolü ise çözülmemiş `..` parçalarını yakalayamaz.

### ✅ Doğrulama (Pi'de, düzeltmeden sonra)

Sekiz varyant denendi, **sekizi de** `index.html` döndü; hiçbirinde
`root:x:0:0` ya da ortam değişkeni izi yok:

```
/../../../../etc/passwd                          index.html
/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd          index.html
/..%2f..%2f..%2f..%2fetc/passwd                  index.html
/%2e%2e/%2e%2e/%2e%2e/%2e%2e/proc/self/environ   index.html
//etc/passwd                                     index.html
///etc/passwd                                    index.html
/%2fetc%2fpasswd                                 index.html
/static/../../../etc/passwd                      index.html
```

> `//etc/passwd` varyantı ayrıca denendi çünkü **`pathlib`'de mutlak yol
> soldakini siler**: `Path("/srv/static") / "/etc/passwd"` → `/etc/passwd`.
> `_within_static` bunu da yakalıyor.

Meşru kullanımın bozulmadığı da doğrulandı:

| Yol | Sonuç |
|---|---|
| `/` | 200 |
| `/kisiler` (SPA yolu) | 200 |
| `/assets/index-*.js` | 200 |
| `/api/v1/auth/login` | 200 |
| `/api/v1/yok-boyle-bir-uc` | 404 (index.html değil — doğru) |
| `/health` | 200 |

> `/assets` mount'u `StaticFiles` kullanıyor; Starlette dizin aşımını kendi
> ele aldığı için orada açık yoktu. Savunmasız olan yalnızca SPA'nın
> "hepsini yakala" yolu idi.

---

## 🟠 Y-1 · Parola sıfırlamak çalınmış oturumu düşürmüyor — ✅ **KAPATILDI**

> **Durum: düzeltildi ve doğrulandı, 2026-08-10 akşam.** Migration `0011`,
> `app_user.password_changed_at`. Uçtan uca test 8/8 geçti; ayrıntı en altta.

**Yer:** `backend/app/security.py:89` · `backend/app/deps.py:26`

`decode_token` yalnızca imzayı, süreyi ve tipi doğruluyor. `current_user`
veritabanından yalnızca `is_active` bakıyor. **Parolanın ne zaman
değiştiğine bakan hiçbir kontrol yok.**

`passwords.invalidate_all()` bekleyen *sıfırlama jetonlarını* kapatıyor —
ama dolaşımdaki **JWT'lere dokunmuyor**. `auth.py:82`'deki `logout` bunu
zaten itiraf ediyor: *"Gerçek iptal gerekirse Faz 11'de jti kara listesi
eklenmeli."*

### Sonucu

Birinin hesabı ele geçirildi. Parolasını değiştiriyor — yapılacak doğru şey
bu. Ama saldırgandaki refresh token **`refresh_token_days = 14`** boyunca
geçerli kalıyor ve istediği an yeni access token üretebiliyor.

Yani parola değiştirmek, *tam da işe yaraması gereken durumda* işe yaramıyor.

### Düzeltme (ucuz)

`app_user`'a `password_changed_at timestamptz` eklenir; parola değişen her
yerde güncellenir (üç yer: `auth.py` reset, `auth.py` change-password,
`users.py` admin reset — üçü de zaten `invalidate_all` çağırıyor, aynı satıra
eklenir). `current_user` içinde:

```python
if payload["iat"] < user.password_changed_at.timestamp():
    raise HTTPException(401, "parola değişti — yeniden giriş yapın")
```

Kara liste tablosu gerekmiyor, tek kolon yetiyor.

### Uygulanan hâli

| Dosya | Değişiklik |
|---|---|
| `alembic/versions/0011_password_changed_at.py` | kolon + geri doldurma |
| `models.py` | `AppUser.password_changed_at` |
| `security.py` | `token_predates_password_change()` |
| `deps.py` | `current_user` — access token kontrolü |
| `routers/auth.py` | `/auth/refresh` kontrolü ⭐ · reset ve change-password damgası |
| `routers/users.py` | yönetici sıfırlaması damgası |
| `frontend/pages/Account.tsx` | dönen taze token'ları saklar |

**Geri doldurma `created_at` ile yapıldı, `now()` ile değil** — `now()`
dağıtım anında herkesi sistemden atardı.

`/auth/change-password` artık **204 değil, taze token çifti** döndürüyor.
Parola değişince o ana kadarki tüm token'lar ölüyor; buna kullanıcının o an
kullandığı token da dahil. Taze çift vermeseydik kişi kendi parolasını
değiştirdiği anda dışarı atılırdı. Sonuç: **diğer oturumlar düşer, bu oturum
devam eder** — beklenen davranış tam olarak bu.

### ⚠️ İlk denemede ÇALIŞMADI — tolerans payı hatası

İlk yazımda `iat + 1 saniye < damga` karşılaştırması vardı. Test **başarısız**:
eski token hâlâ 200 dönüyordu. Sebep, testin bir saniyenin içinde koşması ve
payın her şeyi yutmasıydı.

Pay keyfi bir sabit yerine **iki tarafı da saniyeye yuvarlayarak** düzeltildi
(`int(iat) < int(damga)`). Yuvarlama şart, çünkü JWT `iat` alanı tam saniye
(RFC 7519) ama damga mikrosaniyeli: ham karşılaştırmada parola değiştiren
kullanıcıya verilen **taze token doğduğu anda ölürdü**.

> **Kalan sınır — bilinerek kabul edildi:** parola değişikliğiyle *aynı saniye
> içinde* üretilmiş token hayatta kalır. Gerçek tehdit modelinde önemsiz;
> saldırganın token'ı dakikalar/günler öncesine aittir. Daha ince ayrım
> `iat` yerine milisaniyeli özel bir alan gerektirir, RFC dışına çıkmaya
> değmez.

### ✅ Doğrulama — saldırgan senaryosu birebir kuruldu

Aynı hesapta iki oturum: **A** = "çalınmış", **B** = kurbanın oturumu.

```
A access baştan çalışıyor            200  OK
A refresh baştan çalışıyor           200  OK
B parolayı değiştiriyor → taze çift  OK
─────────────────────────────────────────
A access ARTIK REDDEDİLDİ            401  ✔  "parola değişti — yeniden giriş yapın"
A refresh ARTIK REDDEDİLDİ           401  ✔
C access çalışıyor (atılmadı)        200  ✔
C refresh çalışıyor                  200  ✔
eski parola ile giriş reddedildi     401  ✔
─────────────────────────────────────────
SONUÇ: 8 geçti, 0 kaldı
```

Test parolayı sonunda **eski hâline geri aldı**; giriş bilgileri değişmedi.

---

## 🟡 O-5 · Ana pano koça 403 aldırıyor — ✅ **KAPATILDI**

> Denetim listesinde yoktu; **kullanıcı bildirdi** ("koç olarak girince bazen
> yetkiniz yok yazıyor, bazen içerik geliyor"). 2026-08-10 akşam düzeltildi.

**Yer:** `frontend/src/pages/Dashboard.tsx`

Ana pano (`/`) her role açık, ama içindeki üç uç `StaffUser` istiyor.
Koç token'ıyla ölçüldü:

| Uç | Koç |
|---|---|
| `/dashboard/summary` | 200 |
| `/sessions/open` | 200 |
| **`/events?size=20`** | **403** |
| **`/notifications/channel`** | **403** |
| `/reports/my-students` | 200 |

### Neden "bazen öyle bazen böyle"

Bir yarış durumu:

1. İlk yüklemedeki `Promise.all([summary, events])` — `/events` 403 verince
   **tümü** reddediliyor. Başarılı olan özet de çöpe gidiyor, ekranda
   "yetkiniz yok" beliriyor.
2. Arka planda 15 saniyede bir çalışan `loadSummary` ise **başarılı** oluyor
   ve `setError(null)` diyor → hata kayboluyor, içerik geliyor.

Yani ekran, hangi isteğin önce döndüğüne göre değişiyordu. Sunucu tarafında
hata yoktu; yetki kapıları doğru çalışıyordu.

### Düzeltme

Arayüz yetkisi olmayan uca **hiç çağrı yapmıyor.** Yetki kapısı sunucuda
kalıyor (tek doğruluk kaynağı orası), arayüz yalnızca boşuna kapı çalmayı
bırakıyor.

Ayrıca koça **kendi panosu** verildi. `/dashboard/summary` koç için
filtrelenmiyor — kurum geneli sayı döndürüyor. Üstte "12 içeride" yazarken
listede 2 kişi görünmesi yanıltıcı olurdu; ayrıca okuyucu durumu ve kayıtsız
kart sayısı koçun işi değil. Koç artık kendi öğrencilerini (`/sessions/open`
zaten koça göre filtreliyor) ve Öğrencilerim bağlantısını görüyor.

> **`/sessions/open` doğru davranıyor** — her satır için
> `assert_can_see_person` çağırıyor, koç yalnızca kendi öğrencilerini
> görüyor. Orada sızıntı yok.

---

## 🟠 Y-2 · Giriş ucunda kaba kuvvet koruması yok — ✅ **KAPATILDI**

> `login_attempt` tablosu (migration `0013`) + `app/login_guard.py`.
> Kademeli kilit: 5. hatadan sonra 1 dk, ikiye katlanarak 30 dk tavan.
> **Sayaç e-postaya göre, hesabın varlığından bağımsız** — yalnızca var olan
> hesaplar kilitlenseydi, kilit davranışı hesabın varlığını ele verirdi.
> Doğrulandı: 5 hata sonrası 6. istek 429; olmayan bir e-posta da AYNI
> şekilde kilitlendi; doğru parola bile kilitliyken reddedildi; başarılı
> giriş sayacı sildi.
>
> ⚠️ **Sınır:** koruma e-posta başına. Çok sayıda farklı hesaba dağıtılmış
> saldırı (password spraying) bununla durmaz; IP başına sınır 13f'te ters
> vekil katmanına konacak (bkz. mimari §10.7).

**Yer:** `backend/app/routers/auth.py:39`

### Ölçüm (Pi üzerinde)

12 ardışık yanlış parola denendi:

```
 1..12 -> hepsi 401, her biri ~0.22 sn
sonra doğru parola -> 200
```

Kilitleme yok, gecikme artışı yok, sayaç yok, IP sınırı yok, CAPTCHA yok.
argon2id tek başına ~0.22 sn maliyet getiriyor — bu **çevrimdışı** saldırıya
karşı iyi, **çevrimiçi** saldırıya karşı yeterli değil: bağlantı başına
~4.5 deneme/sn, paralel bağlantıyla katlanır.

`/auth/forgot` hız sınırlı (kullanıcı başına 1 dk) ama `/auth/login` değil.

**Bugün yerel ağda.** Faz 13f'te internete çıkıyor. SaaS'ta bir kurumun
yönetici hesabının kırılması, o kurumun tüm öğrenci verisi demek.

### Düzeltme

En az: `app_user`'a `failed_logins` + `locked_until`; 5 başarısızlıkta artan
gecikme. Tercihen IP başına da sınır (ör. `slowapi`). Faz 13'e girmeden
kararlaştırılmalı — planda bu madde **hiç yok** (bkz. P-6).

---

## 🟡 O-1 · CORS her kaynağa açık — ✅ **KAPATILDI**

> Varsayılan artık **boş liste**; `CORS_ORIGINS` yazılmadıkça middleware hiç
> eklenmiyor. Arayüz API ile aynı kökenden servis edildiği için normal
> kullanımda çapraz köken isteği zaten yok. Doğrulandı: yabancı `Origin`
> başlığıyla gelen isteğe `Access-Control-Allow-Origin` dönmüyor.

**Yer:** `backend/app/config.py:80` — `cors_origins: list[str] = ["*"]`
Pi'nin `.env` dosyasında `CORS_ORIGINS` **tanımlı değil**, yani varsayılan
yürürlükte.

`main.py:44` bunu `allow_credentials=True` ile birleştiriyor. Bu ikisi
şartnameye göre birlikte geçersiz; tarayıcılar `*` + kimlik bilgisi
kombinasyonunu reddeder. Uygulama token'ı `Authorization` başlığında
taşıdığı için bugünkü pratik risk düşük — ama SaaS'ta panelin alan adı
belli olacak, o zaman `*` bırakmanın hiçbir gerekçesi kalmaz.

---

## 🟡 O-2 · Temiz kurulum elle migration istiyor — ✅ **KAPATILDI**

> **Düzeltildi ve doğrulandı, 2026-08-10.** `app/migrate.py` +
> `entrypoint.sh` + `/health` şema kontrolü. Ayrıntı bölüm sonunda.

İki ayrı şema kaynağı var:

| Kaynak | Kapsam |
|---|---|
| `infra/postgres/init/01-schema.sql` | 11 temel tablo (Faz 1) |
| `alembic/versions/0002…0010` | `notification`, `notify_setting`, `wa_thread`, `wa_message`, `password_reset`, `lesson` |

Tasarım bilinçli ve `0001_baseline.py` bunu güzelce belgeliyor: init SQL
çalışır, sonra `alembic stamp 0001`, sonra `upgrade head`.

**Sorun: o "sonra" kısmını çalıştıran hiçbir şey yok.**
`infra/compose.yml`'de ve `backend/Dockerfile`'da `alembic` komutu geçmiyor;
`CMD` doğrudan `uvicorn`. Yani migration'lar **elle** çalıştırılıyor.

Üstüne `/health` yalnızca `SELECT 1` yapıyor — yarım migrate edilmiş bir
veritabanında konteyner **`healthy` raporlar**, hata ancak o tabloya ilk
dokunulduğunda çıkar.

> Bu, bugün `UserOut` çakışmasını saklayan **aynı kör noktadır.**

Tek kurumda bir kez yapılıp unutulur. SaaS'ta her yeni kurulumda tekrarlanır
ve "Sıfır CLI" kuralına da aykırıdır.

**Düzeltme:** API konteynerine giriş betiği (`alembic upgrade head` sonra
uvicorn) + `/health`'in `alembic_version`'ı beklenen sürümle karşılaştırması.

### Uygulanan hâli

| Dosya | İş |
|---|---|
| `app/migrate.py` | açılışta şemayı yükseltir |
| `entrypoint.sh` | `python -m app.migrate` sonra `exec "$@"` |
| `Dockerfile` | `ENTRYPOINT ["./entrypoint.sh"]`, `CMD` korundu |
| `app/main.py` | `/health` şema sürümünü doğrular |

Üç ayrıntı kasıtlı:

1. **`set -e`** — migration başarısızsa konteyner açılmaz. Yanlış şemayla
   çalışan bir API, açılmayan bir API'den tehlikelidir; hata aylar sonra
   bir tabloya ilk dokunulduğunda çıkardı.

2. **Danışma kilidi** (`pg_advisory_lock`, id `8_150_003`) — `api` ve
   `ingest` aynı imajı paylaşıyor ve birlikte kalkıyor; ikisi de aynı DDL'i
   aynı anda uygulamaya kalkardı. Ölçüldü: `api` 21:24:44, `ingest`
   21:24:47 — ikincisi bekledi, sırası geldiğinde yapacak iş bulamadı.

3. **Alembic alt süreçte** — `alembic/env.py` içinde `asyncio.run()` var;
   çalışan bir olay döngüsünden çağrılırsa `RuntimeError` verir.

**Temiz kurulum:** `alembic_version` yoksa ama `app_user` varsa (init SQL
çalışmış) önce `stamp 0001`, sonra `upgrade head`. İkisi de yoksa **yüksek
sesle hata** — `0001` bilinçli olarak boş bir damga olduğu için oradan
`upgrade head` demek tabloları yaratmaz, sessizce yarım şema bırakırdı.

### ✅ Doğrulama

```
normal                          /health -> 200 {"status":"ok","schema":"0012"}
damga elle 0011'e çekildi       /health -> 503 "şema eski — veritabanı '0011',
                                                kod '0012' bekliyor"
damga geri 0012                 /health -> 200
```

Konteyner `healthy`, beş uç 200 döndü. **Kör nokta kapandı:** yarım migrate
edilmiş veritabanı artık `healthy` raporlayamıyor.

---

## 🟡 O-3 · Mekân adı kurum filtresi olmadan okunuyor — ✅ **KAPATILDI**

> `.where(Zone.id == zone_id, Zone.tenant_id == user.tenant_id)`.
> Doğrulandı: ikinci bir kurumda `GIZLI MEKAN ADI` adlı mekân açıldı,
> birinci kurumun jetonuyla o `zone_id` istendi — ad **dönmedi**.

**Yer:** `backend/app/routers/reports.py:131-133`

```python
zone_name = (
    await db.execute(select(Zone.name).where(Zone.id == zone_id))
).scalar_one_or_none()
```

Aynı fonksiyondaki diğer sorgular `tenant_id` filtreliyor, bu filtrelemiyor.
Başka kurumun `zone_id`'sini bilen (ya da tutturan) biri **o mekânın adını**
öğrenir. Rapor satırları sızmıyor, yalnızca ad.

Tek kurumda etkisiz. SaaS'ta küçük ama gerçek bir sızıntı ve tam olarak
çoğalan sınıftan: `.where(Zone.id == zone_id, Zone.tenant_id == user.tenant_id)`.

---

## 🟡 O-4 · `/docs` ve `/openapi.json` kimlik doğrulamasız — ✅ **KAPATILDI**

> `DOCS_ENABLED` (varsayılan `false`) ile kapatıldı; `/docs`, `/redoc` ve
> `/openapi.json` üçü de 404.
>
> Not: ilk denemede `/redoc` 200 döndü ve bir an açık sanıldı — meğer SPA'nın
> `index.html`'ini döndürüyormuş (bilinmeyen yollar için tasarlanan davranış),
> içinde API dokümanı izi yoktu. Yine de tutarlılık için `redoc` da 404
> listesine eklendi.

`main.py:40-41` ikisini de açık bırakıyor; Pi'de doğrulandı (`200`).
Yerel ağda önemsiz. İnternete çıkınca saldırgana tüm uç haritasını,
şema alanlarını ve rol gereksinimlerini hazır verir. Üretimde
`docs_url=None` (ya da yönetici arkasına) alınmalı.

---

## ⚪ D-1 · Savunma amaçlı eksik kurum filtreleri — ✅ **KAPATILDI**

> `reports.py` içindeki üç sorguya da `tenant_id` filtresi eklendi
> (`my_students`, `classroom`, haftalık toplam). Sömürülebilir değillerdi;
> koruma tek katmana bağlı kalmasın diye.

| Yer | Durum |
|---|---|
| `reports.py:354` `my_students` | `Person` sorgusunda `tenant_id` yok |
| `reports.py:283` `classroom` | oturum sorgusunda `tenant_id` yok |
| `reports.py:367` `agg` | `tenant_id` yok |

Üçü de bugün **sömürülebilir değil**: kişi ve mekân kimlikleri zaten kurum
filtresinden geçmiş sorgulardan geliyor. Ama koruma tek katmana bağlı; bir
üstteki filtre değişirse sessizce açılır. Ucuz sigorta.

## ⚪ D-2 · N+1 sorgu — ✅ **KAPATILDI**

> `classroom` ve `my_students` kişi başına bir sorgu yapıyordu. İkisi de tek
> sorguya indirildi (`IN (...)` + bellekte eşleştirme / `GROUP BY`).
> `classroom`'da `order_by(entered_at).limit(1)` semantiği korundu: sorgu
> sıralı geldiği için kişi başına ilk görülen oturum alınıyor.
> Hiç oturumu olmayan öğrenci `my_students`'ta sıfırlarla görünmeye devam ediyor.

`classroom` yoklamasında öğrenci başına bir sorgu (`reports.py:283`),
`my_students`'ta da öyle (`reports.py:367`). 30 kişilik sınıf = 31 gidiş
geliş. Bugün sorun değil; 1500 kişilik kurumda koç paneli 50 sorguya çıkar.
Bulutta ağ gecikmesi eklenince fark edilir hâle gelir.

## ⚪ D-3 · Refresh token `localStorage`'da — ✅ **KAPATILDI**

> Refresh token artık **HttpOnly çerezte** (`SameSite=strict`,
> `Path=/api/v1/auth`) ve **yanıt gövdesinde hiç dönmüyor** — dönseydi arayüz
> yine saklayabilir ve korumanın anlamı kalmazdı. Access token bellekte,
> Bearer modeli korundu (kontrat §3.1 değişmedi); değişen yalnızca uzun
> ömürlü kimlik bilgisinin NEREDE durduğu.
>
> Yan kazanç: **çıkış artık gerçekten iptal ediyor.** Eskiden token durumsuz
> olduğu için `/auth/logout` hiçbir şey yapamıyordu; şimdi sunucu çerezi
> siliyor.
>
> Doğrulandı (17/17): çerez bayrakları, çerezsiz tazelemenin 401 vermesi,
> çıkıştan sonra tazelemenin reddedilmesi, parola değişiminde çerezin
> tazelenmesi.
>
> ⚠️ **`Secure` bayrağı şu an KAPALI** (`COOKIE_SECURE=false`), çünkü panel
> yerel ağda düz HTTP. Açık olsaydı tarayıcı çerezi hiç göndermezdi.
> **13f'te HTTPS'e geçilince `true` yapılmalı.**

`frontend/src/api.ts:24-34`. Sayfa yenilendiğinde oturumun sürmesi için
bilinçli bir tercih ve gerekçesi yorumda yazılı. Bedeli: bir XSS açığı
**14 günlük** oturumu kalıcı olarak çalar. **Y-1 ile birleşince**
(parola değiştirmek token'ı düşürmüyor) kurbanın bunu geri alma yolu yok —
`JWT_SECRET`'ı döndürmek dışında, o da herkesi atar.

Y-1 düzeltilirse bu bulgu büyük ölçüde sönüyor. İkisini birlikte ele alın.

---

# 📐 Faz 13 planı — kapatılmamış boşluklar

Plan sağlam: katmanlar net, kenar cihazı gerekçesi doğru, `uint8_t` tuzağı
yakalanmış, KVKK rol değişikliği fark edilmiş. Koda dair yedi iddiasının
**yedisi de doğru.** Aşağıdakiler eksikler.

## P-1 · `app_user.email` **global** UNIQUE — boşluk listesinde yok

`models.py:333` → `email … unique=True` (kurum bazlı değil, global).
`auth.py:42` girişte kullanıcıyı **yalnızca e-postadan** buluyor, kurum
sormuyor. Yani bugünkü giriş akışı global benzersizliğe **bağımlı**.

Plan §4'te `node_key`'in global UNIQUE olduğu yakalanmış (madde 3) ama
**e-posta yakalanmamış.** Doğurduğu sorular:

- İki dershanede çalışan bir koç iki hesap açtıramaz
- **§13c veli girişi bunu patlatır:** çocukları iki kurumda olan veli tek
  hesapla iki kurumu nasıl görecek? Veliler koçlardan çok daha kalabalık,
  yani bu istisna değil, olağan durum
- E-postayı kurum bazına çevirmek girişe **kurum seçimi** eklemeyi zorunlu
  kılar (alt alan adı, kurum kodu ya da açılır liste)

Bu bir uygulama ayrıntısı değil, **kimlik modeli kararı**. 13c'de keşfedilirse
giriş akışı ve veri modeli birlikte değişir. **13a-1'de karara bağlanmalı.**

## P-2 · Senkron protokolünde "reddedildi" kovası yok — kuyruk kalıcı tıkanabilir

Plan §3.1:

```
→ { "accepted": [seq…], "duplicate": [seq…] }
```

ve *"Kuyruktan silme yalnızca bulut kabul ettikten sonra."*

Üçüncü bir sonuç eksik: **kalıcı ret.** Bulut bir olayı hiçbir zaman kabul
edemezse (silinmiş `node_key`, bozuk kayıt, şema uyuşmazlığı), kenar onu
kuyruktan silemez, sonsuza kadar yeniden gönderir ve **arkasındaki bütün
olaylar sıkışır.** Klasik zehirli mesaj / baş tıkanması.

Kurum aylarca sessizce veri göndermez; kimse fark etmez çünkü kenar "çalışıyor"
görünür.

**Gereken:** yanıta `rejected: [{seq, reason}]` eklenmesi, kenarın bunları
ayrı bir "ölü mektup" tablosuna taşıması ve panelde sayaç olarak görünmesi.

## P-3 · Askıya alınmış kurumda kuyruğun sınırı yok

§5.2: `suspended` kurumda kenar **kayda devam eder**, ödeme gelince akar.
Doğru karar (§5.1 ilkesiyle tutarlı). Ama üst sınır tanımlı değil.

3000 olay/gün × 6 ay ≈ 540 bin satır. SQLite için boyut sorunu değil
(~50-100 MB), ancak Pi 3B'nin SD kartında sınırsız büyüyen bir dosya var ve
**dolduğunda ne olacağı yazılmamış.** En azından: eşik uyarısı, kenar
panelinde durum, dolma hâlinde davranış (en eskiyi düşür mü, yazmayı durdur
mu — ikisi de veri kaybı, hangisinin seçildiği yazılı olmalı).

## P-4 · Veri dışa aktarma hukuki yükümlülük, ama dilimi yok

§6: *"Kurum ayrılırken **veri dışa aktarma** (taşınabilirlik) sağlanmalı"* —
yükümlülük olarak doğru tespit edilmiş. Ama §9 ve §10.4'teki dilim
listelerinde (13a…13f) **karşılığı yok.**

Yükümlülük ilk kurum ayrılmak istediğinde doğar; o an "üç ay sonra" denemez.
Ayrıca abonelik kesintisiyle doğrudan bağlantılı: kurum "verimi verin"
dediğinde hazır olmalı. **13b'ye (abonelik) bağlanmalı.**

## P-5 · Bulut için yedekleme / felaket kurtarma planı yok

On-prem modelde her kurumun verisi kendi Pi'sindeydi; yedekleme onların
sorunuydu. SaaS'ta **elli kurumun reşit olmayan öğrenci verisi sizin tek
veritabanınızda** ve siz *veri işleyen*siniz.

§10.6 boyutlandırma yapıyor (satır sayısı, bölümleme) ama **yedek, geri
dönüş süresi, kabul edilebilir veri kaybı ve yedekten dönüş provası** hiç
geçmiyor. §6'daki ihlal bildirimi zinciri ile doğrudan ilgili.

Denetimdeki en büyük **işletme** boşluğu bu. Bölümleme planlanmışken
yedeğin planlanmamış olması dengesiz.

## P-6 · Kimlik doğrulama sertleştirmesi planda hiç yok

Plan'ın güvenlik bölümü pratikte §2.4 (kenar jetonu) ile sınırlı — o da iyi
tasarlanmış. Ama 13f panelin **internete çıktığı** dilim ve planda şunların
hiçbiri geçmiyor: giriş hız sınırı (bkz. Y-2), yönetici işlemlerinin denetim
kaydı, oturum iptali (bkz. Y-1), `/docs` kapatma, güvenlik başlıkları.

Kenar tarafı düşünülmüş, **bulut tarafı düşünülmemiş.**

## P-7 · "Makineden bağımsız" ile Docker paketlemesi çelişiyor

§2.3b: *"Docker'a ya da Linux'a bağımlı bir tasarım kullanılmaz"* —
girişteki PC'de de koşabilsin diye.

§10.2 ise `edge/compose.yml` + `Dockerfile` gösteriyor.

Servisin **kodu** gerçekten bağımsız olabilir (düz Python + SQLite), yani
çelişki ölümcül değil. Ama Windows'lu bir resepsiyon bilgisayarında Docker
Desktop ağır bir bağımlılık ve pratikte kabul ettirilemez. Windows'ta nasıl
paketleneceği (servis mi, tek dosya exe mi, ne ile güncellenecek) **yazılmamış.**
Ya yazılmalı ya da §2.3b'deki PC seçeneği "ileride" diye işaretlenmeli.

---

## Öneri — ele alma sırası

| Sıra | İş | Gerekçe |
|---|---|---|
| ~~1~~ | ~~**K-1** dizin aşımı~~ | ✅ **2026-08-10 akşam kapatıldı ve doğrulandı** |
| 2 | **P-1** e-posta kimlik modeli kararı | 13a-1 şemasını etkiler, sonradan pahalı |
| 3 | **Y-1** + **D-3** oturum iptali | Tek kolon; D-3'ü de büyük ölçüde kapatır |
| 4 | **O-2** migration otomasyonu | Her yeni kurumda tekrarlayacak |
| 5 | **Y-2**, **O-1**, **O-4** | 13f internete çıkmadan önce |
| 6 | **O-3**, **D-1** kurum filtreleri | Ucuz, çoğalmadan |
| 7 | **P-2**…**P-7** plana işlensin | Kod yazmadan önce doküman güncellensin |

1-4 arası Faz 13'e girmeden yapılmalı. 5-6 13f'ten önce. 7 hemen — plan
belgesi kod yazılmadan düzeltilirse bedava.
