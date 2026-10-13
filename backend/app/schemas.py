"""NÖBET — API şemaları (kontrat §3)"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    AppRole,
    CredentialStatus,
    CredentialType,
    EventDecision,
    NodeDirection,
    NodeStatus,
    PersonStatus,
    PersonType,
    ResetPurpose,
    SessionState,
    ZoneKind,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    """Sayfalama zarfı — sayfalı tüm yanıtlar bunu genişletir."""
    total: int
    page: int
    size: int


# --- §3.1 Kimlik doğrulama -------------------------------------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    # Faz 13a-0: kimlik birden fazla kuruma üye olabilir. Tek üyelik varsa
    # boş bırakılır; birden fazlaysa sunucu seçenekleri döndürür ve istemci
    # seçimle birlikte tekrar gönderir.
    tenant_id: uuid.UUID | None = None


class UserOut(ORM):
    """
    ⚠️ Bu şema hem `AppUser`'dan hem `Principal`'dan doldurulur.
    `role` / `tenant_id` / `person_id` artık `app_user`'da değil
    `membership`'te; `Principal` bunları aynı adlarla sunduğu için
    `model_validate()` her iki durumda da çalışır.
    """
    id: uuid.UUID
    email: str
    role: AppRole
    tenant_id: uuid.UUID
    person_id: uuid.UUID | None
    is_active: bool
    # Faz 13b-1: arayüz `warning` kademesinde bandrol gösterir,
    # `restricted` kademesinde yazma düğmelerini gizler.
    subscription_status: str = "active"


class TenantChoice(BaseModel):
    """Birden fazla kuruma üye olan kullanıcıya sunulan seçenek."""
    tenant_id: uuid.UUID
    tenant_name: str
    role: AppRole


class LoginOut(BaseModel):
    """
    Girişin iki olası sonucu tek şemada.

    - **Çözüldü:** `access_token` dolu, `choices` boş.
    - **Seçim gerekiyor:** `access_token` boş, `choices` dolu — istemci
      kurum seçtirir ve `tenant_id` ile aynı uca tekrar gönderir.

    Ara bir "seçim jetonu" üretilmedi: ikinci istekte parola yeniden
    gönderiliyor. Yeni bir jeton türü (üretim, saklama, süre, iptal)
    getirmenin bedeli, tek ek istekten yüksek.
    """
    access_token: str | None = None
    token_type: str = "bearer"
    user: UserOut | None = None
    choices: list[TenantChoice] = Field(default_factory=list)


class TokenOut(BaseModel):
    """
    ⚠️ `refresh_token` YOK (denetim D-3). Refresh token yalnızca HttpOnly
    çerezde döner; gövdede de dönseydi arayüz onu saklayabilir ve
    korumanın anlamı kalmazdı.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str


class AccessOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- §3.2 Kişi -------------------------------------------------------------
class PersonOut(ORM):
    id: uuid.UUID
    full_name: str
    person_type: PersonType
    birth_date: dt.date | None
    external_ref: str | None
    phone: str | None
    email: str | None
    status: str
    is_minor: bool
    # Kayıt alanları (kontrat v1.4)
    grade: str | None = None
    started_at: dt.date | None = None
    address: str | None = None
    title: str | None = None
    department: str | None = None
    # Dolu ise kimlik alanları KVKK talebi üzerine temizlenmiştir
    anonymized_at: dt.datetime | None = None


class PersonIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    person_type: PersonType
    birth_date: dt.date | None = None
    external_ref: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    grade: str | None = Field(default=None, max_length=40)
    started_at: dt.date | None = None
    address: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)


class PersonPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    person_type: PersonType | None = None
    birth_date: dt.date | None = None
    external_ref: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    status: PersonStatus | None = None
    grade: str | None = Field(default=None, max_length=40)
    started_at: dt.date | None = None
    address: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)


class PersonPage(Page):
    items: list[PersonOut]


# --- Veli ------------------------------------------------------------------
class GuardianIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None


class GuardianOut(ORM):
    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None


class GuardianLinkIn(BaseModel):
    """Var olan veliyi bağla ya da yenisini oluştur."""
    guardian_id: uuid.UUID | None = None
    guardian: GuardianIn | None = None
    relation: str = Field(default="vasi", max_length=20)
    is_primary: bool = False
    notify_enabled: bool = True


class GuardianLinkPatch(BaseModel):
    """
    Veli düzenleme. Kimlik alanları (`full_name`, `phone`, `email`) `guardian`
    satırına, ilişki alanları `person_guardian` bağına yazılır.

    ⚠️ `guardian` çoka-çok: aynı veli birden fazla öğrenciye bağlı olabilir
    (kardeşler). Kimlik alanlarını değiştirmek **hepsini** etkiler; ilişki
    alanları ise yalnızca bu bağa aittir.
    """
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, min_length=1, max_length=40)
    email: EmailStr | None = None
    relation: str | None = Field(default=None, max_length=20)
    is_primary: bool | None = None
    notify_enabled: bool | None = None


