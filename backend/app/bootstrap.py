"""
NÖBET — İlk kurulum: kurum + ilk yönetici hesabı
=================================================
Sistemde hiç kullanıcı yoksa arayüzden giriş yapılamaz; bu tek seferlik
adım o kilidi açar. "Sıfır CLI" kuralı KURUMU bağlar — kurulum yapan
teknisyeni değil.

    docker compose run --rm \
      -e BOOTSTRAP_TENANT_NAME='Örnek Dershanesi' \
      -e BOOTSTRAP_TENANT_SLUG=ornek \
      -e BOOTSTRAP_EMAIL=admin@ornek.com \
      -e BOOTSTRAP_PASSWORD='...' \
      api python -m app.bootstrap

Var olan e-posta/slug ile tekrar çalıştırılırsa hiçbir şey yapmaz (idempotent).

⚠️ **Kurum oluşturma buraya 2026-08-10'da eklendi.** Öncesinde `tenant`
satırının tek kaynağı `02-seed-dev.sql` idi; o dosya üretim kurulumundan
çıkarılınca temiz bir kurulum HİÇ açılamıyordu — bootstrap "0 kurum var"
diyip duruyordu ve kurumu oluşturmanın ne bir ucu ne başka bir yolu vardı.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AppRole, AppUser, Membership, Tenant
from app.security import hash_password


async def main() -> int:
    email = os.environ.get("BOOTSTRAP_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_PASSWORD", "")
    tenant_slug = os.environ.get("BOOTSTRAP_TENANT_SLUG", "").strip()
    role_name = os.environ.get("BOOTSTRAP_ROLE", "kurum_admin")

    if not email or not password:
        print("HATA: BOOTSTRAP_EMAIL ve BOOTSTRAP_PASSWORD zorunlu.", file=sys.stderr)
        return 2

    # Giriş ucu (§3.1) e-postayı EmailStr ile doğruluyor. Burada aynı
    # doğrulamayı yapmazsak giriş yapılamayan hesap oluşturulabiliyor —
    # örneğin `.local` gibi özel amaçlı alan adları reddediliyor.
    try:
        TypeAdapter(EmailStr).validate_python(email)
    except ValidationError as exc:
        reason = exc.errors()[0].get("msg", str(exc))
        print(f"HATA: gecersiz e-posta ({reason})", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("HATA: parola en az 12 karakter olmali.", file=sys.stderr)
        return 2
    try:
        role = AppRole(role_name)
    except ValueError:
        print(f"HATA: gecersiz rol: {role_name}", file=sys.stderr)
        return 2

    async with SessionLocal() as db:
        existing = (
            await db.execute(select(AppUser).where(AppUser.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"'{email}' zaten var — hicbir sey yapilmadi.")
            return 0

        tenant = None
        if tenant_slug:
            tenant = (
                await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one_or_none()

        if tenant is None:
            count = (
                await db.execute(select(func.count()).select_from(Tenant))
            ).scalar_one()

            if count == 0:
                # Temiz kurulum: kurumu burada oluşturuyoruz. Bu olmadan
                # sistem hiç açılamıyor — tenant satırını üretecek başka
                # hiçbir yol yok (uç da yok, arayüz de).
                if not tenant_slug:
                    print(
                        "HATA: hic kurum yok. BOOTSTRAP_TENANT_SLUG (ve "
                        "istege bagli BOOTSTRAP_TENANT_NAME) verin.",
                        file=sys.stderr,
                    )
                    return 2
                if not re.fullmatch(r"[a-z0-9-]{2,40}", tenant_slug):
                    print(
                        "HATA: slug yalnizca kucuk harf, rakam ve tire "
                        "icermeli (2-40 karakter).",
                        file=sys.stderr,
                    )
                    return 2
                tenant = Tenant(
                    name=os.environ.get("BOOTSTRAP_TENANT_NAME") or tenant_slug,
                    slug=tenant_slug,
                    timezone=os.environ.get("BOOTSTRAP_TIMEZONE") or "Europe/Istanbul",
                )
                db.add(tenant)
                await db.flush()
                print(f"Kurum olusturuldu: {tenant.name} ({tenant.slug})")

            elif tenant_slug:
                print(f"HATA: '{tenant_slug}' slug'li kurum yok.", file=sys.stderr)
                return 1
            elif count != 1:
                print(
                    f"HATA: {count} kurum var, hangisi belirsiz. "
                    "BOOTSTRAP_TENANT_SLUG verin.",
                    file=sys.stderr,
                )
                return 1
            else:
                tenant = (await db.execute(select(Tenant))).scalars().first()

        # Faz 13a-0: kimlik ve üyelik ayrı. Kimlik e-postayı ve parolayı,
        # üyelik kurumu ve rolü taşır.
        user = AppUser(
            email=email,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=role,
            is_active=True,
        ))
        await db.commit()

    print(f"Olusturuldu: {email}  rol={role.value}  kurum={tenant.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
