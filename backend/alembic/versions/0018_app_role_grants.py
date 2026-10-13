"""uygulama rolune yetki devri — süper kullanıcıdan iniş (Faz 13b-3)

Mimari: docs/nobet-faz13-saas-mimarisi.md §10.8

**Bulgu (2026-08-13, üretim):** uygulama veritabanına `nobet` rolüyle
bağlanıyordu; bu rol `usesuper = t` ve 91 tablonun **sahibi**. Yani API'deki
herhangi bir açık — kapatılan dizin aşımı gibisi — sınırsız veritabanı
yetkisine dönüşürdü: tablo düşürme, tüm kurumların verisini okuma, hatta
`COPY ... TO PROGRAM` ile Pi üzerinde komut çalıştırma.

Ayrım:

    nobet       (sahip, süper)  → yalnızca migration çalıştırır, DDL yapar
    nobet_app   (süper DEĞİL)   → uygulamanın bağlantısı, yalnızca DML

⭐ **Sıra önemli.** Bir sonraki adım olan RLS'in (§10.8b) tek başına hiçbir
değeri yok: PostgreSQL'de **tablo sahibi ve süper kullanıcı RLS'i baypas
eder.** Uygulama sahip rolle bağlıyken satır politikaları yazmak, kilidi
takıp anahtarı kapıda bırakmaktır. Önce bu migration, sonra RLS.

---

**Rol neden burada YARATILMIYOR?** İki sebep:

1. Rol küme (cluster) düzeyinde bir nesnedir, veritabanına ait değil. Bir
   migration'ın kendi veritabanının dışına taşması istenmez.
2. Rolün parolası olur; parola versiyon kontrolüne giremez.

Rolü `infra/nobet-app-rolu-ac.sh` açar. Bu migration yalnızca **yetkileri**
verir ve rol yoksa sessizce atlar — böylece rolü henüz açmamış bir kurulum
(ve tek kullanımlık test yığını) migration'da patlamaz.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

ROLE = "nobet_app"

# ⚠️ Her ifade AYRI op.execute — asyncpg tek hazırlanmış ifadeye birden
# fazla komut koyduramıyor (0014'te öğrenildi). DO bloğu tek komut sayılır,
# içine istediğimiz kadar ifade koyabiliriz.

_GRANT = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        RAISE NOTICE '{ROLE} rolu yok — yetki devri atlandi (bkz. infra/nobet-app-rolu-ac.sh)';
        RETURN;
    END IF;

    GRANT USAGE ON SCHEMA public TO {ROLE};

    -- Uygulama veri yazar, YAPI değiştirmez. CREATE yetkisi bilerek yok:
    -- uygulama rolü kendi tablosunu yaratabilseydi, o tablonun sahibi olur
    -- ve ileride RLS'i o tablo üzerinde baypas ederdi.
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};

    -- Bundan SONRA açılacak tablolar da kapsansın. Yoksa her yeni
    -- migration'dan sonra uygulama "permission denied" ile düşerdi ve
    -- kimse sebebini hatırlamazdı.
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO {ROLE};

    -- --- daraltmalar -------------------------------------------------
    -- `event` değiştirilemez kayıttır (kontrat §2.4). Tetikleyici zaten
    -- DELETE/UPDATE'i reddediyor; yetkiyi de almak ikinci sıra savunma —
    -- tetikleyici bir gün yanlışlıkla düşerse boşluk kalmasın.
    REVOKE DELETE, UPDATE ON event FROM {ROLE};

    -- Şema sürümünü yalnızca migration değiştirir. Uygulamanın buraya
    -- yazması, "hangi sürümdeyiz" sorusunun cevabını güvenilmez kılar.
    REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {ROLE};
END $$;
"""

_REVOKE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        RETURN;
    END IF;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE};
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
    REVOKE USAGE ON SCHEMA public FROM {ROLE};
END $$;
"""


def upgrade() -> None:
    op.execute(_GRANT)


def downgrade() -> None:
    # ⚠️ Geri alma uygulamayı veritabanından KOPARIR. Yalnızca
    # `POSTGRES_APP_USER` ayarı da geri alınacaksa anlamlı.
    op.execute(_REVOKE)