class GuardianLinkOut(GuardianOut):
    relation: str
    is_primary: bool
    notify_enabled: bool
    # Bu velinin bağlı olduğu öğrenci sayısı. Kimlik alanları `guardian`
    # satırında ortak olduğu için arayüz "bu değişiklik N öğrenciyi etkiler"
    # uyarısını buradan üretiyor.
    linked_person_count: int = 1


# --- §3.3 Credential -------------------------------------------------------
class CredentialOut(ORM):
    id: uuid.UUID
    person_id: uuid.UUID
    type: CredentialType
    identifier: str
    label: str | None
    status: CredentialStatus
    issued_at: dt.datetime


class CredentialIn(BaseModel):
    person_id: uuid.UUID
    type: CredentialType = CredentialType.rfid
    identifier: str = Field(min_length=4, max_length=40)
    label: str | None = None


class CredentialPatch(BaseModel):
    status: CredentialStatus
    label: str | None = None


# --- §3.4 Enrollment -------------------------------------------------------
class EnrollPendingOut(BaseModel):
    event_id: int
    cred_type: CredentialType
    cred_identifier: str
    node_name: str
    seen_at: dt.datetime


class EnrollClaimIn(BaseModel):
    event_id: int
    person_id: uuid.UUID
    label: str | None = None


# --- §3.5 Düğüm -----------------------------------------------------------
class NodeOut(ORM):
    id: uuid.UUID
    node_key: str
    name: str
    zone_id: uuid.UUID
    direction: str
    reader_type: CredentialType
    firmware_version: str | None
    last_seen_at: dt.datetime | None
    status: NodeStatus
    # Kontrat v1.2 — None: firmware bildirmiyor
    reader_ok: bool | None = None
    reader_reinits: int = 0


# --- §3.6 Olaylar ----------------------------------------------------------
class EventOut(ORM):
    id: int
    seq: int
    node_id: uuid.UUID
    cred_type: CredentialType
    cred_identifier: str
    person_id: uuid.UUID | None
    # Kayıtsız kart okumasında None — arayüz o zaman kart numarasını gösterir
    person_name: str | None = None
    decision: EventDecision
    effective_ts: dt.datetime
    server_ts: dt.datetime
    from_buffer: bool


class EventPage(Page):
    items: list[EventOut]


# --- §3.6 Oturumlar --------------------------------------------------------
class SessionOut(ORM):
    id: uuid.UUID
    person_id: uuid.UUID
    person_name: str | None = None
    zone_id: uuid.UUID
    zone_name: str | None = None
    entered_at: dt.datetime
    exited_at: dt.datetime | None
    duration_seconds: int | None
    state: SessionState
    note: str | None
    # Faz 13a-5: 'card' | 'manual'. Arayüz elle açılan kaydı işaretler ki
    # rapora bakan kişi neyin kart, neyin insan girişi olduğunu bilsin.
    entry_source: str = "card"


class ManualSessionIn(BaseModel):
    """
    Elle giriş/çıkış (Faz 13a-5).

    Okuyucular gibi **değiştirmeli (toggle)** çalışır: kişinin o mekânda açık
    oturumu varsa kapanır, yoksa açılır. Kapıdaki görevlinin "giriş mi çıkış
    mı" diye düşünmesi gerekmez — kartla aynı davranış.
    """
    person_id: uuid.UUID
    zone_id: uuid.UUID
    # Görevli olayı sonradan kaydedebilir ("çocuk 08:00'de geldi, ben
    # 08:30'da giriyorum"). Boşsa şimdi.
    at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class ManualSessionOut(SessionOut):
    # "GİRİŞ" | "ÇIKIŞ" — arayüz görevliye ne olduğunu söylesin.
    direction: str


class SessionPatch(BaseModel):
    """§3.6 — unutulan çıkışın düzeltilmesi. Ham olaylar DEĞİŞMEZ."""
    exited_at: dt.datetime | None = None
    note: str | None = None


class SessionPage(Page):
    items: list[SessionOut]


class InsideNowOut(BaseModel):
    person_id: uuid.UUID
    full_name: str
    person_type: PersonType
    zone_id: uuid.UUID
    zone_name: str
    entered_at: dt.datetime
    elapsed_seconds: int


# --- §3.5 Mekân ------------------------------------------------------------
class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ZoneKind
    parent_zone_id: uuid.UUID | None = None
    auto_close_at: dt.time | None = None


class ZoneOut(ORM):
    id: uuid.UUID
    name: str
    kind: ZoneKind
    parent_zone_id: uuid.UUID | None
    auto_close_at: dt.time | None


class NodeIn(BaseModel):
    node_key: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)
    zone_id: uuid.UUID
    direction: NodeDirection = NodeDirection.toggle
    reader_type: CredentialType = CredentialType.rfid


class NodePatch(BaseModel):
    name: str | None = None
    zone_id: uuid.UUID | None = None
    direction: NodeDirection | None = None
    status: NodeStatus | None = None


class NodeHealthOut(BaseModel):
    node_key: str
    status: NodeStatus
    last_seen_at: dt.datetime | None
    firmware_version: str | None
    events_24h: int
    unknown_24h: int
    reader_ok: bool | None = None
    reader_reinits: int = 0


