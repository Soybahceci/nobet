"""
NÖBET — Kenar cihazı uçları (Faz 13a-2)
========================================
Mimari: docs/nobet-faz13-saas-mimarisi.md §2.4, §3.1, §3.1b, §3.2

⭐ **TEK EN ÖNEMLİ KURAL: kurum yalnızca JETONDAN belirlenir.**
İstek gövdesindeki hiçbir alan kurumu seçemez. Bugünkü MQTT alım hattı
kurumu payload'daki `node` alanından çözüyor; SaaS'ta bu, bir kurumun
düğümünün başka kurumun kaydına olay yazabilmesi demektir. Buradaki
`CurrentEdge` bağımlılığı o kapıyı baştan kapatıyor.

Jetonlar **hash'lenerek** saklanır (`password_reset` ile aynı gerekçe):
bulut veritabanını okuyabilen biri kenar cihazlarını taklit edemesin.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ingest
from app.db import set_tenant_scope
from app.deps import AdminUser, DbSession
from app.models import (
    Credential,
    CredentialStatus,
    EdgeDevice,
    Event,
    Node,
    Person,
    PersonStatus,
    Subscription,
    SyncState,
    Tenant,
)

log = logging.getLogger("nobet.edge")
router = APIRouter(tags=["edge"])

_bearer = HTTPBearer(auto_error=False)

# Eşleştirme kodu ömrü. Teknisyen kutuyu kurarken kullanır; hafta sonuna
# denk gelebilir ama sonsuz olmamalı.
PAIRING_TTL = dt.timedelta(hours=24)

# Tek istekte kabul edilecek en fazla olay. Sınırsız bırakmak, uzun bir
# kesinti sonrası kenarın 500 bin olayı tek istekte göndermesine ve isteğin
# zaman aşımına uğrayıp SONSUZA KADAR yeniden denenmesine yol açardı.
MAX_BATCH = 500


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def current_edge(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> EdgeDevice:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "kenar jetonu yok")

    device = (
        await db.execute(
            select(EdgeDevice).where(EdgeDevice.token_hash == _hash(creds.credentials))
        )
    ).scalar_one_or_none()
    if device is None or not device.is_active:
        # Geçersiz jeton ile pasif cihaz aynı cevabı alır.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "kenar jetonu geçersiz")

    # Satır düzeyi güvenlik (Faz 13b-3b). Kurum CİHAZIN kaydından gelir;
    # kenarın gönderdiği gövdeden değil. Bir kurumun kenar cihazı, çalınmış
    # bir kimlikle bile başka kurumun kartını/kişisini göremez.
    await set_tenant_scope(db, str(device.tenant_id))
    return device


CurrentEdge = Annotated[EdgeDevice, Depends(current_edge)]


# ---------------------------------------------------------------------------
# Yönetim: cihaz tanımlama ve eşleştirme kodu
# ---------------------------------------------------------------------------
class EdgeDeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    paired_at: dt.datetime | None
    last_seen_at: dt.datetime | None
    agent_version: str | None
    queue_depth: int
    dead_letter_count: int
    clock_skew_ms: int | None
    card_version_seen: int


class EdgeDeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PairingCodeOut(BaseModel):
    """⚠️ `code` yalnızca BU yanıtta görünür; sistem bir daha gösteremez."""
    code: str
    expires_at: dt.datetime


def _device_out(d: EdgeDevice) -> EdgeDeviceOut:
    return EdgeDeviceOut(
        id=d.id, name=d.name, is_active=d.is_active, paired_at=d.paired_at,
        last_seen_at=d.last_seen_at, agent_version=d.agent_version,
        queue_depth=d.queue_depth, dead_letter_count=d.dead_letter_count,
        clock_skew_ms=d.clock_skew_ms, card_version_seen=d.card_version_seen,
    )


@router.get("/edge-devices", response_model=list[EdgeDeviceOut])
async def list_devices(user: AdminUser, db: DbSession) -> list[EdgeDeviceOut]:
    rows = (
        await db.execute(
            select(EdgeDevice)
            .where(EdgeDevice.tenant_id == user.tenant_id)
            .order_by(EdgeDevice.created_at)
        )
    ).scalars().all()
    return [_device_out(d) for d in rows]


@router.post("/edge-devices", response_model=EdgeDeviceOut,
             status_code=status.HTTP_201_CREATED)
async def create_device(body: EdgeDeviceIn, user: AdminUser, db: DbSession) -> EdgeDeviceOut:
    device = EdgeDevice(tenant_id=user.tenant_id, name=body.name.strip())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return _device_out(device)


@router.post("/edge-devices/{device_id}/pairing-code", response_model=PairingCodeOut)
async def issue_pairing_code(
    device_id: uuid.UUID, user: AdminUser, db: DbSession
) -> PairingCodeOut:
    """
    Tek kullanımlık eşleştirme kodu üretir (mimari §10.3-4).

    Kod **hash'lenerek** saklanır; düz metni yalnızca bu yanıtta görünür.
    Yeni kod üretmek eskisini geçersiz kılar — kaybolan bir kod sonsuza
    kadar geçerli kalmasın.
    """
    device = (
        await db.execute(
            select(EdgeDevice).where(
                EdgeDevice.id == device_id, EdgeDevice.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kenar cihazı bulunamadı")

    # Elle yazılacak: okunması kolay, karışan harfler yok (I/1, O/0).
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    code = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"

    device.pairing_code_hash = _hash(code)
    device.pairing_expires_at = dt.datetime.now(dt.timezone.utc) + PAIRING_TTL
    await db.commit()
    log.info("eslestirme kodu uretildi: cihaz=%s", device.id)
    return PairingCodeOut(code=code, expires_at=device.pairing_expires_at)


# ---------------------------------------------------------------------------
# Kenar cihazının kullandığı uçlar
# ---------------------------------------------------------------------------
class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=40)


class PairOut(BaseModel):
    """⚠️ `token` yalnızca burada döner; hash'i saklanır, kendisi saklanmaz."""
    token: str
    tenant_id: uuid.UUID
    tenant_slug: str
    device_id: uuid.UUID
    device_name: str


