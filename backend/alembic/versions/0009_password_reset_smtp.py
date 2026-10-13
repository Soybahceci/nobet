"""parola sıfırlama jetonu + SMTP ayarları (kontrat v1.7)

Sorun: parola yönetiminin tamamı yöneticiye bağlıydı. Kullanıcı parolasını
unutursa yöneticiyi bulmak zorundaydı; yönetici de yeni parolayı **düz metin**
iletmek durumundaydı (WhatsApp'tan, sözlü, kâğıtla). Kullanıcı kendi
parolasını hiç değiştiremiyordu.

Çözüm: e-postayla, tek kullanımlık, süreli jeton.

⚠️ `token_hash` — jetonun KENDİSİ saklanmaz, sha256'sı saklanır. Veritabanını
okuyabilen biri (yedek dosyası, sızıntı, DBA) aksi hâlde bekleyen her jetonla
o hesabı ele geçirebilirdi. Jeton yalnızca e-postada bulunur.

SMTP sırrı için `secret_enc`'ten AYRI bir sütun açıldı: tek alanda tutulsalardı
SMS sağlayıcı sırrını değiştirmek SMTP parolasını silerdi.

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_PURPOSE = postgresql.ENUM("reset", "invite", name="reset_purpose")


def upgrade() -> None:
    _PURPOSE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "password_reset",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        # create_type=False: tip yukarıda elle oluşturuldu, ikinci kez
        # denemesin ("type already exists" hatası 0004'te bu yüzden çıkmıştı)
        sa.Column("purpose", postgresql.ENUM(name="reset_purpose", create_type=False),
                  nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    # Süresi geçmiş/kullanılmış jetonları temizlerken ve kullanıcı başına
    # hız sınırını kontrol ederken taranan yol
    op.create_index("password_reset_user_idx", "password_reset",
                    ["user_id", "created_at"])

    op.execute(
        "COMMENT ON COLUMN password_reset.token_hash IS "
        "'sha256(jeton). Duz metin jeton saklanmaz — yalnizca e-postada bulunur.'"
    )

    for col, type_ in (
        ("smtp_host", sa.Text()),
        ("smtp_port", sa.Integer()),
        ("smtp_security", sa.Text()),
        ("smtp_from", sa.Text()),
        ("smtp_user", sa.Text()),
        ("smtp_secret_enc", sa.Text()),
    ):
        op.add_column("notify_setting", sa.Column(col, type_))

    op.execute(
        "COMMENT ON COLUMN notify_setting.smtp_secret_enc IS "
        "'Fernet ile sifreli SMTP parolasi. secret_enc''ten AYRI: tek alanda "
        "tutulsalardi birini degistirmek digerini silerdi.'"
    )


def downgrade() -> None:
    for col in ("smtp_secret_enc", "smtp_user", "smtp_from",
                "smtp_security", "smtp_port", "smtp_host"):
        op.drop_column("notify_setting", col)
    op.drop_index("password_reset_user_idx", table_name="password_reset")
    op.drop_table("password_reset")
    _PURPOSE.drop(op.get_bind(), checkfirst=True)
