"""kimlik ile üyelik ayrılıyor — tek hesap, çok kurum (Faz 13a-0)

Karar: `docs/nobet-faz13-saas-mimarisi.md` §3b. Denetim bulgusu P-1.

ÖNCE:
    app_user(id, tenant_id, person_id, email UNIQUE, password_hash, role, …)
    → e-posta global benzersiz; aynı kişi iki kurumda var olamıyor.
    → B kurumu A'da kayıtlı e-postayla hesap açmaya kalkınca 409 alıyor,
      yani kişinin başka kurumda olduğu sızıyor.

SONRA:
    app_user(id, email UNIQUE, password_hash, …)          ← KİMLİK
    membership(user_id, tenant_id, role, person_id, …)    ← ÜYELİK
    UNIQUE(user_id, tenant_id)

`tenant_id`, `role`, `person_id` app_user'dan membership'e taşınır.

⚠️ VERİ TAŞIMA: mevcut her app_user satırı için birebir bir membership
satırı üretilir. Kimse hesabını kaybetmez, kimsenin rolü değişmez.
Bugünkü kurulumda her kullanıcının tek kurumu var, dolayısıyla taşıma
kayıpsızdır.

Kolonlar app_user'dan **düşürülür**; yarı taşınmış bir şema en kötüsü olurdu
(iki yerde rol, hangisi doğru?). Geri alma yolu downgrade'de yazılı.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# app_role enum'u zaten var (0001 baseline); yeniden yaratılmamalı.
_app_role = postgresql.ENUM(name="app_role", create_type=False)


def upgrade() -> None:
    op.create_table(
        "membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("person.id"), nullable=True),
        sa.Column("role", _app_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Bir kişi bir kurumda en fazla bir üyeliğe sahip olur.
        sa.UniqueConstraint("user_id", "tenant_id", name="membership_user_tenant_unique"),
    )
    op.create_index("membership_tenant_idx", "membership", ["tenant_id"])
    op.create_index("membership_user_idx", "membership", ["user_id"])

    # --- veri taşıma: her hesap için birebir üyelik --------------------------
    # `is_active` hesaptan üyeliğe kopyalanır. Kimlik seviyesindeki is_active
    # de kalır: hesabın tamamen kapatılması ile tek kurumdaki üyeliğin
    # kapatılması farklı şeyler.
    op.execute(
        """
        INSERT INTO membership (user_id, tenant_id, person_id, role, is_active, created_at)
        SELECT id, tenant_id, person_id, role, is_active, COALESCE(created_at, now())
        FROM app_user
        """
    )

    # --- kolonları app_user'dan düşür ---------------------------------------
    op.drop_column("app_user", "role")
    op.drop_column("app_user", "person_id")
    op.drop_column("app_user", "tenant_id")


def downgrade() -> None:
    """
    Geri alma: kolonlar geri konur ve **en eski** üyelikten doldurulur.

    ⚠️ Birden fazla kuruma üye olmuş bir kullanıcı varsa geri alma
    KAYIPLIDIR — yalnızca ilk üyeliği korunur, diğerleri düşer. Global
    benzersiz e-postaya dönmenin başka yolu yok; zaten bu migration'ın
    varlık sebebi o kısıtın kalkması.
    """
    op.add_column("app_user", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("app_user", sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("app_user", sa.Column("role", _app_role, nullable=True))

    op.execute(
        """
        UPDATE app_user u SET
            tenant_id = m.tenant_id,
            person_id = m.person_id,
            role      = m.role
        FROM (
            SELECT DISTINCT ON (user_id) user_id, tenant_id, person_id, role
            FROM membership ORDER BY user_id, created_at
        ) m
        WHERE m.user_id = u.id
        """
    )
    # Üyeliği hiç olmayan hesap kalırsa NOT NULL konamaz; böyle satırlar
    # anlamsızdır (hiçbir kuruma bağlı olmayan hesap), silinir.
    op.execute("DELETE FROM app_user WHERE tenant_id IS NULL")

    op.alter_column("app_user", "tenant_id", nullable=False)
    op.alter_column("app_user", "role", nullable=False)
    op.create_foreign_key("app_user_tenant_id_fkey", "app_user", "tenant", ["tenant_id"], ["id"])
    op.create_foreign_key("app_user_person_id_fkey", "app_user", "person", ["person_id"], ["id"])

    op.drop_index("membership_user_idx", table_name="membership")
    op.drop_index("membership_tenant_idx", table_name="membership")
    op.drop_table("membership")
