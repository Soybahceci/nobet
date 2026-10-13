-- ============================================================================
-- NÖBET — Veritabanı Şeması
-- Kaynak: docs/nobet-faz1-sistem-sozlesmesi.md §1.2  (KONTRAT, sürüm 1.1)
-- PostgreSQL 16
--
-- Bu dosya YALNIZCA veri dizini boşken çalışır (docker-entrypoint-initdb.d).
-- Sonraki şema değişiklikleri migration ile yapılmalı.
-- ============================================================================

SET timezone = 'Europe/Istanbul';

-- ---------------------------------------------------------------------------
-- Enum tipleri
-- ---------------------------------------------------------------------------
CREATE TYPE person_type       AS ENUM ('student', 'staff', 'coach');
CREATE TYPE person_status     AS ENUM ('active', 'passive');
CREATE TYPE credential_type   AS ENUM ('rfid', 'fingerprint');
CREATE TYPE credential_status AS ENUM ('active', 'lost', 'revoked');
CREATE TYPE zone_kind         AS ENUM ('entrance', 'library', 'classroom');
CREATE TYPE node_direction    AS ENUM ('in', 'out', 'toggle');
CREATE TYPE node_status       AS ENUM ('online', 'offline', 'disabled');
CREATE TYPE session_state     AS ENUM ('open', 'closed', 'auto_closed', 'corrected');
CREATE TYPE app_role          AS ENUM ('super_admin', 'kurum_admin', 'operator', 'coach');

CREATE TYPE event_decision AS ENUM (
    'granted', 'unknown_credential', 'revoked', 'duplicate', 'disabled_node'
);

-- ---------------------------------------------------------------------------
-- updated_at otomatiği
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- tenant — Kurum
-- ---------------------------------------------------------------------------
CREATE TABLE tenant (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text        NOT NULL,
    slug       text        NOT NULL UNIQUE,
    timezone   text        NOT NULL DEFAULT 'Europe/Istanbul',
    created_at timestamptz NOT NULL DEFAULT now(),

    -- MQTT topic'inde kullanılıyor (§2.1), bu yüzden karakter kümesi dar
    CONSTRAINT tenant_slug_format CHECK (slug ~ '^[a-z0-9-]+$')
);
COMMENT ON COLUMN tenant.slug IS 'MQTT topic bileseni: nobet/v1/{slug}/{node_key}/...';

-- ---------------------------------------------------------------------------
-- person — Kişi (öğrenci / personel / koç)
-- ---------------------------------------------------------------------------
CREATE TABLE person (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid          NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    full_name    text          NOT NULL,
    person_type  person_type   NOT NULL,
    birth_date   date,
    external_ref text,
    phone        text,
    email        text,
    status       person_status NOT NULL DEFAULT 'active',
    created_at   timestamptz   NOT NULL DEFAULT now(),
    updated_at   timestamptz   NOT NULL DEFAULT now()
);
-- Veri minimizasyonu (KVKK): TC kimlik no SAKLANMAZ. Eşleştirme external_ref ile.
COMMENT ON COLUMN person.external_ref IS 'Kurumun kendi ogrenci no''su. TC kimlik no BURAYA YAZILMAZ.';
COMMENT ON COLUMN person.birth_date   IS '18 yas alti veli bildirimi bu alana bakar (§1.2).';

CREATE INDEX person_tenant_type_idx ON person (tenant_id, person_type, status);
CREATE INDEX person_name_idx        ON person USING gin (to_tsvector('simple', full_name));

CREATE TRIGGER person_updated_at BEFORE UPDATE ON person
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Türetilen alan — kolon değil, sorgu kolaylığı için görünüm yardımcısı
CREATE OR REPLACE FUNCTION is_minor(p_birth_date date) RETURNS boolean AS $$
    SELECT p_birth_date IS NOT NULL
           AND age(p_birth_date) < interval '18 years';
$$ LANGUAGE sql IMMUTABLE;

