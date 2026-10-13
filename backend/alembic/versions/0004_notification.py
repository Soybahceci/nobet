"""bildirim kuyruğu (Faz 8)

Kontrat §5 "Bildirim yok → Faz 8" satırının karşılığı. Veri modeline yeni
tablo ekler; mevcut tabloların hiçbiri değişmez.

Tasarım kararı — `UNIQUE (event_id, guardian_id)`:
Aynı olay için aynı veliye ikinci bildirim gönderilemez. İşçi çökse,
yeniden başlasa ya da iki kopya aynı anda çalışsa bile veli mükerrer
mesaj almaz. `UNIQUE(node_id, seq)` ile aynı mantık: idempotency
uygulamaya değil veritabanına yaptırılır.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Tipler ÖNCE ve yalnızca burada oluşturulur.
    postgresql.ENUM(
        "whatsapp", "sms", "email", "dryrun", name="notification_channel",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "pending", "sent", "failed", "skipped", name="notification_status",
    ).create(bind, checkfirst=True)

    # create_table'a verilen referanslar tipi YENİDEN OLUŞTURMAMALI;
    # aksi halde "type already exists" ile düşer.
    channel = postgresql.ENUM(name="notification_channel", create_type=False)
    status = postgresql.ENUM(name="notification_status", create_type=False)

    op.create_table(
        "notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="RESTRICT"), nullable=False),
        # Hangi okumadan doğdu. RESTRICT: olaylar değişmez, bildirim de
        # onlara bağlı kalır — "neden gönderildi" sorusu hep yanıtlanabilir.
        sa.Column("event_id", sa.BigInteger,
                  sa.ForeignKey("event.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("person.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("guardian_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("guardian.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel", channel, nullable=False),
        # Gönderim ANINDAKİ numara. Veli numarasını sonradan değiştirse bile
        # "hangi numaraya gitti" kaydı bozulmaz — denetim izi.
        sa.Column("recipient", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("event_id", "guardian_id", name="notification_once"),
    )

    # İşçinin sıcak sorgusu: gönderilmeyi bekleyenler
    op.create_index(
        "notification_pending_idx", "notification", ["scheduled_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("notification_person_idx", "notification",
                    ["person_id", "created_at"])
    op.create_index("notification_tenant_time_idx", "notification",
                    ["tenant_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("notification")
    op.execute("DROP TYPE IF EXISTS notification_status")
    op.execute("DROP TYPE IF EXISTS notification_channel")