# --- §3.7 Dashboard --------------------------------------------------------
class DashboardOut(BaseModel):
    inside_now: dict[str, int]
    today_events: int
    nodes: dict[str, int]
    open_sessions: int
    unknown_reads_24h: int


# --- §3.1 Kullanıcı hesapları ---------------------------------------------
# Parola alt sınırı `app/bootstrap.py` ile aynı tutuluyor; iki yoldan
# oluşturulan hesapların gücü farklı olmasın.
MIN_PASSWORD_LEN = 12


class AppUserOut(ORM):
    """
    Yönetim listesindeki satır.

    ⚠️ Yukarıdaki `UserOut` ile karıştırılmamalı: o, giriş yanıtında dönen
    **oturum sahibinin kendisi** (`tenant_id` taşır). Bu ise yöneticinin
    BAŞKA hesaplar hakkında gördüğü bilgi. İkisi aynı adı taşırsa Python
    sonuncuyu alır ve giriş ucu sessizce bozulur — bir kez oldu.
    """
    id: uuid.UUID
    email: str
    role: AppRole
    is_active: bool
    person_id: uuid.UUID | None
    # Bağlı kişinin adı — arayüz her satır için ayrı istek atmasın diye
    person_name: str | None = None
    last_login_at: dt.datetime | None
    created_at: dt.datetime
    # Davet e-postasının akıbeti. `None` = davetle açılmadı.
    # Gönderilemezse arayüz bunu söylemeli; yoksa yönetici hesabı açtığını
    # sanır, kullanıcı e-posta bekler ve kimse durumu fark etmez.
    invite_sent: bool | None = None
    invite_error: str | None = None


class UserIn(BaseModel):
    email: EmailStr
    # Boş bırakılırsa parola ATANMAZ ve kullanıcıya davet e-postası gider —
    # yöneticinin parolayı bilmesi ve düz metin iletmesi gerekmez.
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LEN,
                                 max_length=200)
    role: AppRole
    # Koç rolü için ZORUNLU: koçun görebileceği öğrenciler
    # `coach_assignment.coach_person_id = app_user.person_id` üzerinden
    # bulunuyor. Boş bırakılırsa koç hiçbir öğrenci göremez.
    person_id: uuid.UUID | None = None


class UserPatch(BaseModel):
    email: EmailStr | None = None
    role: AppRole | None = None
    is_active: bool | None = None
    person_id: uuid.UUID | None = None


class UserPasswordIn(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=200)


# --- Parola akışları (v1.7) ------------------------------------------------
class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=200)


class ResetCheckOut(BaseModel):
    """
    Parola belirleme sayfası açılırken jetonun durumu.

    `valid=False` iken `email` ve `purpose` **None** — geçersiz jetonla
    hangi hesabın hedeflendiği sızdırılmaz.
    """
    valid: bool
    email: str | None
    purpose: ResetPurpose | None


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=200)


# --- SMTP ayarları (v1.7) --------------------------------------------------
class SmtpIn(BaseModel):
    host: str = Field(max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    from_addr: EmailStr
    user: str | None = Field(default=None, max_length=200)
    # Boş bırakılırsa kayıtlı parola KORUNUR — arayüz mevcut parolayı hiç
    # görmediği için her kaydetmede yeniden yazmak zorunda kalınmamalı.
    password: str | None = Field(default=None, max_length=200)


class MailTestIn(BaseModel):
    to: EmailStr


# --- Ders programı (v1.9) --------------------------------------------------
class LessonIn(BaseModel):
    zone_id: uuid.UUID
    grade: str = Field(min_length=1, max_length=40)
    weekday: int = Field(ge=1, le=7, description="ISO: 1=Pazartesi … 7=Pazar")
    starts_at: dt.time
    ends_at: dt.time
    name: str = Field(min_length=1, max_length=80)


class LessonPatch(BaseModel):
    zone_id: uuid.UUID | None = None
    grade: str | None = Field(default=None, min_length=1, max_length=40)
    weekday: int | None = Field(default=None, ge=1, le=7)
    starts_at: dt.time | None = None
    ends_at: dt.time | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None


class LessonOut(ORM):
    id: uuid.UUID
    zone_id: uuid.UUID
    zone_name: str | None = None
    grade: str
    weekday: int
    starts_at: dt.time
    ends_at: dt.time
    name: str
    is_active: bool


class LessonTodayOut(LessonOut):
    """
    Bugünkü ders — yoklama ekranının doğrudan kullanacağı hâli.

    Saatler burada **UTC olarak hesaplanmış** döner. Tarayıcı, yerel saati
    kendi diliminde yorumlarsa (yurt dışındaki bir yönetici, yanlış ayarlı
    cihaz) yanlış aralık üretir; çevrimi kurumun dilimiyle sunucu yapar.
    """
    starts_at_utc: dt.datetime
    ends_at_utc: dt.datetime
    is_current: bool


# --- Bileşik: ileri referanslar çözülsün diye en sonda --------------------
class PersonDetailOut(PersonOut):
    """§3.2 — kişi + credentials + guardians + son 10 olay"""
    credentials: list[CredentialOut]
    guardians: list[GuardianLinkOut]
    recent_events: list[EventOut]