@router.post("/edge/pair", response_model=PairOut)
async def pair(body: PairIn, db: DbSession) -> PairOut:
    """
    Eşleştirme: tek kullanımlık kod → kalıcı jeton.

    Bu uç **kimlik doğrulaması istemez** (cihazın henüz jetonu yok);
    güvenliği kodun kendisinden gelir: 12 karakter, 32 harflik alfabe,
    24 saat ömür, tek kullanım.
    """
    device = (
        await db.execute(
            select(EdgeDevice).where(EdgeDevice.pairing_code_hash == _hash(body.code.strip().upper()))
        )
    ).scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if device is not None and device.pairing_expires_at is not None:
        exp = device.pairing_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=dt.timezone.utc)
        if exp <= now:
            device = None

    if device is None or not device.is_active:
        # Geçersiz / süresi geçmiş / pasif — HEPSİ aynı cevap.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "eşleştirme kodu geçersiz ya da süresi dolmuş"
        )

    token = secrets.token_urlsafe(32)
    device.token_hash = _hash(token)
    device.paired_at = now
    # Kod tüketildi.
    device.pairing_code_hash = None
    device.pairing_expires_at = None
    await db.commit()

    slug = (
        await db.execute(select(Tenant.slug).where(Tenant.id == device.tenant_id))
    ).scalar_one()

    log.info("kenar cihazi eslesti: %s (kurum=%s)", device.id, slug)
    return PairOut(
        token=token, tenant_id=device.tenant_id, tenant_slug=slug,
        device_id=device.id, device_name=device.name,
    )


