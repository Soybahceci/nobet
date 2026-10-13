#!/usr/bin/env bash
# Faz 13b-3b — satir duzeyi guvenlik (mimari §10.8)
#
# Kanitlanacak sey: `WHERE tenant_id` KASTEN unutulmus bir sorgu bile baska
# kurumun satirini dondurmuyor. Bu testin degeri buradan geliyor — uygulama
# kodunun dogru oldugunu degil, YANLIS olsa bile verinin sizmadigini sinar.
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

# sahip rolle (RLS'i FORCE ettigimiz icin sahip de sinirlidir; bagalam bos
# oldugu icin kisitsiz calisir — kurulum sorgulari bununla)
q(){ docker exec nobet-test-postgres psql -U nobet -d nobet -tA -c "$1" 2>&1 | head -1 | tr -d ' \r'; }
# UYGULAMA rolyle, kurum baglami KURULMUS halde
qa(){ docker exec -e PGPASSWORD="$APAROLA" nobet-test-postgres \
        psql -h 127.0.0.1 -U "$ROL" -d nobet -tA \
        -c "SELECT set_config('app.tenant_id','$1',false);" -c "$2" 2>&1 | tail -1 | tr -d ' \r'; }

cd "$(dirname "$0")/.."

# Beklenen sema surumu migration dosyalarindan okunur — her yeni
# migration'da bu betigi elle guncellemek gerekmesin diye.
SEMA_BASI=$(ls backend/alembic/versions/ | sed "s/_.*//" | sort -n | tail -1)

echo "=== zemin: sifirdan yigin, rol api'den ONCE ==="
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
export TEST_APP_USER="$ROL" TEST_APP_PASSWORD="$APAROLA"
docker compose -f compose.test.yml up -d api-test >/dev/null 2>&1
for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)" = 200 ] && break
  sleep 2
done
chk "sema surumu" "$SEMA_BASI" "$(q 'select version_num from alembic_version;')"

echo
echo "=== 1) RLS ACIK VE ZORLANIYOR ==="
# relforcerowsecurity onemli: FORCE yoksa sahip rol politikalari baypas eder
# ve POSTGRES_APP_USER bos birakilan kurulumda RLS hicbir sey yapmaz.
chk "RLS acik olmayan tablo" 0 "$(q "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relname in ('person','guardian','credential','zone','node','event','attendance_session','edge_device','sync_state','subscription','membership','notification','wa_thread','notify_setting','lesson','tenant') and not c.relrowsecurity;")"
chk "FORCE edilmemis tablo" 0 "$(q "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relname in ('person','guardian','credential','zone','node','event','attendance_session','edge_device','sync_state','subscription','membership','notification','wa_thread','notify_setting','lesson','tenant') and not c.relforcerowsecurity;")"
chk "politika sayisi" 16 "$(q "select count(*) from pg_policies where schemaname='public' and policyname='kurum_yalitimi';")"

echo
echo "=== zemin: IKI kurum, ikisinde de kisi ==="
docker compose -f compose.test.yml run --rm -e BOOTSTRAP_EMAIL=a@nobet-test.com \
  -e BOOTSTRAP_PASSWORD=TestAdminParola2026x -e BOOTSTRAP_ROLE=kurum_admin \
  -e BOOTSTRAP_TENANT_SLUG=kurum-a -e BOOTSTRAP_TENANT_NAME="Kurum A" \
  api-test python -m app.bootstrap >/dev/null 2>&1
# ⚠️ bootstrap IKINCI kurumu acmaz (yalnizca hic kurum yokken acar; kurum
# acmak super_admin konsolunun isi). B kurumunu dogrudan ekliyoruz; bootstrap
# artik var olan slug'i bulup yoneticisini ona bagliyor.
q "insert into tenant (id,name,slug,timezone,created_at) values (gen_random_uuid(),'Kurum B','kurum-b','Europe/Istanbul',now());" >/dev/null
docker compose -f compose.test.yml run --rm -e BOOTSTRAP_EMAIL=b@nobet-test.com \
  -e BOOTSTRAP_PASSWORD=TestAdminParola2026x -e BOOTSTRAP_ROLE=kurum_admin \
  -e BOOTSTRAP_TENANT_SLUG=kurum-b -e BOOTSTRAP_TENANT_NAME="Kurum B" \
  api-test python -m app.bootstrap >/dev/null 2>&1
TA=$(q "select id from tenant where slug='kurum-a';")
TB=$(q "select id from tenant where slug='kurum-b';")
need "kurum A" "$TA"; need "kurum B" "$TB"
q "insert into person (id,tenant_id,full_name,person_type,status,created_at) values (gen_random_uuid(),'$TA','A Ogrencisi','student','active',now());" >/dev/null
q "insert into person (id,tenant_id,full_name,person_type,status,created_at) values (gen_random_uuid(),'$TB','B Ogrencisi','student','active',now());" >/dev/null
chk "toplam kisi (baglamsiz, sahip)" 2 "$(q 'select count(*) from person;')"

