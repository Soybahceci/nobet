"""kenar cihazı şeması (Faz 13a-1)

Mimari: docs/nobet-faz13-saas-mimarisi.md §2.4, §3.2, §8

Üç iş:

1. `node_key` GLOBAL benzersizdi → `UNIQUE (tenant_id, node_key)`.
   Tek kurumda zararsızdı. SaaS'ta her kurumun kapısındaki okuyucu
   `giris-01` adını alacak; global kısıt ikinci kurumu engellerdi.

2. `edge_device` — kurum başına kenar cihazı. Jeton **hash'lenerek**
   saklanır (`password_reset` ile aynı gerekçe: bulut veritabanı sızsa bile
   jetonlarla kenar taklit edilemez). Eşleştirme kodu da öyle.

3. `sync_state` — kart kopyasının kurum başına sürüm sayacı.

⭐ **Kart senkronu: artımlı DEĞİL, anlık görüntü.**
Mimari §3.2 artımlı indirme öngörüyordu. Artımlı olması için her
`credential` satırının kendi sürüm damgası olması ve kişi değişikliklerinin
de o damgayı güncellemesi gerekirdi. 1500 kişilik bir kurumda tam kart
listesi ~100 KB; bu boyutta artımlılık karşılığı olmayan bir karmaşıklık.

Kurum başına **tek sayaç** tutuluyor: kart kopyasını etkileyen her
değişiklikte artıyor. Kenar sayacı farklı görürse listenin tamamını
indiriyor. Protokoldeki `?since=` parametresi duruyor, dolayısıyla ileride
gerçekten artımlıya geçilirse **kenar tarafı hiç değişmez.**

⚠️ Sayaç TETİKLEYİCİ ile artıyor, uygulama katmanında değil. Kart kopyasını
etkileyen yazma noktaları dağınık: kart atama, kart iptali, kişi
pasifleştirme, KVKK anonimleştirme, toplu içe aktarma. Her birinde
"sayacı artırmayı unutma" demek, er geç unutulacak demektir; unutulduğunda
da **kenar bayat kart listesiyle çalışır ve kimse fark etmez.**
Veritabanı seviyesinde tutmak bu hata sınıfını tamamen kapatıyor.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1) node_key artık kurum içinde benzersiz --------------------------
    op.drop_constraint("node_node_key_key", "node", type_="unique")
    op.create_unique_constraint(
        "node_tenant_key_unique", "node", ["tenant_id", "node_key"]
    )

    # --- 2) kenar cihazı ---------------------------------------------------
    op.create_table(
        "edge_device",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),

        # Kalıcı jeton — HASH'İ saklanır, kendisi yalnızca eşleştirme
        # yanıtında bir kez görünür. NULL = henüz eşleşmemiş.
        sa.Column("token_hash", sa.Text(), nullable=True, unique=True),

        # Tek kullanımlık eşleştirme kodu (24 saat). O da hash'li.
        sa.Column("pairing_code_hash", sa.Text(), nullable=True, unique=True),
        sa.Column("pairing_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paired_at", sa.TIMESTAMP(timezone=True), nullable=True),

        # --- kenardan gelen sağlık bilgisi (heartbeat) ---
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("agent_version", sa.Text(), nullable=True),
        # Mimari §10.3(1): sapma > 60 sn ise uyarı. Kenar kendi saatiyle
        # damgaladığı için bu bilgi kritik.
        sa.Column("clock_skew_ms", sa.BigInteger(), nullable=True),
        # §5.2b eşikleri: kuyruk derinliği izlenmezse askıdaki kurumda
        # SD kart sessizce dolar.
        sa.Column("queue_depth", sa.Integer(), nullable=False, server_default="0"),
        # §3.1b: kalıcı reddedilen olaylar. Sıfırdan büyükse panelde uyarı —
        # veri kaybı olabilecek tek yer burası, görünmez olmamalı.
        sa.Column("dead_letter_count", sa.Integer(), nullable=False, server_default="0"),
        # Kenarın gördüğü kart listesi sürümü — bayat mı, panelden görülsün.
        sa.Column("card_version_seen", sa.BigInteger(), nullable=False, server_default="0"),

        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("edge_device_tenant_idx", "edge_device", ["tenant_id"])

    # --- 3) kart kopyası sürüm sayacı --------------------------------------
    op.create_table(
        "sync_state",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("card_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    # Var olan kurumlar için başlangıç satırı (yoksa ilk senkron NULL görür).
    op.execute("INSERT INTO sync_state (tenant_id) SELECT id FROM tenant")

    # ⚠️ SONRADAN açılan kurumlar da satırını almalı. İlk yazımda bu eksikti
    # ve test yakaladı: yeni kurumun `sync_state` satırı, ilk kart
    # değişikliğine kadar hiç oluşmuyordu (aşağıdaki bump tetikleyicisi
    # `ON CONFLICT` ile kendisi yaratıyor). Ölümcül değildi ama
    # `GET /edge/credentials` yeni kurumda satır bulamazdı ve kenar
    # "sürüm yok" durumuyla uğraşmak zorunda kalırdı.
    #
    # Kurum yaratmanın tek bir kod yolu yok (bootstrap, 13b konsolu, testler);
    # bu yüzden yine veritabanı seviyesinde garanti ediliyor.
    # ⚠️ Fonksiyon ve tetikleyici AYRI `op.execute` çağrılarında olmalı.
    # asyncpg tek bir hazırlanmış ifadeye birden fazla komut koyduramıyor
    # ("cannot insert multiple commands into a prepared statement") ve
    # migration yarıda patlar.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION nobet_seed_sync_state() RETURNS trigger AS $$
        BEGIN
            INSERT INTO sync_state (tenant_id) VALUES (NEW.id)
            ON CONFLICT (tenant_id) DO NOTHING;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER tenant_seed_sync_state
        AFTER INSERT ON tenant
        FOR EACH ROW EXECUTE FUNCTION nobet_seed_sync_state();
        """
    )

    # --- 4) sayacı artıran tetikleyici -------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION nobet_bump_card_version() RETURNS trigger AS $$
        DECLARE tid uuid;
        BEGIN
            tid := COALESCE(NEW.tenant_id, OLD.tenant_id);
            INSERT INTO sync_state (tenant_id, card_version, updated_at)
                 VALUES (tid, 1, now())
            ON CONFLICT (tenant_id) DO UPDATE
                    SET card_version = sync_state.card_version + 1,
                        updated_at   = now();
            RETURN NULL;   -- AFTER tetikleyici; dönüş değeri yok sayılır
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Kartın kendisi değişince
    op.execute(
        """
        CREATE TRIGGER credential_bump_card_version
        AFTER INSERT OR UPDATE OR DELETE ON credential
        FOR EACH ROW EXECUTE FUNCTION nobet_bump_card_version();
        """
    )
    # Kişinin kart kopyasına yansıyan alanları değişince.
    # `WHEN` şart: kişinin adresi ya da telefonu değiştiğinde sayacı
    # artırmak, tüm kurumların kart listesini boş yere yeniden indirtirdi.
    op.execute(
        """
        CREATE TRIGGER person_bump_card_version
        AFTER UPDATE ON person
        FOR EACH ROW
        WHEN (OLD.full_name     IS DISTINCT FROM NEW.full_name
           OR OLD.status        IS DISTINCT FROM NEW.status
           OR OLD.anonymized_at IS DISTINCT FROM NEW.anonymized_at)
        EXECUTE FUNCTION nobet_bump_card_version();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tenant_seed_sync_state ON tenant")
    op.execute("DROP FUNCTION IF EXISTS nobet_seed_sync_state()")
    op.execute("DROP TRIGGER IF EXISTS person_bump_card_version ON person")
    op.execute("DROP TRIGGER IF EXISTS credential_bump_card_version ON credential")
    op.execute("DROP FUNCTION IF EXISTS nobet_bump_card_version()")

    op.drop_table("sync_state")
    op.drop_index("edge_device_tenant_idx", table_name="edge_device")
    op.drop_table("edge_device")

    # ⚠️ Geri alma, iki kurumda aynı `node_key` varsa BAŞARISIZ olur —
    # global benzersizlik geri konamaz. Doğrusu da bu: sessizce satır
    # silmektense hata vermek.
    op.drop_constraint("node_tenant_key_unique", "node", type_="unique")
    op.create_unique_constraint("node_node_key_key", "node", ["node_key"])