class EdgeEventIn(BaseModel):
    """Kenarın ilettiği tek olay. Alan adları MQTT şemasıyla aynı (§2.2)."""
    node_key: str
    seq: int
    cred_type: str = "rfid"
    cred_id: str
    up: int = 0
    up_tx: int | None = None
    buf: int | None = None
    # Kenarın KENDİ hesapladığı zaman (§10.3-1). Yoksa sunucu saati kullanılır.
    ts: dt.datetime | None = None
    clock_unsynced: bool = False


class EdgeEventsIn(BaseModel):
    events: list[EdgeEventIn]


class RejectedOut(BaseModel):
    seq: int
    node_key: str
    reason: str


class EdgeEventsOut(BaseModel):
    """
    Üç kova (mimari §3.1b). `rejected` olmadan, bulutun asla kabul
    edemeyeceği tek bir olay kenarın kuyruğunu **sonsuza kadar** tıkardı.
    """
    accepted: list[int] = Field(default_factory=list)
    duplicate: list[int] = Field(default_factory=list)
    rejected: list[RejectedOut] = Field(default_factory=list)
    card_version: int = 0


@router.post("/edge/events", response_model=EdgeEventsOut)
async def push_events(
    body: EdgeEventsIn, device: CurrentEdge, db: DbSession
) -> EdgeEventsOut:
    """
    Toplu olay alımı. **Idempotent** — `UNIQUE(node_id, seq)` sayesinde aynı
    toplu istek iki kez gelse de çift kayıt oluşmaz.

    Kurum `device.tenant_id`'den gelir; gövdedeki hiçbir alan onu seçemez.
    """
    # --- Abonelik kademesi (mimari §5.2) ------------------------------------
    # ⭐ `suspended` kurumda olay alımı DURUR ama kenar kayıt tutmaya devam
    # eder; ödeme gelince kuyruk akar (§5.1: kesilen şey hizmet, veri değil).
    #
    # ⚠️ Burada **503** dönmek hayati. `rejected` kovasına koymak KALICI ret
    # demektir; kenar o olayları ölü mektuba taşır ve **bir daha asla
    # göndermez** — yani ödeme yapıldığında o günlerin devam kaydı geri
    # gelmez. 503, kenarın `CloudError` olarak görüp kuyrukta tutmasını ve
    # yeniden denemesini sağlar.
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.tenant_id == device.tenant_id)
        )
    ).scalar_one_or_none()
    if sub is not None and sub.status == "suspended":
        log.info("kenar %s: abonelik askida, olay alimi ertelendi", device.id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "abonelik askıya alınmış — olaylar kenar cihazında bekletiliyor, "
            "ödeme sonrası aktarılacak",
        )

    if len(body.events) > MAX_BATCH:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"tek istekte en fazla {MAX_BATCH} olay gönderilebilir",
        )

    out = EdgeEventsOut()
    tid = device.tenant_id

    for ev in body.events:
        node = (
            await db.execute(
                select(Node).where(Node.node_key == ev.node_key, Node.tenant_id == tid)
            )
        ).scalar_one_or_none()

        if node is None:
            # KALICI ret: bu kurumda böyle bir düğüm yok ve yeniden denemek
            # durumu değiştirmez. Kuyrukta tutulursa arkasındaki her şey
            # tıkanır (§3.1b).
            out.rejected.append(RejectedOut(
                seq=ev.seq, node_key=ev.node_key, reason="unknown_node"
            ))
            continue

        existing = (
            await db.execute(
                select(Event.id).where(Event.node_id == node.id, Event.seq == ev.seq)
            )
        ).scalar_one_or_none()
        if existing is not None:
            out.duplicate.append(ev.seq)
            continue

        d: dict[str, Any] = {
            "v": 1, "node": ev.node_key, "seq": ev.seq,
            "cred": {"t": ev.cred_type, "id": ev.cred_id},
            "up": ev.up, "up_tx": ev.up_tx, "buf": ev.buf,
        }
        try:
            await ingest.handle_event(
                db, d, tenant_id=tid, effective_ts_override=ev.ts,
            )
            out.accepted.append(ev.seq)
        except KeyError as exc:
            # Bozuk kayıt — yeniden denemek düzeltmez.
            await db.rollback()
            out.rejected.append(RejectedOut(
                seq=ev.seq, node_key=ev.node_key, reason=f"malformed:{exc}"
            ))

    out.card_version = await _card_version(db, tid)
    if out.rejected:
        log.warning(
            "kenar %s: %d olay KALICI reddedildi", device.id, len(out.rejected)
        )
    return out


