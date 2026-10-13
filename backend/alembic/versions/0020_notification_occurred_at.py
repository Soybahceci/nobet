"""bildirime olayın gerçek zamanı — gecikmeli bildirim damgası için

Kullanıcı kararı 2026-08-14: bildirim geç gidiyorsa veli bunu **mesajın ilk
satırından** anlamalı ve olayın gerçek saatini görmeli.

`created_at` bu işi göremez: bildirim, olayı öğrendiğimiz anda üretiliyor.
Düğüm 9 saatlik bir kesintinin ardından tamponunu boşalttığında bildirim
o anda doğar — `created_at` "şimdi" der, oysa çocuk saatler önce girmiştir.
Bu yüzden olayın gerçek zamanı ayrı taşınıyor.

Eski satırlar `NULL` kalır ve damgasız gider. Doğrusu bu: geçmiş
bildirimlerin gecikmesini şimdi uydurmak, hiç damgalamamaktan kötüdür.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notification", "occurred_at")
