"""ders programı (kontrat v1.9)

Sorun: derslik yoklaması "geldi" saymak için bir zaman aralığı istiyor ve bu
aralık her yoklamada ELLE giriliyordu. Operatör ders saatini kendi yazıyordu;
bir dakikalık kayma öğrencileri devamsız gösterebiliyordu.

Saatler yerel saat olarak (`time`) saklanır — tarih ve dilim yok. Kurumun
dilimi `tenant.timezone`'da; UTC'ye çevirme sunucuda yapılır. Tarayıcının
diliminden hesaplamak, yurt dışından bakan bir yöneticide yanlış aralık
üretirdi.

`weekday` ISO: 1 = Pazartesi … 7 = Pazar (Python `isoweekday()` ile aynı).
0-tabanlı seçmek, `isoweekday()` ile `weekday()` karışıklığının klasik
kaynağıdır; ISO'ya sabitlendi.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("zone.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grade", sa.String(40), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("weekday BETWEEN 1 AND 7", name="lesson_weekday_range"),
        # Gece yarısını aşan ders yok; olsaydı iki satıra bölünmeli.
        sa.CheckConstraint("ends_at > starts_at", name="lesson_time_order"),
    )
    # "Bugün bu derslikte bu sınıfın dersleri" sorgusunun taradığı yol
    op.create_index("lesson_lookup_idx", "lesson",
                    ["tenant_id", "zone_id", "grade", "weekday"])

    op.execute(
        "COMMENT ON COLUMN lesson.weekday IS "
        "'ISO gun: 1=Pazartesi … 7=Pazar (Python isoweekday ile ayni)'"
    )
    op.execute(
        "COMMENT ON COLUMN lesson.starts_at IS "
        "'Kurumun YEREL saati. Dilim tenant.timezone''da; UTC cevrimi sunucuda.'"
    )


def downgrade() -> None:
    op.drop_index("lesson_lookup_idx", table_name="lesson")
    op.drop_table("lesson")
