#!/usr/bin/env bash
# Faz 13b-3 — uygulama rolunun yetki ayrimi (mimari §10.8)
#
# Kanitlanacak sey: uygulama artik veritabaninda SUPER KULLANICI DEGIL,
# ve isini yapmaya devam ediyor. Ikisi birden olmali; sadece birincisi
# "uygulama coktu" demektir, sadece ikincisi bugunku durumdur.
#
# TEK KULLANIMLIK yiginda kosar (8090). Uretimde CALISTIRMAYIN.
set -uo pipefail
B=http://127.0.0.1:8090/api/v1
ROL=nobet_app
APAROLA=test-app-parolasi-degil-gercek
pass=0; fail=0
ok(){ echo "   [OK]   $1"; pass=$((pass+1)); }
no(){ echo "   [HATA] $1"; fail=$((fail+1)); }
chk(){ [ "$2" = "$3" ] && ok "$1 ($3)" || no "$1 bekleniyordu=$2 gelen=$3"; }
need(){ [ -n "$2" ] || { echo "   [DUR] zemin kurulamadi: $1 bos"; exit 9; }; }

# sahip rolle sorgu
q(){ docker exec nobet-test-postgres psql -U nobet -d nobet -tA -c "$1" 2>&1 | head -1 | tr -d ' \r'; }
# UYGULAMA rolyle sorgu — yetkiyi gercekten o rolun gozunden sinar
qa(){ docker exec -e PGPASSWORD="$APAROLA" nobet-test-postgres \
        psql -h 127.0.0.1 -U "$ROL" -d nobet -tA -c "$1" 2>&1 | head -3; }
# yasak olmasi gereken islem: reddedildi mi?
red(){ case "$(qa "$2")" in *"denied"*|*"must be owner"*|*"permission"*) ok "$1 REDDEDILDI";;
        *) no "$1 IZIN VERILDI (!)";; esac; }

cd "$(dirname "$0")/.."

# Beklenen sema surumu migration dosyalarindan okunur — her yeni
# migration'da bu betigi elle guncellemek gerekmesin diye.
SEMA_BASI=$(ls backend/alembic/versions/ | sed "s/_.*//" | sort -n | tail -1)

echo "=== zemin: sifirdan yigin, rol api'den ONCE aciliyor ==="
# Sira onemli: migration 0018 yetkileri ancak rol VARSA verir.
docker compose -f compose.test.yml down -v >/dev/null 2>&1
docker compose -f compose.test.yml up -d postgres-test >/dev/null 2>&1
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' nobet-test-postgres 2>/dev/null)" = healthy ] && break
  sleep 2
done
need "postgres" "$(q 'select 1;')"

docker exec -i nobet-test-postgres psql -U nobet -d nobet -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
CREATE ROLE $ROL WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
     PASSWORD '$APAROLA';
GRANT CONNECT ON DATABASE nobet TO $ROL;
REVOKE CREATE ON SCHEMA public FROM $ROL;
SQL
chk "rol acildi" 1 "$(q "select count(*) from pg_roles where rolname='$ROL';")"

export TEST_APP_USER="$ROL" TEST_APP_PASSWORD="$APAROLA"
docker compose -f compose.test.yml up -d api-test >/dev/null 2>&1
for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' $B/../../health)" = 200 ] && break
  sleep 2
done

echo
echo "=== 1) ROL SUPER DEGIL ==="
chk "rolsuper" f "$(q "select rolsuper from pg_roles where rolname='$ROL';")"
chk "rolcreatedb" f "$(q "select rolcreatedb from pg_roles where rolname='$ROL';")"
chk "rolcreaterole" f "$(q "select rolcreaterole from pg_roles where rolname='$ROL';")"
chk "⭐ sahip oldugu tablo sayisi" 0 \
    "$(q "select count(*) from pg_tables where schemaname='public' and tableowner='$ROL';")"