-- ---------------------------------------------------------------------------
-- guardian — Veli
-- ---------------------------------------------------------------------------
CREATE TABLE guardian (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    full_name text NOT NULL,
    phone     text NOT NULL,
    email     text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX guardian_tenant_idx ON guardian (tenant_id);

-- ---------------------------------------------------------------------------
-- person_guardian — Öğrenci ↔ Veli (çoka-çok)
-- ---------------------------------------------------------------------------
CREATE TABLE person_guardian (
    person_id      uuid    NOT NULL REFERENCES person(id)   ON DELETE CASCADE,
    guardian_id    uuid    NOT NULL REFERENCES guardian(id) ON DELETE CASCADE,
    relation       text    NOT NULL,
    is_primary     boolean NOT NULL DEFAULT false,
    notify_enabled boolean NOT NULL DEFAULT true,
    PRIMARY KEY (person_id, guardian_id)
);
COMMENT ON COLUMN person_guardian.relation IS 'anne | baba | vasi';
CREATE INDEX person_guardian_guardian_idx ON person_guardian (guardian_id);

-- ---------------------------------------------------------------------------
-- credential — Kimlik Aracı
-- ---------------------------------------------------------------------------
CREATE TABLE credential (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid              NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    person_id  uuid              NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    type       credential_type   NOT NULL,
    identifier text              NOT NULL,
    label      text,
    status     credential_status NOT NULL DEFAULT 'active',
    issued_at  timestamptz       NOT NULL DEFAULT now(),
    revoked_at timestamptz,

    -- Bir kart iki kişide olamaz (§1.2)
    CONSTRAINT credential_unique UNIQUE (tenant_id, type, identifier)
);
COMMENT ON COLUMN credential.identifier IS
    'RFID: UID hex, BUYUK HARF, ayracsiz (or. A1B2C3D4). Biyometrik: template ref.';
CREATE INDEX credential_person_idx ON credential (person_id, status);
CREATE INDEX credential_lookup_idx ON credential (tenant_id, type, identifier)
    WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- zone — Mekân
-- ---------------------------------------------------------------------------
CREATE TABLE zone (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid      NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name           text      NOT NULL,
    kind           zone_kind NOT NULL,
    parent_zone_id uuid      REFERENCES zone(id) ON DELETE SET NULL,
    auto_close_at  time,
    created_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN zone.auto_close_at IS 'Acik oturumlarin gece kapatilma saati (Faz 7).';
CREATE INDEX zone_tenant_idx ON zone (tenant_id, kind);

-- ---------------------------------------------------------------------------
-- node — Okuyucu Cihaz
-- ---------------------------------------------------------------------------
CREATE TABLE node (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid            NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    zone_id          uuid            NOT NULL REFERENCES zone(id)   ON DELETE RESTRICT,
    node_key         text            NOT NULL UNIQUE,
    name             text            NOT NULL,
    direction        node_direction  NOT NULL DEFAULT 'toggle',
    reader_type      credential_type NOT NULL DEFAULT 'rfid',
    firmware_version text,
    last_seen_at     timestamptz,
    status           node_status     NOT NULL DEFAULT 'offline',
    created_at       timestamptz     NOT NULL DEFAULT now(),

    CONSTRAINT node_key_format CHECK (node_key ~ '^[a-z0-9-]+$')
);
COMMENT ON COLUMN node.node_key IS
    'MQTT topic bileseni ve firmware config.h/NODE_KEY ile BIREBIR ayni olmali.';
COMMENT ON COLUMN node.direction IS
    'Cift okuyuculu kapida in/out, tek okuyucuda toggle. Prototip: toggle.';
CREATE INDEX node_tenant_idx ON node (tenant_id, status);

-- ---------------------------------------------------------------------------
-- event — Ham Okuma Olayı  ⚠ DEĞİŞMEZ
-- ---------------------------------------------------------------------------
-- Bu tabloya yazılan hiçbir satır GÜNCELLENMEZ / SİLİNMEZ (§0 tasarım ilkesi).
-- Denetim izi, KVKK ve veri bütünlüğü buna dayanıyor.
CREATE TABLE event (
    id              bigserial PRIMARY KEY,
    tenant_id       uuid            NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    node_id         uuid            NOT NULL REFERENCES node(id)   ON DELETE RESTRICT,
    seq             bigint          NOT NULL,
    cred_type       credential_type NOT NULL,
    cred_identifier text            NOT NULL,
    -- ⚠️ ON DELETE SET NULL KULLANILAMAZ: silme anında PostgreSQL event
    -- satırını GÜNCELLEMEYE çalışır, değişmezlik trigger'ı bunu reddeder ve
    -- silme anlaşılmaz bir hatayla düşer. RESTRICT ile niyet açık olur:
    -- kullanılmış bir kart/kişi silinmez, `status` ile iptal edilir (§1.2).
    credential_id   uuid            REFERENCES credential(id) ON DELETE RESTRICT,
    person_id       uuid            REFERENCES person(id)     ON DELETE RESTRICT,
    decision        event_decision  NOT NULL,
    device_uptime_ms bigint         NOT NULL,
    device_tx_uptime_ms bigint,
    device_ts       timestamptz,
    server_ts       timestamptz     NOT NULL DEFAULT now(),
    effective_ts    timestamptz     NOT NULL,
    from_buffer     boolean         NOT NULL DEFAULT false,
    raw             jsonb           NOT NULL,

    -- Idempotency: offline buffer replay cift kayit yapmaz (§1.2)
    CONSTRAINT event_node_seq_unique UNIQUE (node_id, seq)
);
COMMENT ON TABLE  event IS 'DEGISMEZ. UPDATE/DELETE yapilmaz.';
COMMENT ON COLUMN event.cred_identifier IS
    'Ham okunan deger. Kayitli olmasa bile yazilir — enrollment akisinin yakiti (§3.4).';
COMMENT ON COLUMN event.device_uptime_ms IS 'Payload "up" — okuma anindaki uptime.';
COMMENT ON COLUMN event.device_tx_uptime_ms IS
    'Payload "up_tx" — yayin anindaki uptime (kontrat v1.1). effective_ts hesabi icin.';
COMMENT ON COLUMN event.from_buffer IS 'Payload "buf": true ise offline buffer''dan geldi.';

CREATE INDEX event_tenant_time_idx ON event (tenant_id, effective_ts DESC);
CREATE INDEX event_person_time_idx ON event (person_id, effective_ts DESC);
CREATE INDEX event_node_time_idx   ON event (node_id, effective_ts DESC);
-- Enrollment ekrani: son N saniyedeki kayitsiz okumalar (§3.4)
CREATE INDEX event_unknown_idx     ON event (tenant_id, effective_ts DESC)
    WHERE decision = 'unknown_credential';

-- Değişmezliği veritabanı seviyesinde koru. Uygulama hatası ham veriyi bozamasın.
CREATE OR REPLACE FUNCTION event_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'event tablosu degismezdir: % engellendi (id=%)',
        TG_OP, COALESCE(OLD.id, NEW.id);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER event_no_update BEFORE UPDATE ON event
    FOR EACH ROW EXECUTE FUNCTION event_immutable();
CREATE TRIGGER event_no_delete BEFORE DELETE ON event
    FOR EACH ROW EXECUTE FUNCTION event_immutable();

-- ---------------------------------------------------------------------------
-- attendance_session — Türetilmiş Oturum
-- ---------------------------------------------------------------------------
CREATE TABLE attendance_session (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid          NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    person_id        uuid          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    zone_id          uuid          NOT NULL REFERENCES zone(id)   ON DELETE RESTRICT,
    entry_event_id   bigint        NOT NULL REFERENCES event(id)  ON DELETE RESTRICT,
    exit_event_id    bigint        REFERENCES event(id)           ON DELETE RESTRICT,
    entered_at       timestamptz   NOT NULL,
    exited_at        timestamptz,
    duration_seconds integer,
    state            session_state NOT NULL DEFAULT 'open',
    corrected_by     uuid,
    note             text,
    created_at       timestamptz   NOT NULL DEFAULT now(),
    updated_at       timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT session_time_order CHECK (exited_at IS NULL OR exited_at >= entered_at)
);

-- Bir kişi aynı mekânda aynı anda tek açık oturuma sahip olabilir (§1.2)
CREATE UNIQUE INDEX attendance_session_open_unique
    ON attendance_session (person_id, zone_id) WHERE state = 'open';

CREATE INDEX attendance_session_person_idx ON attendance_session (person_id, entered_at DESC);
CREATE INDEX attendance_session_zone_idx   ON attendance_session (zone_id, state);
CREATE INDEX attendance_session_open_idx   ON attendance_session (tenant_id) WHERE state = 'open';

CREATE TRIGGER attendance_session_updated_at BEFORE UPDATE ON attendance_session
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- app_user — Sisteme Giriş Yapan Kullanıcı
-- ---------------------------------------------------------------------------
CREATE TABLE app_user (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid     NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    person_id     uuid     REFERENCES person(id) ON DELETE SET NULL,
    email         text     NOT NULL UNIQUE,
    password_hash text     NOT NULL,
    role          app_role NOT NULL,
    is_active     boolean  NOT NULL DEFAULT true,
    last_login_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN app_user.password_hash IS 'argon2id (§1.2). Baska algoritma kullanilmaz.';
CREATE INDEX app_user_tenant_idx ON app_user (tenant_id, role, is_active);

-- ---------------------------------------------------------------------------
-- coach_assignment — Koç ↔ Öğrenci
-- ---------------------------------------------------------------------------
-- Koç YALNIZCA kendisine atanmış öğrencileri görür (§1.3). Yetki sorgusu buradan geçer.
CREATE TABLE coach_assignment (
    coach_person_id   uuid NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    student_person_id uuid NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    assigned_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (coach_person_id, student_person_id)
);
CREATE INDEX coach_assignment_student_idx ON coach_assignment (student_person_id);

-- ---------------------------------------------------------------------------
-- Kolaylık görünümleri
-- ---------------------------------------------------------------------------
CREATE VIEW v_inside_now AS
SELECT s.tenant_id, s.zone_id, z.name AS zone_name, z.kind AS zone_kind,
       s.person_id, p.full_name, p.person_type,
       s.entered_at,
       EXTRACT(EPOCH FROM (now() - s.entered_at))::bigint AS elapsed_seconds
FROM attendance_session s
JOIN person p ON p.id = s.person_id
JOIN zone   z ON z.id = s.zone_id
WHERE s.state = 'open';
COMMENT ON VIEW v_inside_now IS 'Su an iceride olanlar — GET /sessions/open (§3.6).';

CREATE VIEW v_enroll_pending AS
SELECT e.id AS event_id, e.tenant_id, e.cred_type, e.cred_identifier,
       n.name AS node_name, e.effective_ts AS seen_at
FROM event e
JOIN node n ON n.id = e.node_id
WHERE e.decision = 'unknown_credential'
ORDER BY e.effective_ts DESC;
COMMENT ON VIEW v_enroll_pending IS 'Enrollment kuyrugu — GET /enroll/pending (§3.4).';
