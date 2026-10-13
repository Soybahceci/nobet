"""
NÖBET — Parola ve token
========================
Kontrat §1.2: parola hash'i **argon2id**. Başka algoritma kullanılmaz.
Kontrat §3.1: access + refresh token.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.config import settings

# OWASP'ın önerdiği argon2id parametrelerine yakın; Pi 5 ve x86 sunucuda
# ~50-100 ms sürer. Giriş uçları için kabul edilebilir, kaba kuvvete karşı pahalı.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,   # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,            # argon2id
)

TokenKind = Literal["access", "refresh"]


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Parametreler sıkılaştırılırsa eski hash'ler girişte sessizce yenilenir."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return False


def _create_token(subject: str, kind: TokenKind, expires: dt.timedelta,
                  extra: dict[str, Any] | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    return _create_token(
        str(user_id),
        "access",
        dt.timedelta(minutes=settings.access_token_minutes),
        {"tid": str(tenant_id), "role": role},
    )


def create_refresh_token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """
    Refresh token da `tid` taşır (Faz 13a-0).

    Kimlik birden fazla kuruma üye olabildiği için "kullanıcının kurumu" diye
    tek bir şey yok. `tid` olmadan `/auth/refresh` hangi üyelik için access
    token üreteceğini bilemez — kurum seçimi her tazelemede kaybolurdu.
    """
    return _create_token(
        str(user_id),
        "refresh",
        dt.timedelta(days=settings.refresh_token_days),
        {"tid": str(tenant_id)},
    )


class TokenError(Exception):
    pass


def token_predates_password_change(
    payload: dict[str, Any], changed_at: dt.datetime | None
) -> bool:
    """
    Token, kullanıcının parolasını değiştirmesinden ÖNCE mi üretilmiş?

    Denetim bulgusu Y-1'in kalbi: token'lar durumsuz olduğu için parola
    değişikliği tek başına onları geçersiz kılmıyordu. Kara liste tablosu
    yerine tek bir zaman karşılaştırması yapılıyor — durumsuzluk korunuyor,
    veritabanına ek yazma gelmiyor.

    ⚠️ **Çözünürlük bir saniye.** JWT `iat` alanı tam saniye (RFC 7519),
    `password_changed_at` ise mikrosaniyeli. İKİ TARAF DA saniyeye
    yuvarlanarak karşılaştırılır.

    Neden yuvarlama şart: parolasını değiştiren kullanıcıya hemen ardından
    taze token veriliyor. Damga 10.7 sn, token'ın `iat`'i 10 olur (aşağı
    yuvarlanır) — ham karşılaştırmada 10 < 10.7 çıkar ve **taze token
    doğduğu anda ölürdü**. Yuvarlanınca 10 < 10 olmaz, token yaşar.

    Bunun bedeli: parola değişikliğiyle **aynı saniye içinde** üretilmiş bir
    token hayatta kalır. Gerçek tehdit modelinde önemsiz — saldırganın
    token'ı dakikalar ya da günler öncesine ait olur. Daha ince ayrım
    istenirse `iat` yerine milisaniyeli özel bir alan gerekir; RFC dışına
    çıkmaya değmez.
    """
    iat = payload.get("iat")
    if iat is None or changed_at is None:
        # `iat` her token'da var (bkz. _create_token). Yoksa eski/bozuk bir
        # token'dır; burada değil, imza doğrulamasında elenir.
        return False
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=dt.timezone.utc)
    return int(iat) < int(changed_at.timestamp())


def decode_token(token: str, expect: TokenKind) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token süresi doldu") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token geçersiz") from exc

    # Refresh token'ı access yerine kullanmayı engelle
    if payload.get("typ") != expect:
        raise TokenError(f"beklenen token tipi '{expect}', gelen '{payload.get('typ')}'")
    return payload
