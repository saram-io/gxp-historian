-- =============================================================================
-- 01_control_plane_part11.sql
-- Pillar 3: PostgreSQL 16 Control Plane (ISA-95 Hierarchy, Tag Catalog,
-- ISA-88 Event Frames, and 21 CFR Part 11 Cryptographic WORM Audit Trail)
-- =============================================================================

-- 1. Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2. Core Schema Tables
CREATE TABLE IF NOT EXISTS asset_templates (
    template_id SERIAL PRIMARY KEY,
    template_name TEXT UNIQUE NOT NULL,
    attribute_specs JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id SERIAL PRIMARY KEY,
    asset_name TEXT NOT NULL,
    asset_path ltree UNIQUE NOT NULL,
    template_id INT REFERENCES asset_templates(template_id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_assets_asset_path_gist ON assets USING GIST (asset_path);

CREATE TABLE IF NOT EXISTS tags (
    tag_id SERIAL PRIMARY KEY,
    tag_name TEXT UNIQUE NOT NULL,
    asset_id INT REFERENCES assets(asset_id),
    attribute_name TEXT NOT NULL,
    eng_units TEXT NOT NULL DEFAULT '',
    is_step_tag BOOLEAN NOT NULL DEFAULT FALSE,
    exc_dev DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    low_limit DOUBLE PRECISION,
    high_limit DOUBLE PRECISION,
    source_protocol TEXT NOT NULL,
    source_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS event_frames (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_event_id UUID REFERENCES event_frames(event_id),
    event_name TEXT NOT NULL,
    event_template TEXT NOT NULL,
    asset_id INT REFERENCES assets(asset_id),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    severity TEXT NOT NULL DEFAULT 'INFO',
    captured_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    signed_by TEXT,
    signature_meaning TEXT,
    signed_at TIMESTAMPTZ,
    signature_hash TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS digital_state_sets (
    state_set_id SERIAL PRIMARY KEY,
    state_set_name TEXT UNIQUE NOT NULL,
    states_map JSONB NOT NULL DEFAULT '{}'::jsonb,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS event_frame_templates (
    ef_template_id SERIAL PRIMARY KEY,
    template_name TEXT UNIQUE NOT NULL,
    target_attribute TEXT NOT NULL,
    trigger_operator TEXT NOT NULL DEFAULT '>',
    trigger_threshold DOUBLE PRECISION NOT NULL,
    true_for_seconds INT NOT NULL DEFAULT 0,
    close_hysteresis DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    severity TEXT NOT NULL DEFAULT 'WARNING'
);

CREATE TABLE IF NOT EXISTS event_frame_signatures (
    sig_id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES event_frames(event_id),
    stage_order INT NOT NULL DEFAULT 1,
    user_id TEXT NOT NULL,
    signer_full_name TEXT NOT NULL,
    signer_role TEXT NOT NULL,
    signature_meaning TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    signed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    signature_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_logger_entries (
    entry_id SERIAL PRIMARY KEY,
    tag_id INT NOT NULL REFERENCES tags(tag_id),
    sample_ts TIMESTAMPTZ NOT NULL,
    val DOUBLE PRECISION NOT NULL,
    str_val TEXT NOT NULL DEFAULT '',
    sample_barcode TEXT NOT NULL DEFAULT '',
    operator_id TEXT NOT NULL,
    verifier_id TEXT,
    within_limits BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS notification_rules (
    rule_id SERIAL PRIMARY KEY,
    rule_name TEXT UNIQUE NOT NULL,
    event_template_filter TEXT NOT NULL DEFAULT '*',
    min_severity TEXT NOT NULL DEFAULT 'WARNING',
    channel_type TEXT NOT NULL DEFAULT 'WEBHOOK',
    target_endpoint TEXT NOT NULL,
    escalation_minutes INT NOT NULL DEFAULT 15,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    delivery_id SERIAL PRIMARY KEY,
    rule_id INT NOT NULL REFERENCES notification_rules(rule_id),
    event_id UUID NOT NULL REFERENCES event_frames(event_id),
    channel_type TEXT NOT NULL,
    target_endpoint TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'DELIVERED',
    escalation_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS part11_audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    actor_id TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    target_table TEXT NOT NULL,
    record_pk TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_payload JSONB,
    new_payload JSONB,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL
);

-- 3. ClickHouse Dictionary Bridge View
CREATE OR REPLACE VIEW v_clickhouse_tag_dict AS
SELECT
    t.tag_id,
    t.tag_name,
    a.asset_name,
    a.asset_path::TEXT AS asset_path,
    t.attribute_name,
    t.eng_units,
    t.is_step_tag::INT AS is_step_tag,
    t.low_limit,
    t.high_limit
FROM tags t
JOIN assets a ON t.asset_id = a.asset_id;

-- 4. 21 CFR Part 11 Cryptographic Audit Trigger Function
CREATE OR REPLACE FUNCTION fn_enforce_part11_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_actor TEXT;
    v_reason TEXT;
    v_recorded_at TIMESTAMPTZ := clock_timestamp();
    v_old_payload JSONB := NULL;
    v_new_payload JSONB := NULL;
    v_payload_ref JSONB;
    v_record_pk TEXT;
    v_prev_hash TEXT;
    v_row_hash TEXT;
BEGIN
    v_actor := NULLIF(btrim(current_setting('app.actor_id', true)), '');
    v_reason := NULLIF(btrim(current_setting('app.change_reason', true)), '');

    IF v_actor IS NULL OR v_reason IS NULL THEN
        RAISE EXCEPTION '21 CFR Part 11 Violation: app.actor_id and app.change_reason are mandatory';
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_new_payload := to_jsonb(NEW);
        v_payload_ref := v_new_payload;
    ELSIF TG_OP = 'UPDATE' THEN
        v_old_payload := to_jsonb(OLD);
        v_new_payload := to_jsonb(NEW);
        v_payload_ref := v_new_payload;
    ELSIF TG_OP = 'DELETE' THEN
        v_old_payload := to_jsonb(OLD);
        v_payload_ref := v_old_payload;
    END IF;

    v_record_pk := CASE TG_TABLE_NAME
        WHEN 'asset_templates'        THEN v_payload_ref->>'template_id'
        WHEN 'assets'                 THEN v_payload_ref->>'asset_id'
        WHEN 'tags'                   THEN v_payload_ref->>'tag_id'
        WHEN 'event_frames'           THEN v_payload_ref->>'event_id'
        WHEN 'digital_state_sets'     THEN v_payload_ref->>'state_set_id'
        WHEN 'event_frame_templates'  THEN v_payload_ref->>'ef_template_id'
        WHEN 'event_frame_signatures' THEN v_payload_ref->>'sig_id'
        WHEN 'manual_logger_entries'  THEN v_payload_ref->>'entry_id'
        WHEN 'notification_rules'     THEN v_payload_ref->>'rule_id'
        WHEN 'notification_deliveries' THEN v_payload_ref->>'delivery_id'
        ELSE COALESCE(
            v_payload_ref->>'id',
            v_payload_ref->>'tag_id',
            v_payload_ref->>'asset_id',
            v_payload_ref->>'template_id',
            v_payload_ref->>'event_id',
            'unknown'
        )
    END;

    SELECT row_hash INTO v_prev_hash
    FROM part11_audit_log
    ORDER BY audit_id DESC
    LIMIT 1;

    IF v_prev_hash IS NULL THEN
        v_prev_hash := 'GENESIS_0000000000000000';
    END IF;

    v_row_hash := encode(
        digest(
            v_prev_hash || v_recorded_at::text || v_actor || TG_OP || COALESCE(v_new_payload::text, ''),
            'sha256'
        ),
        'hex'
    );

    INSERT INTO part11_audit_log (
        recorded_at,
        actor_id,
        change_reason,
        target_table,
        record_pk,
        operation,
        old_payload,
        new_payload,
        prev_hash,
        row_hash
    ) VALUES (
        v_recorded_at,
        v_actor,
        v_reason,
        TG_TABLE_NAME,
        v_record_pk,
        TG_OP,
        v_old_payload,
        v_new_payload,
        v_prev_hash,
        v_row_hash
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_part11_audit_asset_templates ON asset_templates;
CREATE TRIGGER trg_part11_audit_asset_templates
AFTER INSERT OR UPDATE OR DELETE ON asset_templates
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_assets ON assets;
CREATE TRIGGER trg_part11_audit_assets
AFTER INSERT OR UPDATE OR DELETE ON assets
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_tags ON tags;
CREATE TRIGGER trg_part11_audit_tags
AFTER INSERT OR UPDATE OR DELETE ON tags
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_event_frames ON event_frames;
CREATE TRIGGER trg_part11_audit_event_frames
AFTER INSERT OR UPDATE OR DELETE ON event_frames
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_digital_state_sets ON digital_state_sets;
CREATE TRIGGER trg_part11_audit_digital_state_sets
AFTER INSERT OR UPDATE OR DELETE ON digital_state_sets
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_event_frame_templates ON event_frame_templates;
CREATE TRIGGER trg_part11_audit_event_frame_templates
AFTER INSERT OR UPDATE OR DELETE ON event_frame_templates
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_event_frame_signatures ON event_frame_signatures;
CREATE TRIGGER trg_part11_audit_event_frame_signatures
AFTER INSERT OR UPDATE OR DELETE ON event_frame_signatures
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_manual_logger_entries ON manual_logger_entries;
CREATE TRIGGER trg_part11_audit_manual_logger_entries
AFTER INSERT OR UPDATE OR DELETE ON manual_logger_entries
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_notification_rules ON notification_rules;
CREATE TRIGGER trg_part11_audit_notification_rules
AFTER INSERT OR UPDATE OR DELETE ON notification_rules
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

DROP TRIGGER IF EXISTS trg_part11_audit_notification_deliveries ON notification_deliveries;
CREATE TRIGGER trg_part11_audit_notification_deliveries
AFTER INSERT OR UPDATE OR DELETE ON notification_deliveries
FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();

-- 5. 21 CFR Part 11 WORM Immutability Trigger Function
CREATE OR REPLACE FUNCTION fn_prevent_audit_tampering()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '21 CFR Part 11 WORM Violation: Audit trail records are immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_worm_part11_audit_log_stmt ON part11_audit_log;
CREATE TRIGGER trg_worm_part11_audit_log_stmt
BEFORE UPDATE OR DELETE OR TRUNCATE ON part11_audit_log
FOR EACH STATEMENT EXECUTE FUNCTION fn_prevent_audit_tampering();

DROP TRIGGER IF EXISTS trg_worm_part11_audit_log_row ON part11_audit_log;
CREATE TRIGGER trg_worm_part11_audit_log_row
BEFORE UPDATE OR DELETE ON part11_audit_log
FOR EACH ROW EXECUTE FUNCTION fn_prevent_audit_tampering();

-- 6. Seed Initial GxP Control Plane Data
BEGIN;

SET LOCAL app.actor_id = 'system_bootstrap';
SET LOCAL app.change_reason = 'Initial GxP Qualification Seed';

-- Seed 2 Test Users (operator_01 and qa_approver_01 with bcrypt hashes via pgcrypto)
INSERT INTO users (user_id, full_name, role, password_hash, is_active) VALUES
    ('operator_01', 'Sarah Jenkins (Lead USP Operator)', 'OPERATOR', crypt('Operator_2026!', gen_salt('bf')), TRUE),
    ('qa_approver_01', 'Dr. Marcus Vance (QA Qualified Person)', 'QA_APPROVER', crypt('QA_Approver_2026!', gen_salt('bf')), TRUE);

-- Seed Asset Templates
INSERT INTO asset_templates (template_id, template_name, attribute_specs) VALUES
    (1, 'Bioreactor_USP_Template', '[
        {"attribute_name": "Vessel_Temperature", "eng_units": "degC", "low_limit": 35.0, "high_limit": 38.0, "is_step_tag": false},
        {"attribute_name": "Media_pH", "eng_units": "pH", "low_limit": 6.8, "high_limit": 7.4, "is_step_tag": false},
        {"attribute_name": "Agitator_State", "eng_units": "state", "is_step_tag": true},
        {"attribute_name": "UV_Absorbance_280nm", "eng_units": "mAU", "is_step_tag": false}
    ]'::jsonb),
    (2, 'Cleanroom_EMS_Template', '[
        {"attribute_name": "Differential_Pressure", "eng_units": "Pa", "low_limit": 12.5, "high_limit": 25.0, "is_step_tag": false}
    ]'::jsonb);

SELECT setval(pg_get_serial_sequence('asset_templates', 'template_id'), (SELECT MAX(template_id) FROM asset_templates));

-- Seed ISA-95 Assets
INSERT INTO assets (asset_id, asset_name, asset_path, template_id, metadata) VALUES
    (1, 'Bioreactor_201', 'BioCorp.Fremont.USP.Bioreactor_201', 1, '{"vessel_volume_L": 2000, "gmp_classification": "Grade_C", "equipment_id": "EQ-BR-201"}'::jsonb),
    (2, 'Cleanroom_ISO7', 'BioCorp.Fremont.Facilities.Cleanroom_ISO7', 2, '{"iso_class": "ISO_7", "gmp_classification": "Grade_C", "room_id": "RM-USP-104"}'::jsonb);

SELECT setval(pg_get_serial_sequence('assets', 'asset_id'), (SELECT MAX(asset_id) FROM assets));

-- Seed 5 Historian Tags
INSERT INTO tags (
    tag_id, tag_name, asset_id, attribute_name, eng_units,
    is_step_tag, exc_dev, low_limit, high_limit, source_protocol, source_config, is_active
) VALUES
    (101, 'BR201_TEMP_PV', 1, 'Vessel_Temperature', 'degC', FALSE, 0.05, 35.0, 38.0, 'OPC_UA', '{"node_id": "ns=2;s=BR201.Temperature.PV", "sampling_ms": 1000}'::jsonb, TRUE),
    (102, 'BR201_PH_PV', 1, 'Media_pH', 'pH', FALSE, 0.02, 6.8, 7.4, 'OPC_UA', '{"node_id": "ns=2;s=BR201.pH.PV", "sampling_ms": 1000}'::jsonb, TRUE),
    (103, 'BR201_AGIT_STATE', 1, 'Agitator_State', 'state', TRUE, 0.0, NULL, NULL, 'S7COMM', '{"rack": 0, "slot": 1, "db": 10, "offset": 0}'::jsonb, TRUE),
    (301, 'CR_ISO7_DP_PV', 2, 'Differential_Pressure', 'Pa', FALSE, 0.10, 12.5, 25.0, 'BACNET_IP', '{"device_id": 3010, "object_type": "analogInput", "instance": 1}'::jsonb, TRUE),
    (401, 'CHROM_UV280_PV', 1, 'UV_Absorbance_280nm', 'mAU', FALSE, 0.05, NULL, NULL, 'OPC_DA', '{"prog_id": "Matrikon.OPC.Simulation.1", "item_id": "DSP.Chrom.UV280.PV"}'::jsonb, TRUE);

SELECT setval(pg_get_serial_sequence('tags', 'tag_id'), (SELECT MAX(tag_id) FROM tags));

-- Seed PI Digital State Sets
INSERT INTO digital_state_sets (state_set_name, states_map, description) VALUES
    ('Agitator_Mode_States', '{"0": "OFF", "1": "LOW", "2": "HIGH_RUN"}'::jsonb, 'Bioreactor agitator discrete operating states'),
    ('ISA88_Batch_Phase', '{"0": "IDLE", "1": "CIP_SIP", "2": "MEDIA_CHARGE", "3": "INOCULATION", "4": "GROWTH_PHASE", "5": "HARVEST"}'::jsonb, 'ISA-88 unit procedure phase states'),
    ('SYSTEM_Digital_States', '{"-1": "No_Data", "-2": "I/O_Timeout", "-3": "Out_Of_Service", "-4": "Over_Range", "-5": "Substituted_Manual"}'::jsonb, 'System-level OPC / PI diagnostic digital states')
ON CONFLICT (state_set_name) DO NOTHING;

-- Seed PI Event Frame Templates with TrueFor debounce & hysteresis
INSERT INTO event_frame_templates (
    template_name, target_attribute, trigger_operator, trigger_threshold, true_for_seconds, close_hysteresis, severity
) VALUES
    ('Temp_Excursion_TrueFor_30s', 'Vessel_Temperature', '>', 38.0, 30, 0.2, 'CRITICAL'),
    ('Cleanroom_DP_Low_Excursion', 'Differential_Pressure', '<', 12.5, 15, 0.5, 'WARNING')
ON CONFLICT (template_name) DO NOTHING;

-- Seed PI Notification Rule
INSERT INTO notification_rules (
    rule_name, event_template_filter, min_severity, channel_type, target_endpoint, escalation_minutes, is_active
) VALUES
    ('QA_Critical_Excursion_Webhook', '*', 'CRITICAL', 'WEBHOOK', 'https://qa-alerts.biocorp.internal/api/v1/gxp-incidents', 15, TRUE)
ON CONFLICT (rule_name) DO NOTHING;

COMMIT;

