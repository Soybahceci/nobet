# Geliştirme tohumu — ÜRETİMDE ÇALIŞTIRILMAZ

`02-seed-dev.sql` **bilerek** `init/` dizininin dışında. Oradaki dosyalar
PostgreSQL ilk açılışta kendiliğinden çalıştırır; test kurumu, sahte kişiler
ve kartlar bir kuruma teslim edilen sistemde bulunmamalı.

## Temiz (üretim) kurulum

`init/` yalnızca şemayı içerir. Kurum ve ilk yönetici hesabı bootstrap ile
oluşturulur:

```bash
docker compose run --rm \
  -e BOOTSTRAP_TENANT_NAME='Örnek Dershanesi' \
  -e BOOTSTRAP_TENANT_SLUG=ornek \
  -e BOOTSTRAP_EMAIL=yonetici@ornek.com \
  -e BOOTSTRAP_PASSWORD='en-az-12-karakter' \
  api python -m app.bootstrap
```

Gerisi arayüzden: mekân, okuyucu düğüm, kişiler, kartlar, kullanıcı hesapları.

> **Neden bootstrap CLI?** Proje ilkesi: *"Sıfır CLI kuralı KURUMU bağlar —
> kurulum yapan teknisyeni değil."* Kurum personeli hiçbir zaman terminale
> girmez; bu tek komut kurulumu yapan kişinindir.
>
> ⚠️ Kurum oluşturma bootstrap'a **2026-08-10'da eklendi**. Öncesinde `tenant`
> satırının tek kaynağı bu tohum dosyasıydı; onu üretim yolundan çıkarmak
> sistemi hiç açılamaz hâle getirirdi.

## Geliştirme kurulumu

Tohumu uygulamak için (veritabanı ayakta olmalı):

```bash
docker compose exec -T postgres psql -U nobet -d nobet < postgres/seed-dev/02-seed-dev.sql
```

`-T` **zorunlu**: onsuz `docker compose exec` bir sözde-terminal ayırır ve
yönlendirilen SQL sessizce yutulur — hiçbir hata vermeden hiçbir şey olmaz.
