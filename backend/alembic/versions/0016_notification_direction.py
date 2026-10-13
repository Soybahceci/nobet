"""bildirime yön alanı — bir oturum İKİ bildirim üretir (Faz 13a-5 devamı)

0015'te `notification_once_session` indeksi `UNIQUE(session_id, guardian_id)`
olarak kondu: "bir oturum için bir veliye tek bildirim". Bu **yanlıştı** ve
elle giriş bildirimleri bağlanırken ortaya çıktı.

Bir oturum iki bildirim üretir:

    08:00  elle giriş  → veliye "giriş yaptı"
    12:00  elle çıkış  → veliye "çıkış yaptı"

Olay yolunda sorun yoktu çünkü giriş ve çıkış **ayrı `event` satırları**;
oturumda ise ikisi **aynı satır**. Eski indeksle ikinci bildirim
`duplicate key` ile reddedilir ve **veli çıkış haberini hiç alamazdı.**

Üstelik bu yalnızca elle açılan oturumları ilgilendirmiyor: kartla açılmış
bir oturum elle kapatıldığında o çıkış için hiç `event` üretilmez, dolayısıyla
tek haber verme yolu oturuma bağlı bildirimdir.

⚠️ `direction` NULL kalırsa indeks yine devre dışı kalır — PostgreSQL'de
NULL'lar benzersizlik kontrolüne girmez; bu, 0015'te `event_id` için
düşülen tuzağın aynısı. CHECK ile engelleniyor: oturuma bağlı bildirimin
yönü **dolu olmak zorunda**.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification", sa.Column("direction", sa.Text(), nullable=True))

    op.create_check_constraint(
        "notification_direction_valid",
        "notification",
        "direction IS NULL OR direction IN ('GİRİŞ','ÇIKIŞ')",
    )
    # Oturuma bağlı bildirimin yönü boş olamaz — aksi halde aşağıdaki
    # benzersiz indeks NULL yüzünden hiçbir şeyi engellemez.
    op.create_check_constraint(
        "notification_session_needs_direction",
        "notification",
        "session_id IS NULL OR direction IS NOT NULL",
    )

    op.drop_index("notification_once_session", table_name="notification")
    op.create_index(
        "notification_once_session",
        "notification",
        ["session_id", "guardian_id", "direction"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("notification_once_session", table_name="notification")
    # ⚠️ Aynı oturum için iki yönlü bildirim varsa geri alma BAŞARISIZ olur.
    # Doğrusu da bu: sessizce satır silmek yerine hata vermek.
    op.create_index(
        "notification_once_session",
        "notification",
        ["session_id", "guardian_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.drop_constraint("notification_session_needs_direction", "notification", type_="check")
    op.drop_constraint("notification_direction_valid", "notification", type_="check")
    op.drop_column("notification", "direction")
