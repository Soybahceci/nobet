"""bildirim ayarları (kanal + SMS sağlayıcı)

Kanal ve sağlayıcı bilgileri artık `.env` yerine veritabanında: kurum
bunları ARAYÜZDEN değiştirebilmeli ("sıfır CLI" kuralı). `.env` düzenleyip
konteyner yeniden başlatmak kurum personelinin yapabileceği bir iş değil.

Kimlik bilgileri `secret_enc` içinde **şifreli** tutulur. Düz metin API
anahtarı, veritabanı yedeği sızdığında doğrudan kötüye kullanılabilir.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notify_setting",
        # Kurum başına tek satır
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        # "dryrun" | "whatsapp" | "sms"
        sa.Column("channel", sa.Text, nullable=False, server_default="dryrun"),
        # "netgsm" | "iletimerkezi" | "verimor" | "mutlucell" | "vatansms" | "generic"
        sa.Column("sms_provider", sa.Text),
        # Sır OLMAYAN yapılandırma: URL, yöntem, alan adları, gönderici başlığı.
        # Görünür ve düzenlenebilir olmalı — sağlayıcı API'sini değiştirirse
        # kod değil ayar güncellenir.
        sa.Column("sms_config", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        # Kullanıcı adı/parola/API anahtarı — Fernet ile şifreli
        sa.Column("secret_enc", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="SET NULL")),
    )
    op.execute("COMMENT ON COLUMN notify_setting.secret_enc IS "
               "'Fernet ile sifreli. SETTINGS_KEY olmadan cozulemez.'")


def downgrade() -> None:
    op.drop_table("notify_setting")
