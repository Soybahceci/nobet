"""
NÖBET — Giriş kaba kuvvet koruması (denetim bulgusu Y-2)
========================================================

Ölçüm (2026-08-10, Pi üzerinde): 12 ardışık yanlış parola, hepsi 401,
her biri ~0.22 sn, kilitleme yok, gecikme artışı yok, sonra doğru parola
200. Bağlantı başına ~4.5 deneme/sn, paralel bağlantıyla katlanır.

argon2id'nin ~0.22 sn maliyeti **çevrimdışı** saldırıya karşı iyi;
çevrimiçi saldırıya karşı yeterli değil. Panel Faz 13f'te internete çıkıyor
ve bir kurumun yönetici hesabının kırılması, o kurumun tüm öğrenci verisi
demek.

⭐ **Sayaç e-postaya göre tutulur, hesabın VAR OLUP OLMADIĞINA bakılmaz.**
Yalnızca var olan hesapları kilitleseydik, kilitlenme davranışının kendisi
"bu e-posta kayıtlı" bilgisini verirdi — `/auth/forgot`'ta özenle kaçınılan
sızıntının aynısı giriş ucundan sızardı.

Kademeli gecikme (sabit süre yerine):
    1-4. hata   → kilit yok
    5. hata     → 1 dk
    6.          → 2 dk
    7.          → 4 dk   … ikiye katlanarak
    10+         → 30 dk (tavan)

Sabit kilit süresi ya çok gevşek olur ya da unutkan bir kullanıcıyı gereksiz
cezalandırır. Kademeli olan, gerçek kullanıcıyı neredeyse hiç etkilemeden
otomatik saldırıyı işlemez hâle getirir.

⚠️ **Sınırı:** koruma e-posta başınadır. Çok sayıda FARKLI hesaba dağıtılmış
bir saldırı (password spraying) bununla durmaz; onun için IP/ağ başına sınır
gerekir ve o, ters vekil (reverse proxy) katmanının işidir. Faz 13f'te
Cloudflare Tunnel arkasına geçildiğinde oradan konmalı.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginAttempt

log = logging.getLogger("nobet.login_guard")

FAIL_THRESHOLD = 5           # bu sayıdan itibaren kilit
BASE_LOCK = dt.timedelta(minutes=1)
MAX_LOCK = dt.timedelta(minutes=30)

# Bu süre boyunca hiç denemesi olmayan kaydın sayacı sıfırlanır: dün üç kez
# yanlış yazmış olmak bugünkü ilk denemeyi kilide yaklaştırmamalı.
COUNTER_TTL = dt.timedelta(hours=12)


def _lock_for(failed_count: int) -> dt.timedelta:
    over = failed_count - FAIL_THRESHOLD
    if over < 0:
        return dt.timedelta(0)
    return min(BASE_LOCK * (2 ** over), MAX_LOCK)


async def _row(db: AsyncSession, email: str) -> LoginAttempt | None:
    return (
        await db.execute(select(LoginAttempt).where(LoginAttempt.email == email))
    ).scalar_one_or_none()


async def assert_not_locked(db: AsyncSession, email: str) -> None:
    """
    Kilitliyse 429 ile durdurur — **parola hiç kontrol edilmeden.**

    Parolayı yine de doğrulamak, kilidi bir zamanlama kanalına çevirirdi
    (argon2 doğrulaması ~0.22 sn sürüyor; kilitli hesapta bu sürenin
    harcanıp harcanmaması cevabı ele verirdi).
    """
    row = await _row(db, email)
    if row is None or row.locked_until is None:
        return

    until = row.locked_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.timezone.utc)

    now = dt.datetime.now(dt.timezone.utc)
    if until <= now:
        return

    kalan = int((until - now).total_seconds())
    dakika = max(1, (kalan + 59) // 60)
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"çok fazla başarısız giriş denemesi — {dakika} dakika sonra tekrar deneyin",
    )


async def record_failure(db: AsyncSession, email: str) -> None:
    """Başarısız denemeyi işler ve gerekiyorsa kilidi kurar."""
    now = dt.datetime.now(dt.timezone.utc)
    row = await _row(db, email)

    if row is None:
        row = LoginAttempt(email=email, failed_count=0, last_attempt_at=now)
        db.add(row)
    else:
        last = row.last_attempt_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        if last is not None and now - last > COUNTER_TTL:
            row.failed_count = 0

    row.failed_count += 1
    row.last_attempt_at = now

    lock = _lock_for(row.failed_count)
    if lock:
        row.locked_until = now + lock
        log.warning(
            "giris kilidi: %s (%d. hata, %d dk)",
            email, row.failed_count, int(lock.total_seconds() // 60),
        )
    await db.commit()


async def record_success(db: AsyncSession, email: str) -> None:
    """Başarılı girişte sayaç ve kilit temizlenir."""
    row = await _row(db, email)
    if row is not None:
        await db.delete(row)
