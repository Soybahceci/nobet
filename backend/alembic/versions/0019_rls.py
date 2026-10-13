"""satır düzeyi güvenlik — kurum yalıtımı veritabanına iniyor (Faz 13b-3b)

Mimari: docs/nobet-faz13-saas-mimarisi.md §10.8

Bugüne kadar kurum yalıtımı YALNIZCA uygulama kodundaydı: her sorguya elle
`WHERE tenant_id = ...` yazılıyor. 100'den fazla yerde. Bir tanesinin bir gün
unutulması an meselesi ve unutulduğunda belirtisi yok — uç çalışır, sadece
başka kurumun verisini de döndürür. SaaS'ta bu, tek bir satırlık ihmalin
"kurumlar birbirinin öğrencisini görüyor" hâline gelmesi demek.

Bu migration aynı kuralı veritabanına koyar. Uç `tenant_id` süzgecini
unutursa sonuç **boş** döner, başka kurumun verisi değil.

⭐ **Neden ancak şimdi:** 0018'e kadar uygulama tabloların SAHİBİ olan süper
kullanıcıyla bağlanıyordu ve PostgreSQL'de **sahip ve süper kullanıcı RLS'i
baypas eder.** O sırada yazılacak politikalar tek satır bile süzmezdi.

---

**Üç durumlu bağlam.** Politikalar `app.tenant_id` oturum değişkenine bakar:

    ""    kısıtlama yok — kurum henüz çözülmemiş meşru yollar: giriş
          (kimlik hangi kuruma üye, bilinmiyor), MQTT alım hattı,
          bootstrap ve migration'ların kendisi
    uuid  yalnızca o kurum
    "*"   super_admin — işletmeci konsolu tanım gereği kurumlar arası

Boşun "her şey" demesi kapı gibi görünüyor ama bu katman **ikinci sıra
savunma**: birinci sıra hâlâ uçlardaki süzgeç. Boşu "hiçbir şey" yapmak
girişi kırardı ve kazanç, kapanmayan bir kapı değil, kapanan bir uygulama
olurdu. Değişkeni `app.db.set_tenant_scope` kurar.

**FORCE neden var:** `POSTGRES_APP_USER` boş bırakılan bir kurulumda
uygulama yine sahip rolle bağlanır (0018'deki geri uyum). FORCE olmasaydı
o kurulumda RLS sessizce hiçbir şey yapmazdı — en çok korumaya ihtiyaç
duyan yapılandırma, korumasız kalan yapılandırma olurdu.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

# Kurum sütunu taşıyan her tablo. `app_user` KASITLI olarak yok: kimlik
# kurumlar üstüdür (bir kişi birden fazla kuruma üye olabilir, §3b).
# Kimliğin kuruma bağlanması `membership` üzerindendir ve o liste dahil.
TENANT_TABLES = [
    "person",
    "guardian",
    "credential",
    "zone",
    "node",
    "event",
    "attendance_session",
    "edge_device",
    "sync_state",
    "subscription",
    "membership",
    "notification",
    "wa_thread",
    "notify_setting",
    "lesson",
]

# `tenant` tablosunda sütunun adı `tenant_id` değil `id`.
OWN_ID_TABLES = ["tenant"]

# ⚠️ CASE şart. `current_setting(...)::uuid` boş metinde hata verir ve SQL'de
# OR'un kısa devre yapacağı garanti DEĞİLDİR — planlayıcı koşulları istediği
# sırada değerlendirebilir. CASE'in dal seçimi ise tanımlı.
_FN = """
CREATE OR REPLACE FUNCTION app_tenant_ok(satirin_kurumu uuid)
RETURNS boolean AS $$
    SELECT CASE coalesce(current_setting('app.tenant_id', true), '')
        WHEN ''  THEN true
        WHEN '*' THEN true
        ELSE satirin_kurumu = current_setting('app.tenant_id')::uuid
    END
$$ LANGUAGE sql STABLE;
"""


def upgrade() -> None:
    op.execute(_FN)

    for table, col in [(t, "tenant_id") for t in TENANT_TABLES] + [
        (t, "id") for t in OWN_ID_TABLES
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS kurum_yalitimi ON {table};")
        # USING okumayı/güncellemeyi, WITH CHECK yazmayı süzer. İkisi de
        # gerekli: yalnızca USING olsaydı uygulama BAŞKA kurumun adına
        # satır EKLEYEBİLİRDİ (eklediğini sonra göremeden).
        op.execute(
            f"""
            CREATE POLICY kurum_yalitimi ON {table}
                USING (app_tenant_ok({col}))
                WITH CHECK (app_tenant_ok({col}));
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES + OWN_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS kurum_yalitimi ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS app_tenant_ok(uuid);")
