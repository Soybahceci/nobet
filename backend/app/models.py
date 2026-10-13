"""
NÖBET — ORM modelleri
======================
Kaynak: docs/nobet-faz1-sistem-sozlesmesi.md §1.2 (KONTRAT v1.1)

⚠️ Tablolar `infra/postgres/init/01-schema.sql` ile OLUŞTURULDU.
   Buradaki modeller o şemayı YANSITIR, üretmez. Enum tipleri veritabanında
   zaten var (create_type=False) — SQLAlchemy yeniden yaratmaya çalışmamalı.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ---------------------------------------------------------------------------
# Enum'lar — isimler veritabanındaki CREATE TYPE ile birebir aynı olmalı
# ---------------------------------------------------------------------------
class PersonType(str, enum.Enum):
    student = "student"
    staff = "staff"
    coach = "coach"


class PersonStatus(str, enum.Enum):
    active = "active"
    passive = "passive"


class CredentialType(str, enum.Enum):
    rfid = "rfid"
    fingerprint = "fingerprint"


class CredentialStatus(str, enum.Enum):
    active = "active"
    lost = "lost"
    revoked = "revoked"


class ZoneKind(str, enum.Enum):
    entrance = "entrance"
    library = "library"
    classroom = "classroom"


class NodeDirection(str, enum.Enum):
    in_ = "in"
    out = "out"
    toggle = "toggle"


class NodeStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    disabled = "disabled"


class SessionState(str, enum.Enum):
    open = "open"
    closed = "closed"
    auto_closed = "auto_closed"
    corrected = "corrected"


class AppRole(str, enum.Enum):
    super_admin = "super_admin"
    kurum_admin = "kurum_admin"
    operator = "operator"
    coach = "coach"


class EventDecision(str, enum.Enum):
    granted = "granted"
    unknown_credential = "unknown_credential"
    revoked = "revoked"
    duplicate = "duplicate"
    disabled_node = "disabled_node"


def _pg(py_enum: type[enum.Enum], name: str) -> PgEnum:
    """Var olan PostgreSQL enum tipine bağla; yeniden yaratma."""
    return PgEnum(
        py_enum,
        name=name,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )


_UUID = UUID(as_uuid=True)
_TS = DateTime(timezone=True)


# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Istanbul")
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class Person(Base):
    __tablename__ = "person"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    person_type: Mapped[PersonType] = mapped_column(_pg(PersonType, "person_type"), nullable=False)
    # KVKK veri minimizasyonu: TC kimlik no saklanmaz (§1.2)
    birth_date: Mapped[dt.date | None] = mapped_column(Date)
    external_ref: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PersonStatus] = mapped_column(
        _pg(PersonStatus, "person_status"), nullable=False, default=PersonStatus.active
    )
    # --- Kayıt alanları (kontrat v1.4) ---
    grade: Mapped[str | None] = mapped_column(Text)          # öğrenci sınıf/seviye
    # Kuruma katılma: öğrencide kayıt, personelde işe başlama tarihi
    started_at: Mapped[dt.date | None] = mapped_column(Date)
    address: Mapped[str | None] = mapped_column(Text)        # ⚠️ kişisel veri
    title: Mapped[str | None] = mapped_column(Text)          # personel unvan
    department: Mapped[str | None] = mapped_column(Text)     # personel departman

    # KVKK silme talebi üzerine anonimleştirme zamanı (dolu ise kimlik
    # alanları temizlenmiştir)
    anonymized_at: Mapped[dt.datetime | None] = mapped_column(_TS)

    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())

    credentials: Mapped[list[Credential]] = relationship(back_populates="person", lazy="selectin")

    @property
    def is_minor(self) -> bool:
        """§1.2 türetilen alan — 18 yaş altı bildirim mantığı buna bakar."""
        if self.birth_date is None:
            return False
        today = dt.date.today()
        age = today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )
        return age < 18


class Guardian(Base):
    __tablename__ = "guardian"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class PersonGuardian(Base):
    __tablename__ = "person_guardian"

    person_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True)
    guardian_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("guardian.id", ondelete="CASCADE"), primary_key=True)
    relation: Mapped[str] = mapped_column(Text, nullable=False)   # anne | baba | vasi
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Credential(Base):
    __tablename__ = "credential"
    __table_args__ = (
        UniqueConstraint("tenant_id", "type", "identifier", name="credential_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("person.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[CredentialType] = mapped_column(_pg(CredentialType, "credential_type"), nullable=False)
    # RFID: UID hex, BÜYÜK HARF, ayraçsız (or. A1B2C3D4)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CredentialStatus] = mapped_column(
        _pg(CredentialStatus, "credential_status"), nullable=False, default=CredentialStatus.active
    )
    issued_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    revoked_at: Mapped[dt.datetime | None] = mapped_column(_TS)

    person: Mapped[Person] = relationship(back_populates="credentials", lazy="joined")


class Zone(Base):
    __tablename__ = "zone"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[ZoneKind] = mapped_column(_pg(ZoneKind, "zone_kind"), nullable=False)
    parent_zone_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("zone.id"))
    auto_close_at: Mapped[dt.time | None] = mapped_column(Time)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class Node(Base):
    __tablename__ = "node"
    __table_args__ = (
        # Faz 13a-1: eskiden `node_key` GLOBAL benzersizdi.
        UniqueConstraint("tenant_id", "node_key", name="node_tenant_key_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("zone.id"), nullable=False)
    # firmware include/config.h NODE_KEY ile BİREBİR aynı olmalı.
    # ⚠️ Benzersizlik KURUM İÇİNDE (Faz 13a-1). Eskiden globaldi; SaaS'ta
    # her kurumun kapısındaki okuyucu `giris-01` adını alacağı için global
    # kısıt ikinci kurumu engellerdi. Kısıt __table_args__'ta.
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[NodeDirection] = mapped_column(
        _pg(NodeDirection, "node_direction"), nullable=False, default=NodeDirection.toggle
    )
    reader_type: Mapped[CredentialType] = mapped_column(
        _pg(CredentialType, "credential_type"), nullable=False, default=CredentialType.rfid
    )
    firmware_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    # Kontrat v1.2 (§2.4) — okuyucunun sessiz arızasını görünür kılar.
    # NULL = firmware bildirmiyor (eski sürüm).
    reader_ok: Mapped[bool | None] = mapped_column(Boolean)
    reader_reinits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[NodeStatus] = mapped_column(
        _pg(NodeStatus, "node_status"), nullable=False, default=NodeStatus.offline
    )
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class Event(Base):
    """⚠️ DEĞİŞMEZ. Veritabanında UPDATE/DELETE trigger ile engelli."""

    __tablename__ = "event"
    __table_args__ = (
        UniqueConstraint("node_id", "seq", name="event_node_seq_unique"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("node.id"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cred_type: Mapped[CredentialType] = mapped_column(_pg(CredentialType, "credential_type"), nullable=False)
    # Ham okunan değer — kayıtlı olmasa bile yazılır (enrollment yakıtı, §3.4)
    cred_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("credential.id"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("person.id"))
    decision: Mapped[EventDecision] = mapped_column(_pg(EventDecision, "event_decision"), nullable=False)
    device_uptime_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)      # payload "up"
    device_tx_uptime_ms: Mapped[int | None] = mapped_column(BigInteger)            # payload "up_tx" (v1.1)
    device_ts: Mapped[dt.datetime | None] = mapped_column(_TS)
    server_ts: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    effective_ts: Mapped[dt.datetime] = mapped_column(_TS, nullable=False)
    from_buffer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # payload "buf"
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Arayüzde kart numarası yerine kişi adı gösterilebilsin diye.
    # lazy="joined" zorunlu: async oturumda tembel yükleme MissingGreenlet
    # hatası verir. Olay listeleri zaten sayfalı, JOIN maliyeti önemsiz.
    person: Mapped[Person | None] = relationship(
        lazy="joined", foreign_keys=[person_id], viewonly=True
    )

    @property
    def person_name(self) -> str | None:
        """Kayıtsız kart okumalarında kişi yoktur — None döner."""
        return self.person.full_name if self.person is not None else None


class AttendanceSession(Base):
    __tablename__ = "attendance_session"
    __table_args__ = (
        CheckConstraint("exited_at IS NULL OR exited_at >= entered_at", name="session_time_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("person.id", ondelete="CASCADE"), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("zone.id"), nullable=False)
    # ⚠️ NULL olabilir (Faz 13a-5): elle açılan oturumun olayı YOKTUR.
    # Kart kaynaklı oturumda dolu olması veritabanı kısıtıyla garanti.
    entry_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id"))
    exit_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id"))
    entered_at: Mapped[dt.datetime] = mapped_column(_TS, nullable=False)
    exited_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[SessionState] = mapped_column(
        _pg(SessionState, "session_state"), nullable=False, default=SessionState.open
    )
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    note: Mapped[str | None] = mapped_column(Text)

    # --- Faz 13a-5: elle giriş ---
    # 'card'  → okuyucudan geldi, entry_event_id dolu
    # 'manual'→ görevli elle açtı, entry_event_id NULL, created_by dolu
    # İnsan müdahalesi TÜRETİLMİŞ katmanda kalır; ham olay akışı saf kalır.
    entry_source: Mapped[str] = mapped_column(Text, nullable=False, default="card")
    # Elle açan kullanıcı. Bu yetki kötüye kullanılabilir; izsiz bırakılmaz.
    created_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("app_user.id"))

    person: Mapped[Person] = relationship(lazy="joined", viewonly=True)
    zone: Mapped[Zone] = relationship(lazy="joined", viewonly=True)

    @property
    def person_name(self) -> str | None:
        return self.person.full_name if self.person is not None else None

    @property
    def zone_name(self) -> str | None:
        return self.zone.name if self.zone is not None else None
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class AppUser(Base):
    """
    KİMLİK — kişi kim. Hangi kurumda ne olduğu `Membership`'te (Faz 13a-0).

    `tenant_id` / `role` / `person_id` burada YOK; migration 0012 ile
    `membership`'e taşındılar. Aynı e-posta birden fazla kuruma üye
    olabilsin diye. Gerekçe: mimari doküman §3b.
    """
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)   # argon2id (§1.2)
    # Kimliğin tamamen kapatılması. Tek bir kurumdaki erişimi kesmek için
    # `membership.is_active` kullanılır — ikisi farklı şeyler.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    # Parolanın en son değiştiği an. Bundan ÖNCE üretilmiş token'lar
    # reddedilir (denetim Y-1) — böylece parola değiştirmek çalınmış
    # oturumu gerçekten düşürür. Parola yazan her yer bunu güncellemeli.
    password_changed_at: Mapped[dt.datetime] = mapped_column(
        _TS, nullable=False, server_default=func.now()
    )


class EdgeDevice(Base):
    """
    Kurumun kenar cihazı (Faz 13a-1, mimari §2.4).

    Buluta giden her istek bu cihazın jetonuyla imzalanır ve **kurum
    yalnızca jetondan belirlenir** — istekteki hiçbir alandan değil.
    Bugünkü alım hattı kurumu payload'daki `node` alanından çözüyor; SaaS'ta
    bu, bir kurumun düğümünün başka kurumun kaydına olay yazabilmesi
    demektir. 13a-4'te kapanacak.

    Jeton ve eşleştirme kodu **hash'lenerek** saklanır: bulut veritabanı
    sızsa bile kenar taklit edilemez (`password_reset` ile aynı gerekçe).
    """
    __tablename__ = "edge_device"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # NULL = henüz eşleşmemiş
    token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    pairing_code_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    pairing_expires_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    paired_at: Mapped[dt.datetime | None] = mapped_column(_TS)

    # --- kenardan gelen sağlık bilgisi ---
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    agent_version: Mapped[str | None] = mapped_column(Text)
    # §10.3(1): kenar olayı KENDİ saatiyle damgalıyor; sapma izlenmezse
    # yanlış saatli devam kaydı fark edilmez.
    clock_skew_ms: Mapped[int | None] = mapped_column(BigInteger)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # §3.1b: kalıcı reddedilenler. >0 ise panelde uyarı.
    dead_letter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    card_version_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class SyncState(Base):
    """
    Kart kopyasının kurum başına sürüm sayacı (Faz 13a-1).

    ⚠️ Bu sayacı **veritabanı tetikleyicisi** artırır, uygulama kodu değil.
    Kart kopyasını etkileyen yazma noktaları dağınık (kart atama, iptal,
    kişi pasifleştirme, KVKK anonimleştirme, toplu içe aktarma); her birinde
    "sayacı artırmayı unutma" demek, er geç unutulacak demektir. Unutulduğunda
    kenar bayat kart listesiyle çalışır ve **kimse fark etmez.**

    Senkron artımlı değil, anlık görüntü: kenar sayacı farklı görürse listenin
    tamamını indirir. 1500 kişide ~100 KB; artımlılığın makinesi bu boyutta
    karşılığını vermiyor. Protokoldeki `?since=` duruyor, ileride gerçekten
    artımlıya geçilirse kenar tarafı değişmez.
    """
    __tablename__ = "sync_state"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    card_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class SubscriptionStatus(str, enum.Enum):
    """
    Abonelik kademeleri (mimari §5.2). PG enum DEĞİL — kolon `text` + CHECK;
    kademe listesi ileride genişleyebilir ve PG enum'a değer eklemek
    migration'da zahmetli.
    """
    active = "active"
    warning = "warning"          # ödeme gecikti — her şey açık, panelde bandrol
    restricted = "restricted"    # panel salt okunur, veli ve SMS kapalı
    suspended = "suspended"      # panel kapalı; KENAR kayıt tutmaya devam eder


class Subscription(Base):
    """
    Kurumun abonelik durumu (Faz 13b-1).

    ⭐ §5.1: **kurumun kendi kaydı hiçbir aşamada durdurulmaz.** Kesilen şey
    hizmettir, veri değil. En ağır kademede (`suspended`) bile kenar cihazı
    kayıt tutmaya devam eder ve ödeme gelince kuyruk buluta akar.

    ⚠️ Durum YALNIZCA burada tutulur. Mimari §8 `tenant.status` da
    öngörüyordu; aynı gerçeği iki yerde tutmak er geç birbirini tutmayan
    iki cevap üretir.

    Her kurumun satırı olduğu veritabanı tetikleyicisiyle garanti
    (`tenant_seed_subscription`).
    """
    __tablename__ = "subscription"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    period_start: Mapped[dt.date | None] = mapped_column(Date)
    period_end: Mapped[dt.date | None] = mapped_column(Date)
    # SMS gerçek para (§5.3). 0 = sınırsız.
    sms_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sms_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("app_user.id"))
    suspended_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    updated_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class LoginAttempt(Base):
    """
    Giriş kaba kuvvet sayacı (denetim Y-2).

    ⚠️ Anahtar **e-posta**, kullanıcı değil. Hesabın var olup olmadığından
    bağımsız sayılır; aksi hâlde kilitlenme davranışının kendisi hesabın
    varlığını ele verirdi.
    """
    __tablename__ = "login_attempt"

    email: Mapped[str] = mapped_column(Text, primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(_TS)
    last_attempt_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class Membership(Base):
    """
    ÜYELİK — bu kimlik, hangi kurumda, hangi sıfatla (Faz 13a-0).

    Bir kişi bir kurumda **en fazla bir** üyeliğe sahiptir. Aynı kurumda iki
    role ihtiyaç doğarsa rol matrisi genişletilir, ikinci üyelik açılmaz —
    yoksa "hangi üyelikle giriş yaptım" sorusu her istekte belirsizleşir.

    Yetki kararları (rol, görünürlük) HER ZAMAN buradan okunur; jetondaki
    `tid` hangi üyeliğin etkin olduğunu söyler. Kurumun kullanıcının
    kendisinden değil jetondan gelmesi, kenar cihazları için konan
    kuralın (mimari §2.4) insan kullanıcılara uygulanmış hâlidir.
    """
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="membership_user_tenant_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    person_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("person.id"))
    role: Mapped[AppRole] = mapped_column(_pg(AppRole, "app_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class NotificationChannel(str, enum.Enum):
    whatsapp = "whatsapp"
    sms = "sms"
    email = "email"
    dryrun = "dryrun"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"


class Notification(Base):
    """
    Veli bildirimi (Faz 8).

    `UNIQUE(event_id, guardian_id)` sayesinde bir olay için bir veliye
    yalnızca tek bildirim üretilebilir. İşçi çökse ya da iki kopya aynı anda
    çalışsa bile veli mükerrer mesaj almaz.
    """

    __tablename__ = "notification"
    # ⚠️ Mükerrer koruması artık KISMİ İNDEKSLERLE (migration 0015):
    # `notification_once_event` ve `notification_once_session`.
    # `event_id` NULL olabildiği için tek bir UNIQUE yetmiyordu —
    # PostgreSQL'de NULL'lar benzersizlik kontrolüne girmez.

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    # İkisinden TAM BİRİ dolu olur (veritabanı kısıtı):
    #   event_id   → kart okumasından doğan bildirim
    #   session_id → elle açılan oturumdan doğan bildirim (Faz 13a-5)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("attendance_session.id", ondelete="CASCADE")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("person.id"), nullable=False)
    guardian_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("guardian.id"), nullable=False)
    # 'GİRİŞ' | 'ÇIKIŞ' — bir OTURUM iki bildirim uretir (giris ve cikis),
    # ikisi de ayni satira baglidir; yon olmadan mukerrer engeli ikinciyi
    # yanlislikla reddederdi (migration 0016).
    direction: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[NotificationChannel] = mapped_column(
        _pg(NotificationChannel, "notification_channel"), nullable=False
    )
    # Gönderim anındaki numara — veli sonradan değiştirse de kayıt bozulmaz
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Olayın GERÇEKTEN olduğu an — bildirimin üretildiği an değil.
    # İkisi normalde saniyelerle ayrılır, ama düğüm kesintiden sonra
    # tamponunu boşalttığında olay saatlerce eski olabilir. Gecikmeli
    # bildirim damgası (§8) bu iki zamanın farkından hesaplanır;
    # `created_at` kullanılsaydı tampon gecikmesi hiç görünmezdi.
    occurred_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    status: Mapped[NotificationStatus] = mapped_column(
        _pg(NotificationStatus, "notification_status"),
        nullable=False, default=NotificationStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    sent_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())

    person: Mapped[Person] = relationship(lazy="joined", viewonly=True)
    guardian: Mapped[Guardian] = relationship(lazy="joined", viewonly=True)

    @property
    def person_name(self) -> str | None:
        return self.person.full_name if self.person is not None else None

    @property
    def guardian_name(self) -> str | None:
        return self.guardian.full_name if self.guardian is not None else None


class WaDirection(str, enum.Enum):
    in_ = "in"
    out = "out"


class WaThread(Base):
    """
    Telefon numarası başına bir konuşma.

    `guardian_id` NULL ise numara tanınmıyor demektir — bu konuşmaya
    **asla öğrenci bilgisi verilmez**, doğrudan yöneticiye yükseltilir.
    """

    __tablename__ = "wa_thread"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="wa_thread_phone_once"),
    )

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tenant.id"), nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)   # yalnızca rakam
    display_name: Mapped[str | None] = mapped_column(Text)
    guardian_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("guardian.id"))
    needs_attention: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())

    guardian: Mapped[Guardian | None] = relationship(lazy="joined", viewonly=True)

    @property
    def guardian_name(self) -> str | None:
        return self.guardian.full_name if self.guardian is not None else None


class WaMessage(Base):
    __tablename__ = "wa_message"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True, server_default=func.gen_random_uuid())
    thread_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("wa_thread.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[WaDirection] = mapped_column(_pg(WaDirection, "wa_direction"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Otomatik yanıt mı — hangi bilginin makine tarafından verildiği denetlenebilmeli
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("app_user.id"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class NotifySetting(Base):
    """Kurum başına bildirim ayarı. Kanal ve SMS sağlayıcı arayüzden değişir."""

    __tablename__ = "notify_setting"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="dryrun")
    sms_provider: Mapped[str | None] = mapped_column(Text)
    # Sır olmayan yapılandırma — arayüzde görünür ve düzenlenebilir
    sms_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Fernet ile şifreli kimlik bilgileri
    secret_enc: Mapped[str | None] = mapped_column(Text)

    # --- SMTP (kontrat v1.7) ---
    # Parola sıfırlama/davet e-postaları ve (channel="email" ise) veli
    # bildirimleri buradan çıkar.
    smtp_host: Mapped[str | None] = mapped_column(Text)
    smtp_port: Mapped[int | None] = mapped_column(Integer)
    smtp_security: Mapped[str | None] = mapped_column(Text)   # starttls|ssl|none
    smtp_from: Mapped[str | None] = mapped_column(Text)
    smtp_user: Mapped[str | None] = mapped_column(Text)
    # ⚠️ SMS sırrından AYRI sütun: tek alanda tutulsalardı birini
    # değiştirmek diğerini silerdi.
    smtp_secret_enc: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("app_user.id"))


class Lesson(Base):
    """
    Ders programı (kontrat §1.2, v1.9).

    Derslik yoklaması, "geldi" saymak için bir zaman aralığına ihtiyaç duyuyor.
    Önce bu aralık her yoklamada **elle** giriliyordu: operatör ders saatini
    kendi yazıyordu. Hem yorucu hem hataya açık — bir dakikalık kayma
    öğrencileri devamsız gösterebiliyordu.

    ⚠️ Saatler **yerel saat** olarak saklanır (`time`, tarih ve dilim yok).
    Kurumun dilimi `tenant.timezone`'da. UTC'ye çevirme sunucuda yapılır;
    tarayıcının diliminden hesaplamak, yurt dışından bakan bir yöneticide
    yanlış aralık üretirdi.
    """

    __tablename__ = "lesson"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 1 AND 7", name="lesson_weekday_range"),
        CheckConstraint("ends_at > starts_at", name="lesson_time_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tenant.id"), nullable=False
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("zone.id", ondelete="CASCADE"), nullable=False
    )
    # `person.grade` ile eşleşir; ayrı şube tablosu yok (Faz 10 kararı)
    grade: Mapped[str] = mapped_column(String(40), nullable=False)
    # ISO: 1 = Pazartesi … 7 = Pazar (Python `isoweekday()` ile aynı)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[dt.time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[dt.time] = mapped_column(Time, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class ResetPurpose(str, enum.Enum):
    reset = "reset"     # kullanıcı kendi talep etti — 1 saat
    invite = "invite"   # yönetici hesap açtı — 72 saat


class PasswordReset(Base):
    """
    Parola sıfırlama / davet jetonu (kontrat §1.2, v1.7).

    ⚠️ `token_hash` — düz metin jeton HİÇBİR ZAMAN saklanmaz. Veritabanını
    okuyabilen biri (yedek dosyası, sızıntı) aksi hâlde herkesin hesabını ele
    geçirebilirdi. Jeton yalnızca e-postada var; sistem onu bir daha göremez.
    """

    __tablename__ = "password_reset"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    purpose: Mapped[ResetPurpose] = mapped_column(
        _pg(ResetPurpose, "reset_purpose"), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(_TS, nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(_TS)
    created_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())


class CoachAssignment(Base):
    """Koç YALNIZCA buradaki öğrencileri görür (§1.3)."""

    __tablename__ = "coach_assignment"

    coach_person_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    student_person_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[dt.datetime] = mapped_column(_TS, server_default=func.now())
