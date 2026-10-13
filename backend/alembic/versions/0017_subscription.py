"""abonelik ve kesinti kademeleri (Faz 13b-1)

Mimari §5. Ürün aylık abonelikli SaaS olarak satılacak; ödenmemiş faturada
hizmet kademeli olarak kısılır.

⭐ **§5.1 — kurumun kendi kaydı hiçbir aşamada durdurulmaz.**
SaaS'ta işletmeci *veri işleyen*, kurum *veri sorumlusu*. Devam kayıtları
hukuken kuruma ait. Ödenmemiş fatura yüzünden kayıt tutmayı durdurmak, o
dönemin verisini kalıcı olarak yok eder — faturadan çok daha büyük bir sorun
doğurur. **Kesilen şey hizmettir, veri değil.**

Kademeler (§5.2):

    active      panel ✅   veli ✅   SMS ✅   kenar ✅
    warning     panel ✅   veli ✅   SMS ✅   kenar ✅   (+ bandrol)
    restricted  panel salt-okunur   veli ❌   SMS ❌   kenar ✅ kayıt sürer
    suspended   panel ❌   veli ❌   SMS ❌   kenar ✅ kuyrukta biriktirir

SMS ilk kesilir çünkü işletmecinin cebinden çıkar; kaldıraç orada.

---

⚠️ **Mimari §8'den KASITLI SAPMA.** Orada durum hem `tenant.status` hem
`subscription` tablosunda öngörülmüştü. Aynı gerçeği iki yerde tutmak, er
geç birbirini tutmayan iki cevap üretir. Durum **yalnızca `subscription`**
tablosunda; `tenant` dokunulmadan kaldı.

Her kurumun satırı olması garanti: `tenant` üzerine tohumlama tetikleyicisi
konuyor (0014'teki `sync_state` ile aynı desen). Satırı olmayan kurum
"durumu bilinmiyor" belirsizliği yaratırdı.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        # PG enum yerine text+CHECK: enum'a değer eklemek migration'da
        # zahmetli, kademe listesi ileride genişleyebilir.
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        # SMS gerçek para (§5.3). Kota aşılırsa bildirim durur, panel uyarır.
        # 0 = sınırsız (işletmecinin kendi kurumu, pilot vb.)
        sa.Column("sms_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sms_used", sa.Integer(), nullable=False, server_default="0"),
        # Kademeyi kim, neden değiştirdi — para konusudur, izsiz olmaz.
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("suspended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_check_constraint(
        "subscription_status_valid",
        "subscription",
        "status IN ('active','warning','restricted','suspended')",
    )
    op.create_index("subscription_status_idx", "subscription", ["status"])

    # Var olan kurumlar
    op.execute("INSERT INTO subscription (tenant_id) SELECT id FROM tenant")

    # Sonradan açılan kurumlar da satırını almalı — satırsız kurum
    # "durumu bilinmiyor" belirsizliği yaratır. 0014'teki sync_state ile
    # aynı desen; kurum yaratmanın tek bir kod yolu yok.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION nobet_seed_subscription() RETURNS trigger AS $$
        BEGIN
            INSERT INTO subscription (tenant_id) VALUES (NEW.id)
            ON CONFLICT (tenant_id) DO NOTHING;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # ⚠️ Fonksiyon ve tetikleyici AYRI op.execute olmalı — asyncpg tek
    # hazırlanmış ifadeye birden fazla komut koyduramıyor (0014'te öğrenildi).
    op.execute(
        """
        CREATE TRIGGER tenant_seed_subscription
        AFTER INSERT ON tenant
        FOR EACH ROW EXECUTE FUNCTION nobet_seed_subscription();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tenant_seed_subscription ON tenant")
    op.execute("DROP FUNCTION IF EXISTS nobet_seed_subscription()")
    op.drop_index("subscription_status_idx", table_name="subscription")
    op.drop_table("subscription")
