"""WhatsApp sohbet (konuşma + mesaj)

Panelden iki yönlü mesajlaşma ve otomatik yanıtlayıcı için.

Tasarım:
- `wa_thread` telefon numarası başına tek konuşma. `guardian_id` çözülebilirse
  doldurulur; tanınmayan numaralarda NULL kalır ve konuşma "ilgi bekliyor"
  işaretlenir — bu numaralara ASLA öğrenci bilgisi verilmez.
- `wa_message` ham mesaj kaydı. `is_auto` otomatik yanıtı işaretler:
  hangi bilginin makine tarafından verildiği sonradan denetlenebilmeli.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM("in", "out", name="wa_direction").create(
        op.get_bind(), checkfirst=True
    )
    direction = postgresql.ENUM(name="wa_direction", create_type=False)

    op.create_table(
        "wa_thread",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False),
        # Normalize edilmiş numara (yalnızca rakam) — eşleştirme buna göre
        sa.Column("phone", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        # Tanınmayan numarada NULL. Bilgi verilip verilmeyeceğini bu belirler.
        sa.Column("guardian_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("guardian.id", ondelete="SET NULL")),
        sa.Column("needs_attention", sa.Boolean, nullable=False,
                  server_default=sa.text("false")),
        sa.Column("unread_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "phone", name="wa_thread_phone_once"),
    )
    op.create_index("wa_thread_recent_idx", "wa_thread",
                    ["tenant_id", sa.text("last_message_at DESC")])
    op.create_index("wa_thread_attention_idx", "wa_thread", ["tenant_id"],
                    postgresql_where=sa.text("needs_attention"))

    op.create_table(
        "wa_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("wa_thread.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", direction, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        # Otomatik yanıtı işaretler — hangi bilginin makine tarafından
        # verildiği denetlenebilmeli
        sa.Column("is_auto", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sent_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("wa_message_thread_idx", "wa_message",
                    ["thread_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("wa_message")
    op.drop_table("wa_thread")
    op.execute("DROP TYPE IF EXISTS wa_direction")
