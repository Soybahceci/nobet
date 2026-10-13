"""NÖBET — Kimlik doğrulama uçları (kontrat §3.1)"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from sqlalchemy import select

from app import login_guard, passwords
from app.config import settings
from app.deps import CurrentUser, DbSession, Principal, active_memberships
from app.models import AppUser, Membership, ResetPurpose, Tenant
from app.schemas import (
    AccessOut,
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    LoginOut,
    ResetCheckOut,
    ResetIn,
    TenantChoice,
    TokenOut,
    UserOut,
)
from app.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    token_predates_password_change,
    verify_password,
)

log = logging.getLogger("nobet.auth")
router = APIRouter(tags=["auth"])

# --- Refresh token çerezi (denetim bulgusu D-3) ----------------------------
# Eskiden refresh token yanıt gövdesinde dönüyor ve arayüz onu
# `localStorage`'a yazıyordu. Bedeli: tek bir XSS açığı **14 günlük** oturumu
# kalıcı olarak çalardı ve kurbanın bunu geri alma yolu yoktu.
#
# Artık HttpOnly çerezde: JavaScript okuyamaz. Gövdede DE dönmüyor —
# dönseydi arayüz yine saklayabilirdi ve korumanın anlamı kalmazdı.
#
# `SameSite=strict` CSRF'i kapatıyor: çerez yalnızca kendi sitemizden çıkan
# isteklerde gönderilir. Arayüz API ile aynı kökende olduğu için bu hiçbir
# şeyi kısıtlamıyor.
#
# `path` yalnızca auth uçları: çerez her istekte değil, sadece gerektiğinde
# gider.
COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.cookie_name, path=COOKIE_PATH, httponly=True,
        secure=settings.cookie_secure, samesite="strict",
    )


@router.post("/auth/login", response_model=LoginOut)
async def login(body: LoginIn, response: Response, db: DbSession) -> LoginOut:
    """
    Giriş (Faz 13a-0: tek hesap, çok kurum üyeliği).

    Kimlik e-postayla bulunur — e-posta hâlâ global benzersiz, çünkü artık
    "kurumun kullanıcısı" değil "kişi" anlamına geliyor. Kurum, kimliğin
    **üyeliklerinden** çözülür:

      · tek etkin üyelik  → doğrudan giriş
      · birden fazla      → `choices` döner, istemci seçip tekrar gönderir
      · hiç yok           → 403
    """
    email = body.email.strip().lower()

    # Denetim Y-2: kilitliyse parola HİÇ kontrol edilmez. Kontrol etmek,
    # argon2'nin ~0.22 sn'lik maliyetini bir zamanlama kanalına çevirirdi.
    await login_guard.assert_not_locked(db, email)

    user = (
        await db.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()

    # Kullanıcı yok ile parola yanlış aynı cevabı vermeli — hesap sayımını engelle.
    if user is None or not verify_password(body.password, user.password_hash):
        # Sayaç e-postaya göre; hesap olmasa da artar (bkz. login_guard).
        await login_guard.record_failure(db, email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "e-posta veya parola hatalı")
    if not user.is_active:
        # Parola DOĞRUYDU; bu bir saldırı denemesi değil. Sayacı artırmıyoruz.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hesap pasif")

    await login_guard.record_success(db, email)

    # argon2 parametreleri sıkılaştırıldıysa hash'i sessizce yenile
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    memberships = await active_memberships(db, user.id)
    if not memberships:
        # Hesap var, parola doğru, ama hiçbir kuruma bağlı değil. Bu bir
        # yapılandırma hatasıdır; kullanıcıya ne yapacağını söyleyelim.
        await db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "hesabınız hiçbir kuruma bağlı değil — kurum yöneticinize başvurun",
        )

    chosen = None
    if body.tenant_id is not None:
        chosen = next((m for m in memberships if m.tenant_id == body.tenant_id), None)
        if chosen is None:
            await db.commit()
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "bu kurumda erişiminiz yok"
            )
    elif len(memberships) == 1:
        chosen = memberships[0]

    if chosen is None:
        # Seçim gerekiyor. `last_login_at` HENÜZ yazılmaz — giriş tamamlanmadı.
        names = dict(
            (
                await db.execute(
                    select(Tenant.id, Tenant.name).where(
                        Tenant.id.in_([m.tenant_id for m in memberships])
                    )
                )
            ).all()
        )
        await db.commit()
        return LoginOut(choices=[
            TenantChoice(
                tenant_id=m.tenant_id,
                tenant_name=names.get(m.tenant_id, "—"),
                role=m.role,
            )
            for m in memberships
        ])

    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(user)

    principal = Principal(user=user, membership=chosen)
    # Refresh token GÖVDEDE DÖNMÜYOR — yalnızca HttpOnly çerezde (D-3).
    _set_refresh_cookie(response, create_refresh_token(user.id, chosen.tenant_id))
    return LoginOut(
        access_token=create_access_token(user.id, chosen.tenant_id, chosen.role.value),
        user=UserOut.model_validate(principal),
    )


@router.post("/auth/refresh", response_model=AccessOut)
async def refresh(
    db: DbSession,
    nobet_refresh: Annotated[str | None, Cookie()] = None,
) -> AccessOut:
    """
    Access token tazeleme. Refresh token **çerezden** okunur (D-3);
    istek gövdesi artık kullanılmıyor.
    """
    if not nobet_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "oturum bulunamadı")
    try:
        payload = decode_token(nobet_refresh, "refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = (
        await db.execute(select(AppUser).where(AppUser.id == uuid.UUID(payload["sub"])))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "kullanıcı yok veya pasif")

    # ⭐ Y-1'in en kritik noktası burası. Refresh token 14 gün yaşıyor;
    # bu kontrol olmadan parola değiştirmek saldırganı dışarı atmıyordu —
    # elindeki refresh ile istediği an yeni access token üretiyordu.
    if token_predates_password_change(payload, user.password_changed_at):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "parola değişti — yeniden giriş yapın"
        )

    # Hangi üyelik için tazeleniyor? Refresh token `tid` taşıyor (Faz 13a-0).
    try:
        tenant_id = uuid.UUID(str(payload.get("tid")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "token kurum bilgisi taşımıyor"
        ) from exc

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.tenant_id == tenant_id,
                Membership.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "bu kurumdaki erişiminiz sona ermiş"
        )

    return AccessOut(
        access_token=create_access_token(user.id, membership.tenant_id, membership.role.value)
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, _: CurrentUser) -> None:
    """
    Access token durumsuz ve kısa ömürlü; istemci onu bellekten siler.
    Refresh token ise çerezde, dolayısıyla **sunucu onu gerçekten silebilir**
    (D-3'ten sonra). Çıkış artık uzun ömürlü kimlik bilgisini gerçekten
    geçersiz kılıyor.
    """
    _clear_refresh_cookie(response)
    return None


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


# ---------------------------------------------------------------------------
# Parola akışları (kontrat v1.7)
# ---------------------------------------------------------------------------
@router.post("/auth/forgot", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(body: ForgotIn, db: DbSession) -> None:
    """
    "Parolamı unuttum" — sıfırlama bağlantısı gönderir.

    ⚠️ **DAİMA 204 döner.** E-posta kayıtlı olmasa, hesap pasif olsa, SMTP
    yapılandırılmamış olsa bile. Farklı cevap vermek bu ucu kurumun kullanıcı
    listesini çıkarmak için kullanılabilir hâle getirir.

    Hata ayıklama günlüğe düşer; istemciye asla.
    """
    email = body.email.strip().lower()
    user = (
        await db.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()

    if user is None or not user.is_active:
        log.info("parola sifirlama: eslesmeyen/pasif e-posta (%s)", email)
        return None

    if await passwords.recently_issued(db, user.id):
        # Hız sınırı. Kullanıcıya yine 204 dönüyoruz: "az önce gönderildi"
        # demek bile e-postanın kayıtlı olduğunu doğrular.
        log.info("parola sifirlama: hiz siniri (%s)", email)
        return None

    token = await passwords.issue(db, user, ResetPurpose.reset)
    await db.commit()

    await passwords.send_reset_mail(db, user, token, ResetPurpose.reset)
    return None


@router.get("/auth/reset/{token}", response_model=ResetCheckOut)
async def check_reset_token(token: str, db: DbSession) -> ResetCheckOut:
    """
    Parola belirleme sayfası açılırken jetonun hâlâ geçerli olup olmadığını
    sorar — kullanıcı uzun bir parola yazdıktan sonra "jeton geçersiz"
    duvarına toslamasın.
    """
    found = await passwords.resolve(db, token)
    if found is None:
        return ResetCheckOut(valid=False, email=None, purpose=None)
    user, row = found
    return ResetCheckOut(valid=True, email=user.email, purpose=row.purpose)


@router.post("/auth/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetIn, db: DbSession) -> None:
    """Jetonla yeni parola belirleme."""
    found = await passwords.resolve(db, body.token)
    if found is None:
        # Geçersiz / süresi geçmiş / kullanılmış / pasif hesap — HEPSİ aynı
        # mesaj. Ayrıştırmak saldırgana hangi jetonların var olduğunu söyler.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "bağlantı geçersiz ya da süresi dolmuş — yeniden talep edin",
        )
    user, row = found

    now = dt.datetime.now(dt.timezone.utc)
    user.password_hash = hash_password(body.password)
    # Bu satır olmadan sıfırlama işe yaramaz: hesabı ele geçiren kişinin
    # token'ı geçerli kalırdı (denetim Y-1). Sıfırlamanın bütün anlamı bu.
    user.password_changed_at = now
    row.used_at = now
    # Bu kullanıcının BEKLEYEN diğer jetonları da kapanır: eski bir e-postaya
    # erişen biri yeni parolanın üzerine yazamasın.
    await passwords.invalidate_all(db, user.id)
    await db.commit()
    log.info("parola jetonla degistirildi: %s", user.email)
    return None


@router.post("/auth/change-password", response_model=TokenOut)
async def change_own_password(
    body: ChangePasswordIn, response: Response, user: CurrentUser, db: DbSession
) -> TokenOut:
    """
    Kullanıcının kendi parolasını değiştirmesi.

    Mevcut parola sorulur: oturumu ele geçirilmiş bir tarayıcı (açık bırakılmış
    bilgisayar) parolayı değiştirip hesabı tamamen devralamasın.

    **Yeni token döndürür (204 değil).** Parola değişince o andan önceki tüm
    token'lar geçersizleşiyor (denetim Y-1) — buna kullanıcının şu anda
    kullandığı token da dahil. Taze bir çift vermezsek kişi kendi parolasını
    değiştirdiği anda sistemden atılırdı.

    Sonuç: **diğer bütün oturumlar düşer, bu oturum devam eder.** Parola
    değiştirmenin beklenen davranışı tam olarak budur.
    """
    # `user` bir Principal; kimliği değiştirmek için `user.user` gerekir.
    identity = user.user

    if not verify_password(body.current_password, identity.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mevcut parola hatalı")
    if body.current_password == body.new_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "yeni parola eskisiyle aynı olamaz"
        )

    identity.password_hash = hash_password(body.new_password)
    # Parola kimliğe ait: değişince kullanıcının TÜM kurumlardaki oturumları
    # düşer. Doğrusu bu — parolayı değiştirmenin sebebi genelde bir sorundur.
    identity.password_changed_at = dt.datetime.now(dt.timezone.utc)
    await passwords.invalidate_all(db, identity.id)
    await db.commit()
    await db.refresh(identity)
    log.info("kullanici kendi parolasini degistirdi: %s", identity.email)

    # Token'lar damgadan SONRA üretilir ki `iat` geride kalmasın. Kullanıcı
    # hangi kurumdaysa orada kalır — kurum seçimi yeniden sorulmaz.
    _set_refresh_cookie(response, create_refresh_token(identity.id, user.tenant_id))
    return TokenOut(
        access_token=create_access_token(identity.id, user.tenant_id, user.role.value),
        user=UserOut.model_validate(user),
    )
