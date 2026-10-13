-- ============================================================================
-- NÖBET — GELİŞTİRME TOHUMU
-- ============================================================================
-- ⚠️ BU DOSYA ÜRETİMDE ÇALIŞTIRILMAZ.
--    Kuruma teslimde bu dosya init/ dizininden ÇIKARILIR. Gerçek kurum,
--    kişi ve kart kayıtları arayüzden girilir (proje ilkesi: "sıfır CLI" kuralı).
--
-- Amaç: Faz 4/5 geliştirmesi sırasında elle veri girmeden test edebilmek.
-- Kart numaraları örnektir; gerçek kartlara ait değildir.
-- ============================================================================

DO $$
DECLARE
    v_tenant  uuid;
    v_zone    uuid;
    v_student uuid;
    v_staff   uuid;
    v_guard   uuid;
BEGIN
    -- Kurum -----------------------------------------------------------------
    -- slug, firmware config.h/TENANT_SLUG ile BIREBIR ayni olmali.
    INSERT INTO tenant (name, slug, timezone)
    VALUES ('Örnek Eğitim Kurumu', 'ornek-kurum', 'Europe/Istanbul')
    RETURNING id INTO v_tenant;

    -- Mekân -----------------------------------------------------------------
    INSERT INTO zone (tenant_id, name, kind, auto_close_at)
    VALUES (v_tenant, 'Ana Giriş', 'entrance', '23:00')
    RETURNING id INTO v_zone;

    -- Düğüm -----------------------------------------------------------------
    -- node_key, firmware config.h/NODE_KEY ile BIREBIR ayni olmali.
    INSERT INTO node (tenant_id, zone_id, node_key, name, direction, reader_type)
    VALUES (v_tenant, v_zone, 'giris-01', 'Ana Giriş Okuyucu', 'toggle', 'rfid');

    -- Kişiler ---------------------------------------------------------------
    INSERT INTO person (tenant_id, full_name, person_type, birth_date, external_ref)
    VALUES (v_tenant, 'Test Öğrenci', 'student', '2010-03-15', 'OGR-0001')
    RETURNING id INTO v_student;

    INSERT INTO person (tenant_id, full_name, person_type)
    VALUES (v_tenant, 'Test Personel', 'staff')
    RETURNING id INTO v_staff;

    -- Veli (öğrenci 18 yaş altı — bildirim mantığı Faz 8) --------------------
    INSERT INTO guardian (tenant_id, full_name, phone)
    VALUES (v_tenant, 'Test Veli', '+90 500 000 00 00')
    RETURNING id INTO v_guard;

    INSERT INTO person_guardian (person_id, guardian_id, relation, is_primary, notify_enabled)
    VALUES (v_student, v_guard, 'anne', true, true);

    -- Kartlar — örnek UID'ler (gerçek kartlara ait değildir) ----------------
    INSERT INTO credential (tenant_id, person_id, type, identifier, label)
    VALUES (v_tenant, v_student, 'rfid', 'A1B2C3D4', 'Test kart 1');

    INSERT INTO credential (tenant_id, person_id, type, identifier, label)
    VALUES (v_tenant, v_staff,   'rfid', 'B5C6D7E8', 'Test kart 2');

    -- NOT: C9D0E1F2 BILEREK KAYDEDILMEDI.
    -- unknown_credential + enrollment akisi (§3.4) bu kartla test edilecek.

    RAISE NOTICE 'Gelistirme tohumu yuklendi: tenant=% zone=% ', v_tenant, v_zone;
END $$;
