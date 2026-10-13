"""baseline — mevcut şemayı damgala

`infra/postgres/init/01-schema.sql` ile oluşturulan şema bu revizyona
karşılık gelir. Yeni bir veritabanında init betiği çalışır, ardından
`alembic stamp 0001` ile bu nokta işaretlenir. Bundan SONRAKİ tüm şema
değişiklikleri migration olarak yazılır.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline: şema init SQL'i tarafından zaten oluşturuldu.
    pass


def downgrade() -> None:
    # Baseline geri alınamaz — veritabanını yeniden oluşturun.
    pass
