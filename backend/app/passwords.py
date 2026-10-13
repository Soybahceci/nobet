"""
NÖBET — Parola sıfırlama / davet jetonları (kontrat §1.2, v1.7)
==============================================================
Bu modülün tek işi jetonu **üretmek, saklamak ve tüketmek**. E-posta metni
ve uçlar `routers/auth.py` içinde.

Tasarım kararları ve gerekçeleri:

- **Jeton hash'lenerek saklanır.** Veritabanını okuyabilen biri (yedek
  dosyası, sızıntı, DBA) düz metin jetonla bekleyen her hesabı ele
  geçirebilirdi. Jeton yalnızca e-postada bulunur.
- **Tek kullanımlık ve süreli.** Kullanılan jeton `used_at` ile kapanır.
- **Parola değişince bekleyen tüm jetonlar iptal olur.** Aksi hâlde eski bir
  sıfırlama e-postasına erişen biri (paylaşılan gelen kutusu, çalınan telefon)
  parolayı geri alabilirdi.
- **Sabit zamanlı karşılaştırma yok, gerek de yok:** jetonu hash'leyip
  benzersiz indeks üzerinden arıyoruz. Zamanlama farkı jetonun kendisini
  sızdırmaz.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import mail, settings_store
from app.config import settings
from app.models import AppUser, Membership, PasswordReset, ResetPurpose

log = logging.getLogger("nobet.passwords")

# Kendi talebiyle sıfırlama kısa ömürlü; davet, kişi işe yeni başladığı için
# uzun (hafta sonuna denk gelebilir).
TTL = {
    ResetPurpose.reset: dt.timedelta(hours=1),
    ResetPurpose.invite: dt.timedelta(hours=72),
}

# Aynı kullanıcı için ardışık jeton üretimi arasındaki en kısa süre.
# Bu olmadan `/auth/forgot` birinin gelen kutusunu bombalamak için kullanılır.
RATE_LIMIT = dt.timedelta(minutes=1)

MIN_PASSWORD_LEN = 12


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def recently_issued(db: AsyncSession, user_id) -> bool:
    """Hız sınırı: son `RATE_LIMIT` içinde bu kullanıcı için jeton üretildi mi?"""
    since = dt.datetime.now(dt.timezone.utc) - RATE_LIMIT
    row = (
        await db.execute(
            select(PasswordReset.id).where(
                PasswordReset.user_id == user_id,
                PasswordReset.created_at >= since,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def issue(db: AsyncSession, user: AppUser, purpose: ResetPurpose) -> str:
    """
    Yeni jeton üretir ve **düz metin hâlini döndürür** — çağıran onu yalnızca
    e-postaya koyar, hiçbir yere yazmaz. Sistem bir daha göremez.
    """
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(
        user_id=user.id,
        token_hash=_hash(token),
        purpose=purpose,
        expires_at=dt.datetime.now(dt.timezone.utc) + TTL[purpose],
    ))
    await db.flush()
    return token


async def resolve(db: AsyncSession, token: str) -> tuple[AppUser, PasswordReset] | None:
    """
    Jetonu kullanıcıya çevirir. Geçersiz / süresi geçmiş / kullanılmış /
    pasif hesap durumlarında `None`.

    Çağıran taraf **hepsi için aynı hatayı** döndürmeli: hangi sebeple
    reddedildiğini söylemek saldırgana bilgi verir.
    """
    row = (
        await db.execute(
            select(PasswordReset).where(PasswordReset.token_hash == _hash(token))
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        return None

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    if expires <= dt.datetime.now(dt.timezone.utc):
        return None

    user = (
        await db.execute(select(AppUser).where(AppUser.id == row.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    return user, row


async def invalidate_all(db: AsyncSession, user_id) -> None:
    """
    Kullanıcının bekleyen tüm jetonlarını kapatır.

    Parola HER değiştiğinde çağrılır — kendi değiştirdiğinde, yönetici
    sıfırladığında, jetonla belirlediğinde. Aksi hâlde eski bir e-postadaki
    jeton hâlâ geçerli kalır ve yeni parolanın üzerine yazabilir.
    """
    now = dt.datetime.now(dt.timezone.utc)
    rows = (
        await db.execute(
            select(PasswordReset).where(
                PasswordReset.user_id == user_id,
                PasswordReset.used_at.is_(None),
            )
        )
    ).scalars().all()
    for r in rows:
        r.used_at = now


async def send_reset_mail(
    db: AsyncSession, user: AppUser, token: str, purpose: ResetPurpose
) -> bool:
    """
    Sıfırlama/davet e-postasını gönderir. **İstisna fırlatmaz** — başarı
    durumunu döndürür.

    `/auth/forgot` kullanıcıya her hâlükârda 204 dönüyor; orada patlamak hem
    o sözü bozar hem de e-postanın kayıtlı olduğunu sızdırır. Hesap açma
    akışında ise çağıran taraf `False` sonucunu yöneticiye gösterir.
    """
    # Faz 13a-0: kimliğin artık tek bir kurumu yok. E-posta, kullanıcının
    # **en eski etkin üyeliğinin** kurumu üzerinden gider — kimlik kuruma
    # değil kişiye ait olduğu için hangisi seçilirse seçilsin keyfi; en eski
    # olan en kararlı seçim (yeni üyelik eklenince adres değişmesin).
    tenant_id = (
        await db.execute(
            select(Membership.tenant_id)
            .where(Membership.user_id == user.id, Membership.is_active.is_(True))
            .order_by(Membership.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if tenant_id is None:
        log.error("parola e-postasi gonderilemedi: %s hicbir kuruma bagli degil", user.email)
        return False

    row = await settings_store.get_setting(db, tenant_id)
    cfg = settings_store.smtp_config(row)

    link = f"{settings.public_base_url.rstrip('/')}/parola-belirle?token={token}"
    if purpose == ResetPurpose.invite:
        subject = "NÖBET — hesabınız açıldı, parolanızı belirleyin"
        intro = ("NÖBET sistemine hesabınız açıldı. Parolanızı belirlemek için "
                 "aşağıdaki bağlantıya tıklayın.")
        validity = "Bağlantı 72 saat geçerlidir."
    else:
        subject = "NÖBET — parola sıfırlama"
        intro = ("Parolanızı sıfırlamak için bir talep aldık. Aşağıdaki "
                 "bağlantıya tıklayarak yeni parolanızı belirleyebilirsiniz.")
        validity = "Bağlantı 1 saat geçerlidir."

    text = (
        f"Merhaba,\n\n{intro}\n\n{link}\n\n{validity} "
        "Bağlantı yalnızca bir kez kullanılabilir.\n\n"
        "Bu talebi siz yapmadıysanız bu e-postayı yok sayabilirsiniz; "
        "parolanız değişmez.\n\n— NÖBET"
    )

    try:
        await mail.send_mail(cfg, user.email, subject, text)
        log.info("parola e-postasi gonderildi: %s (%s)", user.email, purpose.value)
        return True
    except mail.MailError as exc:
        log.error("parola e-postasi GONDERILEMEDI: %s — %s", user.email, exc)
        return False
