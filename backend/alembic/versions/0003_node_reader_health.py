"""node tablosuna okuyucu sağlığı alanları

Kontrat v1.2 (§2.4): heartbeat artık `rdr` ve `rdr_reinit` taşıyor.

Gerekçe: RC522 askıda kalabiliyor — SPI cevap verirken RF alanı sessizce
kapanıyor. Düğüm ağa bağlı, heartbeat düzenli, panel `online`, ama hiçbir
kart okunmuyor. Bu alanlar olmadan arıza görünmez.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Varsayılan true: mevcut düğümler aksi bildirilene kadar sağlıklı sayılır.
    # Eski firmware `rdr` göndermiyor; alan NULL kalırsa "bilinmiyor" demektir,
    # bu yüzden nullable bırakılıyor.
    op.add_column("node", sa.Column("reader_ok", sa.Boolean(), nullable=True))
    op.add_column(
        "node",
        sa.Column("reader_reinits", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("COMMENT ON COLUMN node.reader_ok IS "
               "'hb.rdr (kontrat v1.2). NULL = firmware bildirmiyor.'")
    op.execute("COMMENT ON COLUMN node.reader_reinits IS "
               "'hb.rdr_reinit — okuyucunun kac kez yeniden baslatildigi.'")


def downgrade() -> None:
    op.drop_column("node", "reader_reinits")
    op.drop_column("node", "reader_ok")
