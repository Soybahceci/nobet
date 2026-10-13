#!/usr/bin/env bash
# Gecikmeli bildirim damgasi (kullanici karari 2026-08-14)
#
# Kanitlanacak sey: bildirim gec gidiyorsa veli bunu ILK SATIRDAN anliyor ve
# olayin gercek saatini goruyor. Zamaninda giden bildirim ise DEGISMIYOR --
# her mesaji "gecikmeli" diye damgalamak damgayi anlamsizlastirirdi.
#
# TEK KULLANIMLIK yiginda kosar (8090). Uretimde CALISTIRMAYIN.
set -uo pipefail
pass=0; fail=0
ok(){ echo "   [OK]   $1"; pass=$((pass+1)); }
no(){ echo "   [HATA] $1"; fail=$((fail+1)); }
chk(){ [ "$2" = "$3" ] && ok "$1 ($3)" || no "$1 bekleniyordu=$2 gelen=$3"; }

cd "$(dirname "$0")/.."
SEMA_BASI=$(ls backend/alembic/versions/ | sed "s/_.*//" | sort -n | tail -1)
q(){ docker exec nobet-test-postgres psql -U nobet -d nobet -tA -c "$1" 2>&1 | head -1 | tr -d '\r'; }

echo "=== zemin ==="
docker compose -f compose.test.yml down -v >/dev/null 2>&1
docker compose -f compose.test.yml up -d >/dev/null 2>&1
for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)" = 200 ] && break
  sleep 2
done
chk "sema surumu" "$SEMA_BASI" "$(q 'select version_num from alembic_version;')"
chk "occurred_at sutunu acildi" 1 \
    "$(q "select count(*) from information_schema.columns where table_name='notification' and column_name='occurred_at';")"

echo
echo "=== 1) METIN URETIMI (saf fonksiyon) ==="
docker compose -f compose.test.yml run --rm api-test python - <<'PY'
import datetime as dt
from app.notify import apply_delay_notice, _sure_metni, GECIKME_ESIGI

taban = ("Ornek Dershanesi\n"
         "Ahmet Yilmaz, 13.08.2026 21:47 itibariyla Ana Giris "
         "noktasindan giris yapti.\n\n"
         "Bu bilgilendirme mesaji otomatik gonderilmistir.")

g = apply_delay_notice(taban, dt.timedelta(hours=9, minutes=7))
print("---DAMGALI---"); print(g); print("---SON---")

s = []
s.append(("ilk satir damgali", g.startswith("GECIKMELI BILDIRIM ·".replace("I","İ").replace("GEC","GEÇ"))
          or g.startswith("GECİKMELİ BİLDİRİM · ")))
s.append(("kurum adi korundu", "Ornek Dershanesi" in g.split("\n")[0]))
s.append(("olayin saati duruyor", "13.08.2026 21:47" in g))
s.append(("gecikme suresi yazili", "9 saat 7 dakika" in g))
s.append(("emoji yok (SMS ucreti)", g.isascii() or all(ord(c) < 0x2190 for c in g)))

# Fikir sabitligi: yeniden denemede damga ust uste binmemeli
iki = apply_delay_notice(g, dt.timedelta(hours=9, minutes=30))
s.append(("iki kez uygulanca tek baslik", iki.count("GECİKMELİ BİLDİRİM") == 1))
s.append(("iki kez uygulanca tek aciklama", iki.count("gecikmeyle iletilmistir.")
          + iki.count("gecikmeyle iletilmiştir.") == 1))
s.append(("yeniden denemede sure guncellendi", "9 saat 30 dakika" in iki))

s.append(("sure metni: dakika", _sure_metni(dt.timedelta(minutes=8)) == "8 dakika"))
s.append(("sure metni: saat+dakika", _sure_metni(dt.timedelta(hours=2, minutes=15)) == "2 saat 15 dakika"))
s.append(("sure metni: tam saat", _sure_metni(dt.timedelta(hours=3)) == "3 saat"))
s.append(("sure metni: gun", _sure_metni(dt.timedelta(days=1, hours=3)) == "1 gun 3 saat"
          or _sure_metni(dt.timedelta(days=1, hours=3)) == "1 gün 3 saat"))
s.append(("esik 5 dakika", GECIKME_ESIGI == dt.timedelta(minutes=5)))

