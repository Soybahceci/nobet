"""kişi anonimleştirme damgası (KVKK silme hakkı)

Sorun: kişi kalıcı SİLİNEMİYOR. `event.person_id` yabancı anahtarı RESTRICT
ve olaylar değişmez — denetim izi için doğru, ama KVKK'daki silme hakkını
karşılamıyor.

Çözüm silme değil **anonimleştirme**: kimliği belirleyen alanlar temizlenir,
satır ve geçmiş olaylar korunur. Böylece "kaç kişi girdi çıktı" istatistiği
bozulmaz ama o satır artık bir insanı işaret etmez.

`anonymized_at` bu işlemin NE ZAMAN yapıldığını saklar — talebe ne zaman
yanıt verildiğinin kaydı, denetimde gerekir.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("person", sa.Column("anonymized_at", sa.DateTime(timezone=True)))
    op.execute("COMMENT ON COLUMN person.anonymized_at IS "
               "'KVKK silme talebi uzerine anonimlestirme zamani. "
               "Dolu ise kimlik alanlari temizlenmistir.'")
    op.create_index("person_anonymized_idx", "person", ["tenant_id"],
                    postgresql_where=sa.text("anonymized_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("person_anonymized_idx", table_name="person")
    op.drop_column("person", "anonymized_at")