async def _card_version(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    v = (
        await db.execute(
            select(SyncState.card_version).where(SyncState.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    return int(v or 0)


class CardOut(BaseModel):
    identifier: str
    cred_type: str
    person_id: uuid.UUID
    full_name: str
    # Kenar kararı bu ikisine bakar: kart aktif mi, kişi aktif mi.
    active: bool


class CredentialsOut(BaseModel):
    version: int
    # `false` ise `cards` boştur: kenardaki kopya zaten güncel.
    changed: bool
    cards: list[CardOut] = Field(default_factory=list)


@router.get("/edge/credentials", response_model=CredentialsOut)
async def credentials_snapshot(
    device: CurrentEdge, db: DbSession, since: int = 0
) -> CredentialsOut:
    """
    Kart kopyası (mimari §3.2).

    ⚠️ **Artımlı değil, anlık görüntü.** `since` sürümle aynıysa boş döner;
    farklıysa listenin TAMAMI iner. 1500 kişide ~100 KB — artımlılığın
    makinesi bu boyutta karşılığını vermiyor. Parametre protokolde duruyor,
    ileride gerçekten artımlıya geçilirse kenar tarafı değişmez.
    """
    tid = device.tenant_id
    version = await _card_version(db, tid)

    if since == version:
        return CredentialsOut(version=version, changed=False)

    rows = (
        await db.execute(
            select(Credential, Person)
            .join(Person, Person.id == Credential.person_id)
            .where(Credential.tenant_id == tid)
        )
    ).all()

    cards = [
        CardOut(
            identifier=c.identifier,
            cred_type=c.type.value,
            person_id=p.id,
            # Anonimleştirilmiş kayıtta ad zaten temizlenmiş (KVKK).
            full_name=p.full_name,
            active=(c.status == CredentialStatus.active
                    and p.status == PersonStatus.active),
        )
        for c, p in rows
    ]
    return CredentialsOut(version=version, changed=True, cards=cards)


class HeartbeatIn(BaseModel):
    agent_version: str | None = None
    queue_depth: int = 0
    dead_letter_count: int = 0
    # Kenarın saati — bulut sapmayı kendisi hesaplar (§10.3-1).
    edge_time: dt.datetime | None = None
    card_version_seen: int = 0


class HeartbeatOut(BaseModel):
    server_time: dt.datetime
    card_version: int
    # Sapma 60 sn'yi aşarsa kenar NTP'ye başvurmalı; devam kaydının saati
    # buna bağlı.
    clock_skew_ms: int | None = None
    clock_warning: bool = False


@router.post("/edge/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn, device: CurrentEdge, db: DbSession
) -> HeartbeatOut:
    now = dt.datetime.now(dt.timezone.utc)
    skew_ms: int | None = None
    if body.edge_time is not None:
        et = body.edge_time
        if et.tzinfo is None:
            et = et.replace(tzinfo=dt.timezone.utc)
        skew_ms = int((et - now).total_seconds() * 1000)

    device.last_seen_at = now
    device.agent_version = body.agent_version
    device.queue_depth = body.queue_depth
    device.dead_letter_count = body.dead_letter_count
    device.card_version_seen = body.card_version_seen
    device.clock_skew_ms = skew_ms
    await db.commit()

    return HeartbeatOut(
        server_time=now,
        card_version=await _card_version(db, device.tenant_id),
        clock_skew_ms=skew_ms,
        clock_warning=skew_ms is not None and abs(skew_ms) > 60_000,
    )