echo
echo "=== 2) ⭐ SUZGECSIZ SORGU SIZDIRMIYOR ==="
# `WHERE tenant_id` YOK. Uygulama kodundaki en olasi hatanin ta kendisi.
chk "A baglaminda 'select * from person'" 1 "$(qa "$TA" 'select count(*) from person;')"
chk "B baglaminda 'select * from person'" 1 "$(qa "$TB" 'select count(*) from person;')"
chk "A, B'nin kisisini adiyla arasa" 0 \
    "$(qa "$TA" "select count(*) from person where full_name='B Ogrencisi';")"
chk "A, B'nin kurum satirini gorebiliyor mu" 0 \
    "$(qa "$TA" "select count(*) from tenant where id='$TB';")"
chk "A, B'nin uyeliklerini gorebiliyor mu" 0 \
    "$(qa "$TA" "select count(*) from membership where tenant_id='$TB';")"

echo
echo "=== 3) ⭐ BASKA KURUM ADINA YAZAMIYOR (WITH CHECK) ==="
case "$(qa "$TA" "insert into person (id,tenant_id,full_name,person_type,status,created_at) values (gen_random_uuid(),'$TB','Sizinti','student','active',now());")" in
  *"policy"*|*"violat"*) ok "A, B adina INSERT edemedi";;
  *) no "A, B adina satir EKLEYEBILDI (!)";;
esac
chk "-> B'nin kisi sayisi degismedi" 1 "$(qa "$TB" 'select count(*) from person;')"
# UPDATE ile satiri karsi kuruma TASIMA denemesi
qa "$TA" "update person set tenant_id='$TB' where full_name='A Ogrencisi';" >/dev/null
chk "A, kendi satirini B'ye tasiyamadi" 1 "$(qa "$TA" 'select count(*) from person;')"

echo
echo "=== 4) BAGLAM DEGERLERI ==="
chk "'*' (super_admin) hepsini gorur" 2 "$(qa '*' 'select count(*) from person;')"
chk "'' (giris/alim hatti) kisitsiz" 2 "$(qa '' 'select count(*) from person;')"
# Bu ikisi kasitli birer muafiyet; sessizce olusmadiklarini burada sabitliyoruz
ok "-> ikisi de kasitli muafiyet (bkz. migration 0019 basligi)"

echo
echo "=== 5) UYGULAMA UCTAN UCA CALISIYOR ==="
lg(){ curl -s -X POST "$B/auth/login" -H 'Content-Type: application/json' \
      -d "{\"email\":\"$1\",\"password\":\"TestAdminParola2026x\"}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))'; }
KA=$(lg a@nobet-test.com); KB=$(lg b@nobet-test.com)
need "A jetonu" "$KA"; need "B jetonu" "$KB"
ok "iki kurumun yoneticisi de giris yapabildi (RLS girisi kirmadi)"
say(){ curl -s -H "Authorization: Bearer $1" "$B/persons?size=50" \
       | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d.get("items",d) if isinstance(d,dict) else d))'; }
chk "A panelde 1 kisi gorur" 1 "$(say "$KA")"
chk "B panelde 1 kisi gorur" 1 "$(say "$KB")"
chk "A, B'nin kisisini ID ile cekemez" 404 \
    "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KA" \
       "$B/persons/$(q "select id from person where full_name='B Ogrencisi';")")"
chk "kisi ekleme hala calisiyor" 201 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $KA" \
       -H 'Content-Type: application/json' "$B/persons" \
       -d '{"full_name":"RLS Sonrasi","person_type":"student"}')"
chk "-> eklenen satir A'ya yazildi" 2 "$(qa "$TA" 'select count(*) from person;')"

echo
echo "=== 6) HAVUZA SIZMA YOK ==="
# SET LOCAL islem yerel; baglanti havuza donunce iz kalmamali. Ust uste
# istekler farkli kurumlarla kosuluyor, sirayla dogru cevabi vermeliler.
sizinti=0
for _ in 1 2 3; do
  [ "$(say "$KB")" = 1 ] || sizinti=1
  [ "$(say "$KA")" = 2 ] || sizinti=1
done
chk "donusumlu istekler (A/B/A/B...) tutarli" 0 "$sizinti"

echo
echo "==================== SONUC: $pass gecti, $fail kaldi ===================="
echo "Yigini yok etmek icin: docker compose -f compose.test.yml down -v"
[ "$fail" -eq 0 ]
