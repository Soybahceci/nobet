"""elle giriş/çıkış (Faz 13a-5)

Kullanıcı gereksinimi: öğrenci kartını unutursa, kart bozulursa ya da
okuyucu arıza yaparsa **kapıdaki görevli elle kayıt açabilmeli.** Bugün
bunun hiçbir yolu yok — kart okunmazsa öğrenci sistemde hiç görünmüyor,
veliye bildirim gitmiyor, yoklamada devamsız çıkıyor.

⭐ **Seçilen yol (kullanıcı onayı 2026-08-11): oturum DOĞRUDAN üretilir.**

Alternatif, `event` tablosuna sahte satır yazmaktı. Reddedildi: `event`'in
güvenilir olmasının tek sebebi **"bir okuyucu bir kart okudu"** demesi.
İçine insan eliyle yazılan satırlar karıştığında denetim izinin anlamı
sulanır ve Faz 0'ın en temel kararına aykırı düşer.

Bu yol Faz 0 ilkesiyle uyumlu: *"Olaylar değişmez, oturumlar türetilir."*
İnsan müdahalesi **her zaman türetilmiş katmanda** kalıyor — zaten var olan
`corrected_by` / `SessionState.corrected` mekanizmasının kardeşi.

Sonuç: elle giriş ham olay akışında **görünmez** (doğrusu da bu, kart
okunmadı) ama yoklamada, raporda ve "şu an içeride" listesinde **görünür**.

---

Üç değişiklik:

1. `attendance_session.entry_event_id` NULL olabilir hâle geliyor.
2. `entry_source` ('card' | 'manual') ve `created_by` ekleniyor.
   `created_by` olmadan "bu kaydı kim açtı" sorusunun cevabı olmaz;
   elle giriş kötüye kullanılabilir bir yetki, izsiz bırakılamaz.
3. `notification.event_id` NULL olabiliyor ve `session_id` ekleniyor.
   Elle girişte veliye bildirim gitmesi gerekiyor (velinin ihtiyacı aynı)
   ama bildirim bugün yalnızca olaya bağlanabiliyordu.

⚠️ `notification` tablosundaki `UNIQUE(event_id, guardian_id)` kısıtı
mükerrer bildirimi engelliyordu. `event_id` artık NULL olabildiği için o
kısıt tek başına yetmez — NULL değerler benzersizlik kontrolüne girmez ve
aynı oturum için sınırsız bildirim üretilebilirdi. İki **kısmi** benzersiz
indeksle değiştiriliyor.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1) oturum artık olaysız var olabilir ------------------------------
    op.alter_column("attendance_session", "entry_event_id", nullable=True)

    op.add_column(
        "attendance_session",
        sa.Column("entry_source", sa.Text(), nullable=False, server_default="card"),
    )
    op.add_column(
        "attendance_session",
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id"), nullable=True),
    )
    op.create_check_constraint(
        "session_entry_source_valid",
        "attendance_session",
        "entry_source IN ('card','manual')",
    )
    # Kart kaynaklı oturum olaysız olamaz — eski garanti korunuyor.
    # Elle açılan oturumda ise olay YOKTUR ve olmamalıdır.
    op.create_check_constraint(
        "session_entry_event_matches_source",
        "attendance_session",
        "(entry_source = 'card'   AND entry_event_id IS NOT NULL) OR "
        "(entry_source = 'manual' AND entry_event_id IS NULL)",
    )
    # Elle açılan kaydın sahibi belli olmalı.
    op.create_check_constraint(
        "session_manual_needs_author",
        "attendance_session",
        "entry_source <> 'manual' OR created_by IS NOT NULL",
    )
    op.create_index(
        "session_entry_source_idx", "attendance_session", ["tenant_id", "entry_source"]
    )

    # --- 2) bildirim oturuma da bağlanabilsin ------------------------------
    op.alter_column("notification", "event_id", nullable=True)
    op.add_column(
        "notification",
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attendance_session.id", ondelete="CASCADE"),
                  nullable=True),
    )
    op.create_check_constraint(
        "notification_source_exactly_one",
        "notification",
        "(event_id IS NOT NULL AND session_id IS NULL) OR "
        "(event_id IS NULL AND session_id IS NOT NULL)",
    )

    # ⚠️ Mükerrer bildirim koruması. Eski UNIQUE(event_id, guardian_id)
    # kısıtı, event_id NULL olabilir hâle gelince işlevini kaybediyor:
    # PostgreSQL'de NULL'lar benzersizlik kontrolüne girmez, dolayısıyla
    # aynı oturum için SINIRSIZ bildirim üretilebilirdi. Veliye mükerrer
    # mesaj gitmesi Faz 8'de özenle engellenmişti; o garanti korunuyor.
    op.drop_constraint("notification_once", "notification", type_="unique")
    op.create_index(
        "notification_once_event", "notification", ["event_id", "guardian_id"],
        unique=True, postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    op.create_index(
        "notification_once_session", "notification", ["session_id", "guardian_id"],
        unique=True, postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("notification_once_session", table_name="notification")
    op.drop_index("notification_once_event", table_name="notification")
    op.create_unique_constraint(
        "notification_once", "notification", ["event_id", "guardian_id"]
    )
    op.drop_constraint("notification_source_exactly_one", "notification", type_="check")
    op.drop_column("notification", "session_id")
    # ⚠️ Oturuma bağlı bildirimler varsa geri alma BAŞARISIZ olur
    # (event_id NOT NULL yapılamaz). Doğrusu da bu: sessizce satır silmek
    # yerine hata vermek.
    op.alter_column("notification", "event_id", nullable=False)

    op.drop_index("session_entry_source_idx", table_name="attendance_session")
    op.drop_constraint("session_manual_needs_author", "attendance_session", type_="check")
    op.drop_constraint("session_entry_event_matches_source", "attendance_session", type_="check")
    op.drop_constraint("session_entry_source_valid", "attendance_session", type_="check")
    op.drop_column("attendance_session", "created_by")
    op.drop_column("attendance_session", "entry_source")
    # Elle açılmış oturum varsa bu da BAŞARISIZ olur — kasıtlı.
    op.alter_column("attendance_session", "entry_event_id", nullable=False)
