"""parola değişince oturumlar düşsün (denetim bulgusu Y-1)

Sorun: `passwords.invalidate_all()` bekleyen **sıfırlama jetonlarını**
kapatıyordu ama dolaşımdaki **JWT'lere** dokunmuyordu. Token'lar durumsuz;
`decode_token` yalnızca imza, süre ve tip bakıyordu.

Sonucu: hesabı ele geçirilen biri parolasını değiştirdiğinde — yapılması
gereken doğru şey — saldırganın refresh token'ı `refresh_token_days`
(14 gün) boyunca geçerli kalıyor ve istediği an yeni access token
üretebiliyordu. Yani parola değiştirmek, tam da işe yaraması gereken
durumda işe yaramıyordu.

Çözüm: kullanıcının parolasının **en son ne zaman değiştiğini** tut. Token
doğrulanırken `iat` (üretim zamanı) bu andan önceyse token reddedilir.
Kara liste tablosuna gerek yok — tek kolon yetiyor ve durumsuzluk korunuyor.

⚠️ Geri doldurma `created_at` ile yapılıyor, `now()` ile değil.
`now()` yazmak dağıtım anında **herkesi sistemden atardı**. `created_at`
semantik olarak da dürüst: "parola en azından hesap açıldığından beri
değişmemiş". Bugünkünden kötü bir durum oluşturmuyor, yalnızca eski
token'ları da geçerli saymaya devam ediyor.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Önce nullable ekle — mevcut satırlar için doldurulacak.
    op.add_column(
        "app_user",
        sa.Column("password_changed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Mevcut kullanıcılar: hesabın açıldığı an. (created_at NOT NULL +
    # server_default olduğu için COALESCE yalnızca ihtiyat.)
    op.execute(
        "UPDATE app_user "
        "SET password_changed_at = COALESCE(created_at, now()) "
        "WHERE password_changed_at IS NULL"
    )
    # Artık boş satır yok; kısıt ve varsayılan konabilir.
    op.alter_column(
        "app_user",
        "password_changed_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("app_user", "password_changed_at")
