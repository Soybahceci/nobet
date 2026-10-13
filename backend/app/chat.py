"""
NÖBET — WhatsApp Sohbet ve Otomatik Yanıtlayıcı
================================================

⚠️ MAHREMİYET KAPISI — bu dosyanın en önemli kısmı budur.

Reşit olmayan bir çocuğun nerede olduğu bilgisi veriliyor. Kurallar:

  1. Yalnızca **kayıtlı veli numarasından** gelen mesaja bilgi verilir
  2. Yalnızca **o veliye bağlı öğrenciler** hakkında bilgi verilir
  3. Tanınmayan numara **hiçbir bilgi almaz** — yöneticiye yükseltilir
  4. Mesajda başka bir isim geçse bile o kişi hakkında bilgi verilmez
  5. Her otomatik yanıt `is_auto` ile kayda geçer — kime ne verildiği denetlenebilir

Otomatik yanıtlayıcı **kasten dardır**. Anlamadığı her şeyi yöneticiye
yükseltir. Tahmin eden bir bot veliye yanlış bilgi verip kurumu zora sokar.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AttendanceSession,
    Guardian,
    Person,
    PersonGuardian,
    SessionState,
    Tenant,
    WaDirection,
    WaMessage,
    WaThread,
    Zone,
)

log = logging.getLogger("nobet.chat")


def normalize_phone(raw: str) -> str:
    """
    Numarayı yalnızca rakama indirger ve ülke kodunu netleştirir.
    "+90 555 111 22 33" ve "0555 111 22 33" aynı anahtara düşmeli,
    aksi halde aynı veli iki ayrı konuşma açar.
    """
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0"):
        d = settings.default_country_code + d[1:]
    return d


# ---------------------------------------------------------------------------
# Niyet çözümleme — dar ve öngörülebilir
# ---------------------------------------------------------------------------
_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _fold(text: str) -> str:
    return text.translate(_TR_MAP).lower()


# Sıra önemli: "cikti mi" kalıbı "icerde mi"den önce denenmez, ikisi de
# ayrı kalıplarla eşleşiyor. Kapsam bilerek dar tutuldu.
_INSIDE = ("iceride", "icerde", "geldi mi", "girdi mi", "okulda mi", "kurumda mi")
_LEFT = ("cikti mi", "cikis yapti", "ayrildi mi", "cikti")
_WHEN = ("ne zaman", "saat kacta", "kacta geldi", "kacta girdi")


def detect_intent(text: str) -> str | None:
    t = _fold(text)
    if any(k in t for k in _WHEN):
        return "when"
    if any(k in t for k in _LEFT):
        return "left"
    if any(k in t for k in _INSIDE):
        return "inside"
    return None


# ---------------------------------------------------------------------------
# Yanıt üretimi
# ---------------------------------------------------------------------------
async def _students_of(db: AsyncSession, guardian_id) -> list[Person]:
    """Bu veliye bağlı öğrenciler. Kapı burada: başkası sorulamaz."""
    return list((
        await db.execute(
            select(Person)
            .join(PersonGuardian, PersonGuardian.person_id == Person.id)
            .where(PersonGuardian.guardian_id == guardian_id)
            .order_by(Person.full_name)
        )
    ).scalars().all())


async def build_reply(
    db: AsyncSession, thread: WaThread, intent: str, tz_name: str
) -> str | None:
    if thread.guardian_id is None:
        return None   # tanınmayan numara — bilgi YOK

    students = await _students_of(db, thread.guardian_id)
    if not students:
        return None

    try:
        tz = ZoneInfo(tz_name or settings.timezone)
    except Exception:
        tz = ZoneInfo(settings.timezone)

    lines: list[str] = []
    for s in students:
        open_s = (
            await db.execute(
                select(AttendanceSession, Zone)
                .join(Zone, Zone.id == AttendanceSession.zone_id)
                .where(
                    AttendanceSession.person_id == s.id,
                    AttendanceSession.state == SessionState.open,
                )
                .order_by(AttendanceSession.entered_at.desc())
                .limit(1)
            )
        ).first()

        if open_s is not None:
            sess, zone = open_s
            local = sess.entered_at.astimezone(tz)
            if intent == "left":
                lines.append(f"{s.full_name} henüz çıkış yapmadı, {zone.name} içinde.")
            else:
                lines.append(
                    f"{s.full_name} şu an içeride ({zone.name}), "
                    f"{local:%H:%M} itibarıyla."
                )
            continue

        # Açık oturum yok — en son kapanan oturuma bak
        last = (
            await db.execute(
                select(AttendanceSession, Zone)
                .join(Zone, Zone.id == AttendanceSession.zone_id)
                .where(AttendanceSession.person_id == s.id)
                .order_by(AttendanceSession.entered_at.desc())
                .limit(1)
            )
        ).first()

        if last is None:
            lines.append(f"{s.full_name} için bugün kayıt bulunmuyor.")
            continue

        sess, zone = last
        if sess.exited_at is None:
            lines.append(f"{s.full_name} için çıkış kaydı bulunmuyor.")
        elif sess.state == SessionState.auto_closed:
            # Dürüst ol: çıkış okutulmamış, saat tahmin
            lines.append(
                f"{s.full_name} için çıkış okutulmamış. "
                f"Son giriş {sess.entered_at.astimezone(tz):%d.%m %H:%M}."
            )
        else:
            lines.append(
                f"{s.full_name} {sess.exited_at.astimezone(tz):%d.%m %H:%M} "
                f"itibarıyla {zone.name} noktasından çıkış yaptı."
            )

    if not lines:
        return None

    return "\n".join(lines) + "\n\nBu yanıt otomatik oluşturuldu."


# ---------------------------------------------------------------------------
# Gelen mesajın işlenmesi
# ---------------------------------------------------------------------------
async def get_or_create_thread(
    db: AsyncSession, tenant: Tenant, phone: str, display_name: str | None
) -> WaThread:
    norm = normalize_phone(phone)

    thread = (
        await db.execute(
            select(WaThread).where(
                WaThread.tenant_id == tenant.id, WaThread.phone == norm
            )
        )
    ).scalars().unique().one_or_none()

    if thread is None:
        thread = WaThread(
            tenant_id=tenant.id, phone=norm, display_name=display_name
        )
        db.add(thread)
        await db.flush()

    # Veli numarası sonradan eklenmiş olabilir — her mesajda yeniden dene
    if thread.guardian_id is None:
        guardians = (
            await db.execute(
                select(Guardian).where(Guardian.tenant_id == tenant.id)
            )
        ).scalars().all()
        for g in guardians:
            if g.phone and normalize_phone(g.phone) == norm:
                thread.guardian_id = g.id
                break

    return thread


async def handle_inbound(
    db: AsyncSession, tenant: Tenant, phone: str,
    body: str, display_name: str | None = None,
) -> tuple[WaThread, str | None]:
    """
    Gelen mesajı kaydeder ve varsa otomatik yanıtı döndürür.
    Yanıt None ise konuşma yöneticiye yükseltilmiştir.
    """
    thread = await get_or_create_thread(db, tenant, phone, display_name)

    # ⚠️ Zaman damgaları BURADA veriliyor, veritabanı varsayılanıyla değil.
    # PostgreSQL'de `now()` İŞLEM BAŞLANGIÇ zamanını döndürür; gelen mesaj ile
    # otomatik yanıt aynı işlemde yazıldığı için ikisi de birebir aynı damgayı
    # alır ve sohbet ekranında yanıt, kendisini tetikleyen mesajın üstünde
    # görünür. Sıra garanti altına alınmalı.
    received_at = dt.datetime.now(dt.timezone.utc)

    db.add(WaMessage(
        thread_id=thread.id, direction=WaDirection.in_, body=body,
        created_at=received_at,
    ))
    thread.last_message_at = received_at
    thread.unread_count += 1

    reply: str | None = None

    if thread.guardian_id is None:
        # Tanınmayan numara: bilgi YOK, doğrudan yükselt
        thread.needs_attention = True
        log.warning("taninmayan numaradan mesaj, yukseltildi: %s", thread.phone)
    else:
        intent = detect_intent(body)
        if intent is None:
            thread.needs_attention = True
            log.info("niyet anlasilamadi, yukseltildi: thread=%s", thread.id)
        else:
            reply = await build_reply(db, thread, intent, tenant.timezone)
            if reply is None:
                thread.needs_attention = True
            else:
                db.add(WaMessage(
                    thread_id=thread.id, direction=WaDirection.out,
                    body=reply, is_auto=True,
                    # Yanıt, tetikleyen mesajdan SONRA görünmeli
                    created_at=received_at + dt.timedelta(milliseconds=1),
                ))
                log.info("otomatik yanit verildi: thread=%s niyet=%s",
                         thread.id, intent)

    return thread, reply
