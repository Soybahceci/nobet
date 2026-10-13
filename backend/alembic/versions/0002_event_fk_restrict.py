"""event yabancı anahtarları SET NULL -> RESTRICT

Gerekçe: `event` tablosu değişmezdir ve UPDATE'i trigger ile engellenir.
`ON DELETE SET NULL`, silme anında PostgreSQL'in event satırını
GÜNCELLEMEYE çalışmasına yol açıyor; trigger bunu reddedince silme
anlaşılmaz bir hatayla düşüyordu. RESTRICT ile niyet açık hâle gelir:
kullanılmış kart/kişi silinmez, `status` ile iptal edilir (kontrat §1.2).

Faz 5 uçtan uca testinde bulundu (2026-08-08).

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("event_credential_id_fkey", "event", type_="foreignkey")
    op.create_foreign_key(
        "event_credential_id_fkey", "event", "credential",
        ["credential_id"], ["id"], ondelete="RESTRICT",
    )
    op.drop_constraint("event_person_id_fkey", "event", type_="foreignkey")
    op.create_foreign_key(
        "event_person_id_fkey", "event", "person",
        ["person_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("event_credential_id_fkey", "event", type_="foreignkey")
    op.create_foreign_key(
        "event_credential_id_fkey", "event", "credential",
        ["credential_id"], ["id"], ondelete="SET NULL",
    )
    op.drop_constraint("event_person_id_fkey", "event", type_="foreignkey")
    op.create_foreign_key(
        "event_person_id_fkey", "event", "person",
        ["person_id"], ["id"], ondelete="SET NULL",
    )
