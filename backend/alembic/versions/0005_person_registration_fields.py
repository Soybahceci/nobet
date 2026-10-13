"""person tablosuna kayıt alanları (kontrat v1.4)

Kurumun gerçek kayıt bilgilerini tutabilmesi için 5 alan.

`started_at` bilerek TEK kolon: öğrencide "kayıt tarihi", personelde
"işe başlama tarihi" — aynı anlam, birbirini dışlıyor. İki ayrı nullable
kolon tutmak veriyi bölerdi. Etiket arayüzde `person_type`'a göre değişir.

Veli 2, acil durum kişisi ve koç ataması için kolon eklenmedi:
`person_guardian` çoka-çok ve `coach_assignment` zaten mevcut.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("person", sa.Column("grade", sa.Text()))
    op.add_column("person", sa.Column("started_at", sa.Date()))
    op.add_column("person", sa.Column("address", sa.Text()))
    op.add_column("person", sa.Column("title", sa.Text()))
    op.add_column("person", sa.Column("department", sa.Text()))

    op.execute("COMMENT ON COLUMN person.grade IS 'Ogrenci sinif/seviye'")
    op.execute("COMMENT ON COLUMN person.started_at IS "
               "'Kuruma katilma: ogrencide kayit, personelde ise baslama tarihi'")
    op.execute("COMMENT ON COLUMN person.address IS "
               "'KISISEL VERI — kurumun aydinlatma metninde yer almali'")
    op.execute("COMMENT ON COLUMN person.title IS 'Personel gorev/unvan'")
    op.execute("COMMENT ON COLUMN person.department IS 'Personel departman'")

    # Sınıf bazlı listeleme kurumun en sık yapacağı sorgu
    op.create_index("person_grade_idx", "person", ["tenant_id", "grade"],
                    postgresql_where=sa.text("grade IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("person_grade_idx", table_name="person")
    for col in ("department", "title", "address", "started_at", "grade"):
        op.drop_column("person", col)