for ad, sonuc in s:
    print(("PASS " if sonuc else "FAIL ") + ad)
PY

echo
echo "=== 2) UCTAN UCA: gecikmis bildirim damgalanir ==="
# Kurum + ogrenci + veli + ESKI tarihli bildirim kur, sonra kuyrugu bosalt.
docker compose -f compose.test.yml run --rm -e BOOTSTRAP_EMAIL=a@nobet-test.com \
  -e BOOTSTRAP_PASSWORD=TestAdminParola2026x -e BOOTSTRAP_ROLE=kurum_admin \
  -e BOOTSTRAP_TENANT_SLUG=kurum-a -e BOOTSTRAP_TENANT_NAME="Kurum A" \
  api-test python -m app.bootstrap >/dev/null 2>&1

docker compose -f compose.test.yml run --rm api-test python - <<'PY'
import asyncio, datetime as dt
from sqlalchemy import select
from app.db import SessionLocal
from app import notify
from app.models import (Tenant, Person, Guardian, PersonGuardian, AttendanceSession, Zone, ZoneKind, AppUser,
                        SessionState, Notification, NotificationChannel,
                        NotificationStatus)

async def main():
    async with SessionLocal() as db:
        t = (await db.execute(select(Tenant))).scalars().first()
        u = (await db.execute(select(AppUser))).scalars().first()
        p = Person(tenant_id=t.id, full_name="Ahmet Yilmaz", person_type="student",
                   birth_date=dt.date(2012, 5, 1))     # 18 yas alti
        db.add(p); await db.flush()
        g = Guardian(tenant_id=t.id, full_name="Veli Yilmaz", phone="+905551112233")
        db.add(g); await db.flush()
        db.add(PersonGuardian(person_id=p.id, guardian_id=g.id, relation="anne",
                             notify_enabled=True))
        await db.flush()

        simdi = dt.datetime.now(dt.timezone.utc)
        # Biri 9 saat once olmus (tampon bosaldi), biri az once.
        for etiket, gecmis in (("ESKI", dt.timedelta(hours=9)), ("YENI", dt.timedelta(seconds=30))):
            olay = simdi - gecmis
            # `notification` kaynagindan TAM BIRI dolu olmali (event_id ya da
            # session_id). Burada oturum yolunu kullaniyoruz.
            # Her olay icin ayri mekan: acik oturum (kisi, mekan) basina tek.
            z = Zone(tenant_id=t.id, name=f"Ana Giris {etiket}", kind=ZoneKind.entrance)
            db.add(z); await db.flush()
            oturum = AttendanceSession(tenant_id=t.id, person_id=p.id,
                                       entered_at=olay, zone_id=z.id, entry_source="manual", created_by=u.id,
                                       state=SessionState.open)
            db.add(oturum); await db.flush()
            db.add(Notification(
                tenant_id=t.id, person_id=p.id, guardian_id=g.id,
                session_id=oturum.id,
                direction="GİRİŞ", channel=NotificationChannel.dryrun,
                recipient=g.phone, occurred_at=olay,
                body=notify.build_body(student=f"{etiket} Ahmet", zone_name="Ana Giris",
                                       direction="GİRİŞ", when=olay,
                                       tz_name=t.timezone, institution=t.name),
            ))
        await db.commit()

        await notify.flush_pending(db, channel=notify.DryRunChannel())
        await db.commit()

        for n in (await db.execute(select(Notification))).scalars().unique().all():
            etiket = "ESKI" if "ESKI" in n.body else "YENI"
            damga = n.body.startswith("GECİKMELİ BİLDİRİM")
            print(f"{etiket} damgali={damga} durum={n.status.value}")
            if etiket == "ESKI":
                print("PASS eski bildirim damgalandi" if damga else "FAIL eski bildirim DAMGASIZ")
                print("PASS eski: gecikme suresi yazili" if "9 saat" in n.body
                      else "FAIL eski: gecikme suresi yok")
            else:
                print("PASS yeni bildirim damgasiz" if not damga else "FAIL yeni bildirim DAMGALANDI (!)")

asyncio.run(main())
PY

echo
echo "==================== Yukarida FAIL satiri OLMAMALI ===================="
echo "Yigini yok etmek icin: docker compose -f compose.test.yml down -v"
