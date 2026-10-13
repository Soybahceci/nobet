"""giriş kaba kuvvet koruması (denetim bulgusu Y-2)

Ölçüm: 12 ardışık yanlış parola, hepsi 401, her biri ~0.22 sn, kilitleme
yok. argon2id maliyeti çevrimdışı saldırıya karşı iyi ama çevrimiçi
saldırıya karşı yeterli değil; panel Faz 13f'te internete çıkıyor.

Sayaç **e-postaya** göre tutulur ve hesabın var olup olmadığına bakılmaz.
Yalnızca var olan hesaplar kilitlenseydi, kilitlenmenin kendisi "bu e-posta
kayıtlı" bilgisini sızdırırdı — `/auth/forgot`'ta özenle kaçınılan
sızıntının aynısı giriş ucundan çıkardı. Bu yüzden ayrı bir tablo; app_user
üzerinde kolon DEĞİL.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempt",
        # E-posta birincil anahtar: kayıt başına tek satır, yarış yok.
        sa.Column("email", sa.Text(), primary_key=True),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    # Bakım/temizlik sorguları için: eskimiş kayıtlar süpürülebilsin.
    op.create_index("login_attempt_last_idx", "login_attempt", ["last_attempt_at"])


def downgrade() -> None:
    op.drop_index("login_attempt_last_idx", table_name="login_attempt")
    op.drop_table("login_attempt")
