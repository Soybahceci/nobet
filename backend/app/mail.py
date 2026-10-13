"""
NÖBET — E-posta gönderimi (SMTP)
=================================
Parola sıfırlama/davet e-postaları ve `channel="email"` seçiliyse veli
bildirimleri buradan çıkar.

**Neden `smtplib`, `aiosmtplib` değil?** Hacim çok düşük: kurum başına günde
birkaç parola e-postası. Engelleyen çağrı `asyncio.to_thread` ile ayrı bir
iş parçacığına alınıyor; yeni bir bağımlılık taşımaya değmez.

⚠️ **Zaman aşımı zorunlu.** Yanıt vermeyen bir SMTP sunucusu, zaman aşımı
olmadan bildirim işçisini süresiz kilitler — kuyruk durur ve hiçbir veli
mesaj almaz. Sessiz durma, bu üründe en pahalı arıza türü.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl as ssl_mod
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

log = logging.getLogger("nobet.mail")

SMTP_TIMEOUT = 20  # saniye — bağlantı ve her komut için


class MailError(RuntimeError):
    """Gönderim başarısız. İşçi bunu yakalayıp yeniden dener."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    security: str = "starttls"          # starttls | ssl | none
    from_addr: str = ""
    from_name: str = "NÖBET"
    user: str | None = None
    password: str | None = None

    def problems(self) -> list[str]:
        """Gönderimi imkânsız kılan eksikler. Boş liste = yapılandırma tam."""
        out: list[str] = []
        if not (self.host or "").strip():
            out.append("sunucu adresi girilmemiş")
        if not (self.from_addr or "").strip():
            out.append("gönderen adresi girilmemiş")
        elif "@" not in parseaddr(self.from_addr)[1]:
            out.append("gönderen adresi geçersiz")
        if self.security not in ("starttls", "ssl", "none"):
            out.append(f"bilinmeyen güvenlik kipi: {self.security}")
        # Kullanıcı adı varsa parola da olmalı; ikisi de yoksa kimlik
        # doğrulamasız röle demektir (yerel Postfix gibi) — geçerli bir kurulum.
        if self.user and not self.password:
            out.append("kullanıcı adı var ama parola yok")
        return out


def _build(cfg: SmtpConfig, to: str, subject: str,
           text: str, html: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name, parseaddr(cfg.from_addr)[1]))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _connect(cfg: SmtpConfig) -> smtplib.SMTP:
    if cfg.security == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            cfg.host, cfg.port, timeout=SMTP_TIMEOUT,
            context=ssl_mod.create_default_context(),
        )
    else:
        smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT)
        if cfg.security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=ssl_mod.create_default_context())
            smtp.ehlo()
    if cfg.user:
        smtp.login(cfg.user, cfg.password or "")
    return smtp


def _send_blocking(cfg: SmtpConfig, msg: EmailMessage) -> None:
    smtp = _connect(cfg)
    try:
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()


async def send_mail(cfg: SmtpConfig, to: str, subject: str,
                    text: str, html: str | None = None) -> None:
    problems = cfg.problems()
    if problems:
        raise MailError("SMTP yapılandırması eksik: " + ", ".join(problems))

    msg = _build(cfg, to, subject, text, html)
    try:
        await asyncio.to_thread(_send_blocking, cfg, msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"SMTP kimlik doğrulama reddedildi: {exc}") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"alıcı reddedildi: {to}") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP hatası: {exc}") from exc


async def verify(cfg: SmtpConfig) -> tuple[bool, str]:
    """
    Bağlanıp (varsa) kimlik doğrular, mesaj GÖNDERMEZ.

    Ayarlar sayfasındaki sağlık rozeti için. Gerçek teslimat garantisi
    vermez — onun için "Test e-postası gönder" gerekir.
    """
    problems = cfg.problems()
    if problems:
        return False, ", ".join(problems)

    def _check() -> None:
        smtp = _connect(cfg)
        try:
            smtp.noop()
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()

    try:
        await asyncio.to_thread(_check)
    except smtplib.SMTPAuthenticationError:
        return False, "kimlik doğrulama reddedildi — kullanıcı adı/parola"
    except Exception as exc:
        return False, f"bağlanılamadı: {exc}"

    who = f" ({cfg.user})" if cfg.user else " (kimlik doğrulamasız)"
    return True, f"{cfg.host}:{cfg.port} {cfg.security}{who}"
