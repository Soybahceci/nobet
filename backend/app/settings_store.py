"""
NÖBET — Bildirim ayarlarının saklanması

Kimlik bilgileri Fernet ile şifrelenir. Anahtar ortam değişkeninden gelir
(`SETTINGS_KEY`); veritabanı yedeği sızsa bile sır çözülemez.

Anahtar tanımlı değilse **sır saklanmaz** — düz metin yazmaktansa
reddetmek doğru davranış.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import NotifySetting

log = logging.getLogger("nobet.settings")


class SecretUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = (settings.settings_key or "").strip()
    if not key:
        raise SecretUnavailable(
            "SETTINGS_KEY tanımlı değil — kimlik bilgileri şifrelenemez, "
            "düz metin saklanmaz"
        )
    return Fernet(key.encode())


def encrypt_secret(data: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_secret(blob: str | None) -> dict[str, str]:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError):
        # Anahtar değişmiş ya da veri bozuk. Sessizce boş dönmek yanlış
        # kimlikle gönderim denemesine yol açar; açıkça hata verilir.
        raise SecretUnavailable(
            "kayıtlı kimlik bilgileri çözülemedi — SETTINGS_KEY değişmiş olabilir"
        ) from None


async def get_setting(db: AsyncSession, tenant_id) -> NotifySetting:
    row = (
        await db.execute(
            select(NotifySetting).where(NotifySetting.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    if row is None:
        # İlk kayıt, MEVCUT ortam ayarından tohumlanır.
        # Doğrudan "dryrun" yazmak, ayarlar veritabanına taşınırken çalışan
        # bir kanalı sessizce kapatırdı — kurum bildirimlerin durduğunu
        # ancak bir veli şikâyet edince fark ederdi.
        initial = settings.notify_channel
        if initial not in ("dryrun", "whatsapp", "sms", "email"):
            initial = "dryrun"
        row = NotifySetting(tenant_id=tenant_id, channel=initial, sms_config={})
        db.add(row)
        await db.flush()
        log.info("bildirim ayari olusturuldu, baslangic kanali: %s", initial)
    return row


def smtp_config(row: NotifySetting) -> "mail.SmtpConfig":
    """
    Satırdan SMTP yapılandırması üretir. Parola çözülemezse (SETTINGS_KEY
    yok/değişmiş) **boş parolayla** döner — `SmtpConfig.problems()` bunu
    yakalar ve sebebi arayüzde görünür. Sessizce yanlış kimlikle bağlanmaya
    çalışmaktan iyidir.
    """
    from app import mail

    password = None
    if row.smtp_secret_enc:
        try:
            password = decrypt_secret(row.smtp_secret_enc).get("password")
        except SecretUnavailable as exc:
            log.error("SMTP parolasi cozulemedi: %s", exc)

    return mail.SmtpConfig(
        host=row.smtp_host or "",
        port=row.smtp_port or 587,
        security=row.smtp_security or "starttls",
        from_addr=row.smtp_from or "",
        user=row.smtp_user or None,
        password=password,
    )


def public_config(row: NotifySetting) -> dict[str, Any]:
    """Arayüze dönen hâli — sır ASLA çıkmaz, yalnızca tanımlı olup olmadığı."""
    return {
        "channel": row.channel,
        "sms_provider": row.sms_provider,
        "sms_config": row.sms_config or {},
        "has_secret": bool(row.secret_enc),
        "smtp_host": row.smtp_host,
        "smtp_port": row.smtp_port,
        "smtp_security": row.smtp_security,
        "smtp_from": row.smtp_from,
        "smtp_user": row.smtp_user,
        "has_smtp_secret": bool(row.smtp_secret_enc),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
