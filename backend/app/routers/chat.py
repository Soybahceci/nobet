"""NÖBET — WhatsApp sohbet uçları"""
from __future__ import annotations

import datetime as dt
import hmac
import uuid

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app import chat, notify
from app.config import settings
from app.deps import DbSession, StaffUser
from app.models import (
    Tenant,
    WaDirection,
    WaMessage,
    WaThread,
)
from app.schemas import ORM

router = APIRouter(tags=["chat"])


class ThreadOut(ORM):
    id: uuid.UUID
    phone: str
    display_name: str | None
    guardian_id: uuid.UUID | None
    guardian_name: str | None = None
    needs_attention: bool
    unread_count: int
    last_message_at: dt.datetime | None


class MessageOut(ORM):
    id: uuid.UUID
    direction: WaDirection
    body: str
    is_auto: bool
    error: str | None
    created_at: dt.datetime


class InboundIn(BaseModel):
    phone: str
    text: str
    name: str | None = None


class ReplyIn(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Ağ geçidi webhook'u — kullanıcı arayüzü değil, makine ucu
# ---------------------------------------------------------------------------
@router.post("/wa/inbound", include_in_schema=False)
async def inbound(
    body: InboundIn,
    db: DbSession,
    x_wa_secret: str = Header(default=""),
) -> dict[str, str | None]:
    """
    Ağ geçidinden gelen mesaj. Kimlik doğrulaması paylaşılan sır ile.

    Bu uç açık kalırsa biri sahte "veli mesajı" uydurup otomatik yanıt
    tetikleyebilir ve öğrenci konumu sızdırabilir — sır zorunlu.
    """
    if not settings.wa_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "webhook sırrı tanımlı değil")
    if not hmac.compare_digest(x_wa_secret, settings.wa_webhook_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "geçersiz sır")

    # Tek kurumlu dağıtım (Faz 0 kararı)
    tenant = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kurum tanımlı değil")

    thread, reply = await chat.handle_inbound(
        db, tenant, body.phone, body.text.strip(), body.name
    )
    await db.commit()

    # Anlaşılmayan mesajı yöneticiye ilet
    if reply is None and settings.admin_whatsapp:
        who = thread.guardian_name or thread.display_name or thread.phone
        await _notify_admin(
            f"NÖBET — yanıtlanamayan mesaj\n\n"
            f"Gönderen: {who} ({thread.phone})\n"
            f"Mesaj: {body.text.strip()[:300]}\n\n"
            f"Panelden yanıtlayın."
        )

    return {"reply": reply}


async def _notify_admin(text: str) -> None:
    """Yönetici bildirimi başarısız olursa gelen mesaj yine de kaydedilmiştir."""
    try:
        ch = notify.build_channel()
        await ch.send(settings.admin_whatsapp, text)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Panel uçları
# ---------------------------------------------------------------------------
@router.get("/wa/threads", response_model=list[ThreadOut])
async def list_threads(user: StaffUser, db: DbSession) -> list[ThreadOut]:
    rows = (
        await db.execute(
            select(WaThread)
            .where(WaThread.tenant_id == user.tenant_id)
            # İlgi bekleyenler önce, sonra en yeni mesaj
            .order_by(
                WaThread.needs_attention.desc(),
                WaThread.last_message_at.desc().nullslast(),
            )
            .limit(100)
        )
    ).scalars().unique().all()
    return [ThreadOut.model_validate(t) for t in rows]


@router.get("/wa/threads/{thread_id}/messages", response_model=list[MessageOut])
async def thread_messages(
    thread_id: uuid.UUID, user: StaffUser, db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MessageOut]:
    thread = await _get_thread(db, user.tenant_id, thread_id)

    rows = (
        await db.execute(
            select(WaMessage)
            .where(WaMessage.thread_id == thread.id)
            .order_by(WaMessage.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    # Okundu say — panelde açıldı
    thread.unread_count = 0
    await db.commit()

    return [MessageOut.model_validate(m) for m in reversed(rows)]


@router.post("/wa/threads/{thread_id}/reply", response_model=MessageOut,
             status_code=status.HTTP_201_CREATED)
async def reply(
    thread_id: uuid.UUID, body: ReplyIn, user: StaffUser, db: DbSession
) -> MessageOut:
    """Yöneticinin elle yanıtı. Gönderim başarısız olsa da kayda geçer."""
    thread = await _get_thread(db, user.tenant_id, thread_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "mesaj boş")

    msg = WaMessage(
        thread_id=thread.id, direction=WaDirection.out,
        body=text, is_auto=False, sent_by=user.id,
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                f"{settings.wa_gateway_url.rstrip('/')}/send",
                json={"to": thread.phone, "text": text},
            )
        if r.status_code >= 400:
            msg.error = f"{r.status_code}: {r.text[:200]}"
    except Exception as exc:
        msg.error = str(exc)[:300]

    db.add(msg)
    thread.last_message_at = dt.datetime.now(dt.timezone.utc)
    # Yönetici müdahale etti; ilgi bayrağı düşer
    thread.needs_attention = False
    await db.commit()
    await db.refresh(msg)

    if msg.error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"mesaj kaydedildi ama gönderilemedi: {msg.error}",
        )
    return MessageOut.model_validate(msg)


@router.post("/wa/threads/{thread_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_thread(
    thread_id: uuid.UUID, user: StaffUser, db: DbSession
) -> None:
    """Yanıt gerektirmeyen konuşmayı işaretten çıkar."""
    thread = await _get_thread(db, user.tenant_id, thread_id)
    thread.needs_attention = False
    thread.unread_count = 0
    await db.commit()


@router.get("/wa/unread", response_model=dict)
async def unread_summary(user: StaffUser, db: DbSession) -> dict:
    """
    Kenar çubuğundaki "ilgi bekliyor" rozeti.

    ⚠️ 2026-08-10'da iki kusur düzeltildi; ikisi de bu dosyadaki diğer beş
    uçta doğru yapılmıştı, yalnızca burada atlanmıştı:
      1. `CurrentUser` idi → koç rolü yöneticinin gelen kutusu sayacını
         görebiliyordu. `StaffUser` oldu (§1.3).
      2. `tenant_id` filtresi yoktu → çok kurumlu kurulumda sayaç TÜM
         kurumların konuşmalarını topluyordu. Tek kurum dağıtıldığı için
         canlıda etkisi olmadı, ama şema baştan çok kurumlu.
    """
    attention = (
        await db.execute(
            select(func.count()).select_from(WaThread)
            .where(
                WaThread.tenant_id == user.tenant_id,
                WaThread.needs_attention.is_(True),
            )
        )
    ).scalar_one()
    return {"needs_attention": attention}


async def _get_thread(db, tenant_id, thread_id) -> WaThread:
    t = (
        await db.execute(
            select(WaThread).where(
                WaThread.id == thread_id, WaThread.tenant_id == tenant_id
            )
        )
    ).scalars().unique().one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "konuşma bulunamadı")
    return t