echo
echo "=== 2) MIGRATION sahip rolle kostu ==="
chk "sema surumu" "$SEMA_BASI" "$(q 'select version_num from alembic_version;')"
chk "tablolarin sahibi hala nobet" 0 \
    "$(q "select count(*) from pg_tables where schemaname='public' and tableowner<>'nobet';")"

echo
echo "=== 3) UYGULAMA CALISIYOR (yetki daraltmasi isi bozmadi) ==="
chk "/health" 200 "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)"
docker compose -f compose.test.yml run --rm -e BOOTSTRAP_EMAIL=admin@nobet-test.com \
  -e BOOTSTRAP_PASSWORD=TestAdminParola2026x -e BOOTSTRAP_ROLE=kurum_admin \
  api-test python -m app.bootstrap >/dev/null 2>&1
TK=$(curl -s -X POST "$B/auth/login" -H 'Content-Type: application/json' \
     -d '{"email":"admin@nobet-test.com","password":"TestAdminParola2026x"}' \
     | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
need "jeton" "$TK"
ok "giris yapildi (okuma+yazma zinciri calisiyor)"
A=(-H "Authorization: Bearer $TK" -H 'Content-Type: application/json')
chk "listeleme (SELECT)" 200 "$(curl -s -o /dev/null -w '%{http_code}' "${A[@]}" "$B/persons?size=1")"
chk "kayit acma (INSERT)" 201 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${A[@]}" "$B/persons" \
       -d '{"full_name":"Yetki Testi","person_type":"student"}')"
PID=$(q "select id from person where full_name='Yetki Testi';")
chk "guncelleme (UPDATE)" 200 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "${A[@]}" "$B/persons/$PID" \
       -d '{"grade":"11-A"}')"

echo
echo "=== 4) ⭐ YAPAMAMASI GEREKENLER ==="
red "tablo yaratma"          "create table sizinti (x int);"
red "tablo dusurme"          "drop table person;"
red "sutun ekleme"           "alter table person add column x int;"
red "sema surumu degistirme" "update alembic_version set version_num='0001';"
red "olay silme"             "delete from event;"
red "olay degistirme"        "update event set effective_ts = now();"
case "$(qa "copy (select 1) to program 'id';")" in
  *"superuser"*|*"denied"*|*"permission"*) ok "COPY TO PROGRAM (komut calistirma) REDDEDILDI";;
  *) no "COPY TO PROGRAM IZIN VERILDI (!)";;
esac
case "$(qa "select rolpassword from pg_authid limit 1;")" in
  *"denied"*|*"permission"*) ok "pg_authid (parola ozetleri) OKUNAMIYOR";;
  *) no "pg_authid okunabiliyor (!)";;
esac

echo
echo "=== 5) SONRAKI migration'lar da kapsanir (default privileges) ==="
q "create table gelecek_tablo (x int);" >/dev/null
chk "yeni tabloya SELECT otomatik verildi" t \
    "$(q "select has_table_privilege('$ROL','gelecek_tablo','SELECT');")"
chk "yeni tabloya INSERT otomatik verildi" t \
    "$(q "select has_table_privilege('$ROL','gelecek_tablo','INSERT');")"
q "drop table gelecek_tablo;" >/dev/null
ok "-> yeni migration sonrasi uygulama 'permission denied' ile dusmez"

echo
echo "=== 6) GERI UYUM: rol tanimsizken eski davranis ==="
chk "POSTGRES_APP_USER bos ise sahip role duser" nobet \
    "$(docker compose -f compose.test.yml run --rm -e POSTGRES_APP_USER= -e POSTGRES_APP_PASSWORD= \
        api-test python -c "
from app.config import settings
print(settings.database_url.split('://')[1].split(':')[0])" 2>/dev/null | tr -d '\r' | tail -1)"

echo
echo "==================== SONUC: $pass gecti, $fail kaldi ===================="
echo "Yigini yok etmek icin: docker compose -f compose.test.yml down -v"
[ "$fail" -eq 0 ]
