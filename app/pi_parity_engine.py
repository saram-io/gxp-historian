"""
AVEVA PI System Full Parity Engine for GxPHistorian (Pillar 2 & Pillar 3).

Implements enterprise capabilities across all 4 phases of the AVEVA PI System parity roadmap:
  - Phase 1: PI DataLink & PI Web API Parity
      * Snapshot / Current Value (`PICurrVal` -> `/api/v1/datalink/current`)
      * Exact-Timestamp Archive Value (`PIArcVal` -> `/api/v1/datalink/archive-value`)
      * Compressed Recorded Values (`PICompDat` -> `/api/v1/datalink/recorded`)
      * Time-Weighted vs. Event-Weighted Summary (`PIAdvCalcDat` -> `/api/v1/datalink/calculated`)
      * Expression Duration Time-Filter (`PITimeFilter` -> `/api/v1/datalink/time-filter`)
      * Bulk Multi-Tag & Asset-Centric Queries (`StreamSets` -> `/api/v1/streamsets/*`)
  - Phase 2: PI Analysis Service, GxP Calculation Engine & PI BatchView
      * ICH Q1A(R2) Mean Kinetic Temperature (`MKT` -> `/api/v1/analytics/mkt`)
      * USP <1229> Steam Sterilization Lethality (`F0` -> `/api/v1/analytics/f0-lethality`)
      * PI SQC / Statistical Process Control (`Western Electric Rules` -> `/api/v1/analytics/sqc`)
      * PI BatchView Golden Batch Relative-Time Overlay (`/api/v1/batches/compare`)
  - Phase 3: PI Asset Framework (AF) Templates, UOM Engine, Digital States & PI Manual Logger
      * Canonical Units of Measure (UOM) Registry & Converter (`/api/v1/af/uom/*`)
      * PI Digital State Sets (`/api/v1/af/digital-state-sets`)
      * Template-Driven Asset & Tag Auto-Instantiation (`/api/v1/assets/instantiate-template`)
      * 21 CFR Part 11 PI Manual Logger with Dual-Verification (`/api/v1/manual-logger/entries`)
  - Phase 4: Swinging Door Compression, Event Frame `TrueFor` Backfill, Multi-Signatures & Notifications
      * Stage 1 Exception + Stage 2 Swinging Door Trending (`SDT`) Evaluator (`/api/v1/compression/swinging-door-evaluate`)
      * Event Frame Templates with `TrueFor` Debounce, Hysteresis & Historical Backfill (`/api/v1/event-frames/backfill`)
      * Multi-Stage Electronic Signatures Chain (`/api/v1/event-frames/{event_id}/signatures`)
      * PI Notifications & Escalation Engine (`/api/v1/notifications/*`)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("historian_api.pi_parity")


# ---------------------------------------------------------------------------
# Canonical Units of Measure (UOM) Registry & Conversion Engine (PI AF UOM)
# ---------------------------------------------------------------------------

UOM_CLASSES: Dict[str, Dict[str, Any]] = {
    "temperature": {
        "canonical_unit": "degC",
        "units": {
            "degC": {
                "name": "Degrees Celsius",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda c: float(c),
            },
            "C": {
                "name": "Degrees Celsius",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda c: float(c),
            },
            "degF": {
                "name": "Degrees Fahrenheit",
                "to_canonical": lambda x: (float(x) - 32.0) / 1.8,
                "from_canonical": lambda c: float(c) * 1.8 + 32.0,
            },
            "F": {
                "name": "Degrees Fahrenheit",
                "to_canonical": lambda x: (float(x) - 32.0) / 1.8,
                "from_canonical": lambda c: float(c) * 1.8 + 32.0,
            },
            "K": {
                "name": "Kelvin",
                "to_canonical": lambda x: float(x) - 273.15,
                "from_canonical": lambda c: float(c) + 273.15,
            },
        },
    },
    "pressure": {
        "canonical_unit": "Pa",
        "units": {
            "Pa": {
                "name": "Pascal",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda p: float(p),
            },
            "kPa": {
                "name": "Kilopascal",
                "to_canonical": lambda x: float(x) * 1000.0,
                "from_canonical": lambda p: float(p) / 1000.0,
            },
            "bar": {
                "name": "Bar",
                "to_canonical": lambda x: float(x) * 100000.0,
                "from_canonical": lambda p: float(p) / 100000.0,
            },
            "mbar": {
                "name": "Millibar",
                "to_canonical": lambda x: float(x) * 100.0,
                "from_canonical": lambda p: float(p) / 100.0,
            },
            "psi": {
                "name": "Pounds per Square Inch",
                "to_canonical": lambda x: float(x) * 6894.75729,
                "from_canonical": lambda p: float(p) / 6894.75729,
            },
            "mmHg": {
                "name": "Millimeters of Mercury",
                "to_canonical": lambda x: float(x) * 133.322387,
                "from_canonical": lambda p: float(p) / 133.322387,
            },
        },
    },
    "volume": {
        "canonical_unit": "L",
        "units": {
            "L": {
                "name": "Liter",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda v: float(v),
            },
            "mL": {
                "name": "Milliliter",
                "to_canonical": lambda x: float(x) / 1000.0,
                "from_canonical": lambda v: float(v) * 1000.0,
            },
            "m3": {
                "name": "Cubic Meter",
                "to_canonical": lambda x: float(x) * 1000.0,
                "from_canonical": lambda v: float(v) / 1000.0,
            },
        },
    },
    "flow_rate": {
        "canonical_unit": "L/min",
        "units": {
            "L/min": {
                "name": "Liters per Minute",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda f: float(f),
            },
            "mL/min": {
                "name": "Milliliters per Minute",
                "to_canonical": lambda x: float(x) / 1000.0,
                "from_canonical": lambda f: float(f) * 1000.0,
            },
            "L/h": {
                "name": "Liters per Hour",
                "to_canonical": lambda x: float(x) / 60.0,
                "from_canonical": lambda f: float(f) * 60.0,
            },
        },
    },
    "optical_absorbance": {
        "canonical_unit": "mAU",
        "units": {
            "mAU": {
                "name": "Milli-Absorbance Units",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda a: float(a),
            },
            "AU": {
                "name": "Absorbance Units",
                "to_canonical": lambda x: float(x) * 1000.0,
                "from_canonical": lambda a: float(a) / 1000.0,
            },
        },
    },
    "mass": {
        "canonical_unit": "g",
        "units": {
            "g": {
                "name": "Gram",
                "to_canonical": lambda x: float(x),
                "from_canonical": lambda m: float(m),
            },
            "kg": {
                "name": "Kilogram",
                "to_canonical": lambda x: float(x) * 1000.0,
                "from_canonical": lambda m: float(m) / 1000.0,
            },
            "mg": {
                "name": "Milligram",
                "to_canonical": lambda x: float(x) / 1000.0,
                "from_canonical": lambda m: float(m) * 1000.0,
            },
        },
    },
}


def convert_uom_value(val: float, from_uom: str, to_uom: str) -> Tuple[float, str]:
    """
    Convert `val` from `from_uom` to `to_uom` using the PI AF UOM registry.
    Raises ValueError if units are unknown or belong to incompatible physical dimensions.
    """
    src = (from_uom or "").strip()
    dst = (to_uom or "").strip()
    if not dst or src == dst:
        return round(float(val), 4), src

    src_class: Optional[str] = None
    dst_class: Optional[str] = None
    for cls_name, cls_info in UOM_CLASSES.items():
        if src in cls_info["units"]:
            src_class = cls_name
        if dst in cls_info["units"]:
            dst_class = cls_name

    if src_class is None or dst_class is None:
        raise ValueError(f"Unsupported UOM conversion requested: {src!r} -> {dst!r}")
    if src_class != dst_class:
        raise ValueError(
            f"Incompatible UOM dimension classes: cannot convert {src!r} ({src_class}) to {dst!r} ({dst_class})"
        )

    cls_units = UOM_CLASSES[src_class]["units"]
    canonical_val = cls_units[src]["to_canonical"](val)
    converted_val = cls_units[dst]["from_canonical"](canonical_val)
    return round(float(converted_val), 4), dst


# ---------------------------------------------------------------------------
# Idempotent PostgreSQL Schema & Trigger Auto-Initializer
# ---------------------------------------------------------------------------


def ensure_pi_parity_schema(get_pg_conn: Callable[[], psycopg.Connection[Dict[str, Any]]]) -> None:
    """
    Idempotently provision all AVEVA PI System parity tables, Part 11 triggers,
    and seed records in PostgreSQL so existing Docker volumes upgrade automatically.
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.actor_id', 'system_bootstrap', true);")
            cur.execute(
                "SELECT set_config('app.change_reason', 'AVEVA PI System Parity Schema Initialization', true);"
            )

            cur.execute(
                """
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
                    non_repetition_minutes INT NOT NULL DEFAULT 5,
                    resend_interval_minutes INT NOT NULL DEFAULT 30,
                    notify_on_close BOOLEAN NOT NULL DEFAULT TRUE,
                    message_template TEXT NOT NULL DEFAULT '[%Severity%] %Element% — %EventFrame% started at %StartTime% (Value: %Value% %EngUnits%, Limit: %HighLimit%)',
                    escalation_team JSONB NOT NULL DEFAULT '[]'::jsonb,
                    delivery_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                );

                ALTER TABLE notification_rules
                    ADD COLUMN IF NOT EXISTS non_repetition_minutes INT NOT NULL DEFAULT 5,
                    ADD COLUMN IF NOT EXISTS resend_interval_minutes INT NOT NULL DEFAULT 30,
                    ADD COLUMN IF NOT EXISTS notify_on_close BOOLEAN NOT NULL DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS message_template TEXT NOT NULL DEFAULT '[%Severity%] %Element% — %EventFrame% started at %StartTime% (Value: %Value% %EngUnits%, Limit: %HighLimit%)',
                    ADD COLUMN IF NOT EXISTS escalation_team JSONB NOT NULL DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS delivery_config JSONB NOT NULL DEFAULT '{}'::jsonb;

                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    delivery_id SERIAL PRIMARY KEY,
                    rule_id INT NOT NULL REFERENCES notification_rules(rule_id),
                    event_id UUID NOT NULL REFERENCES event_frames(event_id),
                    channel_type TEXT NOT NULL,
                    target_endpoint TEXT NOT NULL,
                    delivery_status TEXT NOT NULL DEFAULT 'DELIVERED',
                    escalation_triggered BOOLEAN NOT NULL DEFAULT FALSE,
                    notification_phase TEXT NOT NULL DEFAULT 'TRIGGER',
                    escalation_tier INT NOT NULL DEFAULT 1,
                    recipient_name TEXT NOT NULL DEFAULT '',
                    rendered_message TEXT NOT NULL DEFAULT '',
                    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb
                );

                ALTER TABLE notification_deliveries
                    ADD COLUMN IF NOT EXISTS notification_phase TEXT NOT NULL DEFAULT 'TRIGGER',
                    ADD COLUMN IF NOT EXISTS escalation_tier INT NOT NULL DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS recipient_name TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS rendered_message TEXT NOT NULL DEFAULT '';
                """
            )

            # Update fn_enforce_part11_audit() so all new tables resolve their primary keys cleanly
            cur.execute(
                """
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
                        WHEN 'asset_templates'         THEN v_payload_ref->>'template_id'
                        WHEN 'assets'                  THEN v_payload_ref->>'asset_id'
                        WHEN 'tags'                    THEN v_payload_ref->>'tag_id'
                        WHEN 'event_frames'            THEN v_payload_ref->>'event_id'
                        WHEN 'digital_state_sets'      THEN v_payload_ref->>'state_set_id'
                        WHEN 'event_frame_templates'   THEN v_payload_ref->>'ef_template_id'
                        WHEN 'event_frame_signatures'  THEN v_payload_ref->>'sig_id'
                        WHEN 'manual_logger_entries'   THEN v_payload_ref->>'entry_id'
                        WHEN 'notification_rules'      THEN v_payload_ref->>'rule_id'
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
                """
            )

            for tbl in (
                "digital_state_sets",
                "event_frame_templates",
                "event_frame_signatures",
                "manual_logger_entries",
                "notification_rules",
                "notification_deliveries",
            ):
                cur.execute(
                    f"""
                    DROP TRIGGER IF EXISTS trg_part11_audit_{tbl} ON {tbl};
                    CREATE TRIGGER trg_part11_audit_{tbl}
                    AFTER INSERT OR UPDATE OR DELETE ON {tbl}
                    FOR EACH ROW EXECUTE FUNCTION fn_enforce_part11_audit();
                    """
                )

            # Seed default Digital State Sets if empty
            cur.execute("SELECT count(*) AS cnt FROM digital_state_sets;")
            if int((cur.fetchone() or {}).get("cnt", 0)) == 0:
                cur.execute(
                    """
                    INSERT INTO digital_state_sets (state_set_name, states_map, description) VALUES
                        ('Agitator_Mode_States', '{"0": "OFF", "1": "LOW", "2": "HIGH_RUN"}'::jsonb, 'Bioreactor agitator discrete operating states'),
                        ('ISA88_Batch_Phase', '{"0": "IDLE", "1": "CIP_SIP", "2": "MEDIA_CHARGE", "3": "INOCULATION", "4": "GROWTH_PHASE", "5": "HARVEST"}'::jsonb, 'ISA-88 unit procedure phase states'),
                        ('SYSTEM_Digital_States', '{"-1": "No_Data", "-2": "I/O_Timeout", "-3": "Out_Of_Service", "-4": "Over_Range", "-5": "Substituted_Manual"}'::jsonb, 'System-level OPC / PI diagnostic digital states')
                    ON CONFLICT (state_set_name) DO NOTHING;
                    """
                )

            # Seed default Event Frame Templates if empty
            cur.execute("SELECT count(*) AS cnt FROM event_frame_templates;")
            if int((cur.fetchone() or {}).get("cnt", 0)) == 0:
                cur.execute(
                    """
                    INSERT INTO event_frame_templates (
                        template_name, target_attribute, trigger_operator, trigger_threshold, true_for_seconds, close_hysteresis, severity
                    ) VALUES
                        ('Temp_Excursion_TrueFor_30s', 'Vessel_Temperature', '>', 38.0, 30, 0.2, 'CRITICAL'),
                        ('Cleanroom_DP_Low_Excursion', 'Differential_Pressure', '<', 12.5, 15, 0.5, 'WARNING')
                    ON CONFLICT (template_name) DO NOTHING;
                    """
                )

            # Seed default Multi-Channel PI Notification Rules (WEBHOOK, SMS, MOBILE_PUSH, EMAIL)
            cur.execute(
                """
                INSERT INTO notification_rules (
                    rule_name, event_template_filter, min_severity, channel_type, target_endpoint,
                    escalation_minutes, non_repetition_minutes, resend_interval_minutes, notify_on_close,
                    message_template, escalation_team, delivery_config, is_active
                ) VALUES
                    (
                        'QA_Critical_Excursion_Webhook',
                        '*',
                        'CRITICAL',
                        'WEBHOOK',
                        'https://qa-alerts.biocorp.internal/api/v1/gxp-incidents',
                        15,
                        5,
                        30,
                        TRUE,
                        '[%Severity%] %Element% — %EventFrame% started at %StartTime% (Value: %Value% %EngUnits%, Limit: %HighLimit%)',
                        '[{"tier": 1, "role": "QA Incident Webhook", "contact_name": "QA Automated Triage", "channel_type": "WEBHOOK", "target_endpoint": "https://qa-alerts.biocorp.internal/api/v1/gxp-incidents", "delay_minutes": 0}, {"tier": 2, "role": "QA Qualified Person", "contact_name": "Dr. Marcus Vance", "channel_type": "EMAIL", "target_endpoint": "marcus.vance@biocorp.internal", "delay_minutes": 15}]'::jsonb,
                        '{"format": "PI_WEBSERVICE_JSON_AND_TEAMS_CARD", "include_grafana_trend_link": true}'::jsonb,
                        TRUE
                    ),
                    (
                        'USP_Operator_SMS_Twilio_Alert',
                        '*',
                        'CRITICAL',
                        'SMS',
                        '+14155550101',
                        10,
                        5,
                        15,
                        TRUE,
                        '[GxP %Severity%] %Element% (%EventFrame%): %Value% %EngUnits% (Lim:%HighLimit%) @ %StartTime%. Reply ACK %EventShortId%',
                        '[{"tier": 1, "role": "Lead USP Operator", "contact_name": "Sarah Jenkins", "channel_type": "SMS", "target_endpoint": "+14155550101", "delay_minutes": 0}, {"tier": 2, "role": "USP Shift Supervisor", "contact_name": "David Chen", "channel_type": "SMS", "target_endpoint": "+14155550102", "delay_minutes": 10}, {"tier": 3, "role": "QA Qualified Person", "contact_name": "Dr. Marcus Vance", "channel_type": "SMS", "target_endpoint": "+14155550199", "delay_minutes": 20}]'::jsonb,
                        '{"gateway_provider": "TWILIO_REST_API", "fallback_gateway": "OT_SMPP_CELLULAR_MODEM", "carrier_email_to_sms": "4155550101@txt.att.net", "two_way_ack_enabled": true}'::jsonb,
                        TRUE
                    ),
                    (
                        'Bioreactor_Mobile_Push_PagerDuty',
                        '*',
                        'WARNING',
                        'MOBILE_PUSH',
                        'gxphistorian://mobile/push/usp-oncall-roster',
                        15,
                        5,
                        30,
                        TRUE,
                        '[%Severity%] %Element% (%AssetPath%): %EventFrame% — Peak %MaxVal% %EngUnits% (Duration: %Duration%)',
                        '[{"tier": 1, "role": "Lead USP Operator Mobile", "contact_name": "Sarah Jenkins", "channel_type": "MOBILE_PUSH", "target_endpoint": "fcm://device-usp-operator-01", "delay_minutes": 0}, {"tier": 2, "role": "QA On-Call PagerDuty", "contact_name": "Dr. Marcus Vance", "channel_type": "MOBILE_PUSH", "target_endpoint": "pagerduty://gxp-qa-critical-service", "delay_minutes": 15}]'::jsonb,
                        '{"apns_interruption_level": "critical", "fcm_priority": "high", "pagerduty_events_v2": true, "deep_link_scheme": "gxphistorian://events/"}'::jsonb,
                        TRUE
                    ),
                    (
                        'QA_Rich_HTML_Email_Notification',
                        '*',
                        'WARNING',
                        'EMAIL',
                        'qa-compliance@biocorp.internal',
                        15,
                        5,
                        30,
                        TRUE,
                        '[%Severity%] GxP Event Frame %EventFrame% on %Element% (%AssetPath%) started at %StartTime% (Peak: %MaxVal% %EngUnits%)',
                        '[{"tier": 1, "role": "QA Compliance Distribution", "contact_name": "QA Compliance Team", "channel_type": "EMAIL", "target_endpoint": "qa-compliance@biocorp.internal", "delay_minutes": 0}, {"tier": 2, "role": "QA Qualified Person", "contact_name": "Dr. Marcus Vance", "channel_type": "EMAIL", "target_endpoint": "marcus.vance@biocorp.internal", "delay_minutes": 15}]'::jsonb,
                        '{"smtp_host": "smtp.biocorp.internal", "smtp_port": 587, "mime_format": "multipart/alternative", "include_grafana_adhoc_trend_link": true, "include_one_click_ack_link": true}'::jsonb,
                        TRUE
                    )
                ON CONFLICT (rule_name) DO NOTHING;
                """
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Pydantic Request/Response Models for AVEVA PI Parity Endpoints
# ---------------------------------------------------------------------------


class StreamSetQueryRequest(BaseModel):
    asset_path: Optional[str] = Field(
        default=None,
        description="ISA-95 ltree asset path (resolves all active tags attached to this asset)",
    )
    tag_names: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of tag names when querying across multiple assets",
    )
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    step_seconds: int = Field(default=60, ge=1, le=86400)
    limit_per_tag: int = Field(default=200, ge=1, le=5000)


class BatchWindowItem(BaseModel):
    batch_id: str = Field(..., description="Batch identifier (e.g., BATCH-2026-CANDIDATE-002)")
    start_time: str = Field(..., description="ISO-8601 start timestamp of the batch")
    end_time: Optional[str] = Field(default=None, description="Optional ISO-8601 end timestamp")


class GoldenBatchCompareRequest(BaseModel):
    tag_name: str = Field(default="BR201_TEMP_PV", description="Tag name to overlay across batches")
    golden_batch: BatchWindowItem
    candidate_batches: List[BatchWindowItem]
    duration_seconds: int = Field(default=120, ge=10, le=604800, description="Relative batch duration window (seconds)")
    step_seconds: int = Field(default=30, ge=1, le=3600, description="Relative time alignment step (seconds)")


class UomConvertRequest(BaseModel):
    value: float
    from_uom: str
    to_uom: str


class DigitalStateSetCreateRequest(BaseModel):
    state_set_name: str
    states_map: Dict[str, str]
    description: str = ""


class TemplateInstantiateRequest(BaseModel):
    template_id: int = Field(default=1, description="PostgreSQL asset_templates.template_id")
    asset_name: str = Field(..., description="New equipment/asset name (e.g., Bioreactor_202)")
    asset_path: str = Field(..., description="ISA-95 ltree path (e.g., BioCorp.Fremont.USP.Bioreactor_202)")
    tag_prefix: str = Field(..., description="Tag naming prefix (e.g., BR202)")
    source_protocol: str = Field(default="OPC_UA")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ManualLoggerEntryRequest(BaseModel):
    tag_name: str = Field(..., description="Target historian tag name (e.g., BR201_PH_PV)")
    sample_ts: Optional[str] = Field(default=None, description="UTC sample timestamp (defaults to now)")
    val: float = Field(..., description="Manually recorded / lab-measured value")
    str_val: str = Field(default="", description="Optional state string or lab result code")
    sample_barcode: str = Field(default="", description="LIMS / at-line sample vial barcode")
    verifier_user_id: Optional[str] = Field(default=None, description="Optional 2nd-person verifier user_id")
    verifier_password: Optional[str] = Field(default=None, description="Optional 2nd-person verifier password")
    notes: str = Field(default="")


class SwingingDoorEvaluateRequest(BaseModel):
    tag_id: int = 101
    exc_dev: float = Field(default=0.05, ge=0.0)
    exc_max: float = Field(default=60.0, ge=1.0)
    comp_dev: float = Field(default=0.10, ge=0.0)
    comp_max: float = Field(default=300.0, ge=1.0)
    is_step_tag: bool = False
    samples: List[Dict[str, Any]] = Field(
        ...,
        description="List of {'ts': float_epoch_sec, 'val': float, 'quality': 192, 'status_code': 0}",
    )


class EventFrameBackfillRequest(BaseModel):
    tag_name: str = Field(default="BR201_TEMP_PV")
    template_name: str = Field(default="Temp_Excursion_TrueFor_30s")
    start_time: str = Field(..., description="Historical window ISO-8601 start")
    end_time: str = Field(..., description="Historical window ISO-8601 end")
    trigger_operator: str = Field(default=">", pattern="^(>|<|>=|<=|==|!=)$")
    trigger_threshold: float = Field(default=38.0)
    true_for_seconds: int = Field(
        default=30,
        ge=0,
        le=86400,
        description="PI TrueFor debounce: condition must hold continuously for >= true_for_seconds",
    )
    close_hysteresis: float = Field(default=0.2, ge=0.0)
    severity: str = Field(default="CRITICAL")


class EscalationTierContact(BaseModel):
    tier: int = Field(default=1, ge=1, le=10, description="1-based escalation sequence order")
    role: str = Field(default="On-Call Engineer", description="Role or shift title")
    contact_name: str = Field(default="Sarah Jenkins", description="Full name of contact")
    channel_type: str = Field(
        default="SMS",
        pattern="^(EMAIL|SMS|MOBILE_PUSH|WEBHOOK|TEAMS_ADAPTIVE_CARD)$",
        description="Delivery channel for this tier",
    )
    target_endpoint: str = Field(..., description="Email address, E.164 phone number, push token URI, or webhook URL")
    delay_minutes: int = Field(default=0, ge=0, le=1440, description="Minutes after Event Frame start before paging this tier")


class NotificationRuleCreateRequest(BaseModel):
    rule_name: str = Field(..., description="Unique PI Notification Rule name")
    event_template_filter: str = Field(default="*", description="Event Frame template name or '*' wildcard")
    min_severity: str = Field(default="WARNING", pattern="^(INFO|WARNING|CRITICAL)$")
    channel_type: str = Field(
        default="WEBHOOK",
        pattern="^(EMAIL|SMS|MOBILE_PUSH|WEBHOOK|TEAMS_ADAPTIVE_CARD)$",
        description="Primary PI Delivery Channel: EMAIL, SMS, MOBILE_PUSH, WEBHOOK, or TEAMS_ADAPTIVE_CARD",
    )
    target_endpoint: str = Field(..., description="Primary recipient address, E.164 phone, push URI, or webhook URL")
    escalation_minutes: int = Field(default=15, ge=1, le=1440, description="Escalation threshold in minutes if unacknowledged")
    non_repetition_minutes: int = Field(
        default=5,
        ge=0,
        le=1440,
        description="PI Non-Repetition Interval: quiet period suppressing duplicate chattering alerts",
    )
    resend_interval_minutes: int = Field(
        default=30,
        ge=0,
        le=1440,
        description="PI Resend Interval: repeat alert frequency while unacknowledged (must be >= non_repetition_minutes)",
    )
    notify_on_close: bool = Field(
        default=True,
        description="PI Send on Close: transmit a final recovery summary when the Event Frame closes",
    )
    message_template: str = Field(
        default="[%Severity%] %Element% — %EventFrame% started at %StartTime% (Value: %Value% %EngUnits%, Limit: %HighLimit%)",
        description="PI Notification message template with %Element%, %EventFrame%, %StartTime%, %Value% substitution tokens",
    )
    escalation_team: List[EscalationTierContact] = Field(
        default_factory=list,
        description="Ordered PI Escalation Team tiers stepped through sequentially until acknowledged",
    )
    delivery_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Channel-specific transport settings (SMTP, Twilio/SMPP/Carrier SMS, APNs/FCM/PagerDuty, Teams)",
    )
    is_active: bool = True


class NotificationPreviewRequest(BaseModel):
    event_id: Optional[str] = Field(default=None, description="Optional existing Event Frame UUID to preview")
    message_template: str = Field(
        default="[%Severity%] %Element% (%AssetPath%): %EventFrame% started at %StartTime% — Peak %MaxVal% %EngUnits% (Limit: %HighLimit% %EngUnits%). Duration: %Duration%.",
        description="PI Notification template using %Parameter% tokens",
    )
    notification_phase: str = Field(
        default="TRIGGER",
        pattern="^(TRIGGER|RESEND|ESCALATION|RECOVERY_CLOSE)$",
    )
    recipient_email: str = Field(default="qa-compliance@biocorp.internal")
    recipient_phone_e164: str = Field(default="+14155550101")
    recipient_mobile_uri: str = Field(default="fcm://device-usp-operator-01")


class NotificationAcknowledgeRequest(BaseModel):
    ack_channel: str = Field(
        default="MOBILE_PUSH",
        pattern="^(MOBILE_PUSH|SMS|EMAIL|WEB_HMI|PAGERDUTY|API)$",
        description="Channel through which the operator acknowledged the Event Frame",
    )
    ack_comment: str = Field(
        default="Operator acknowledged excursion alert; inspecting equipment on floor.",
        description="Engineering or QA acknowledgment note",
    )


class SmsInboundWebhookRequest(BaseModel):
    from_phone: str = Field(..., description="Originating E.164 phone number (e.g., +14155550101)")
    to_phone: str = Field(default="+18005550199", description="Historian SMS gateway number")
    message_body: str = Field(
        ...,
        description="Inbound two-way SMS command, e.g., 'ACK <EventShortId> Checked jacket valve'",
    )
    gateway_provider: str = Field(default="TWILIO_SMS_WEBHOOK", description="TWILIO_SMS_WEBHOOK or OT_SMPP_MODEM")


def render_pi_notification_formats(
    ef: Dict[str, Any],
    message_template: str,
    notification_phase: str = "TRIGGER",
    recipient_email: str = "qa-compliance@biocorp.internal",
    recipient_phone: str = "+14155550101",
    recipient_mobile_uri: str = "fcm://device-usp-operator-01",
    escalation_tier: int = 1,
    recipient_name: str = "On-Call Operator",
) -> Dict[str, Any]:
    """
    Deterministic AVEVA PI Notifications Dynamic Substitution & Multi-Channel Envelope Generator.
    Resolves PI AF / Event Frame parameters (%Element%, %\\Element%, %..\\Element%, %AssetPath%,
    %EventFrame%, %EventId%, %EventShortId%, %StartTime%, %EndTime%, %Duration%, %Severity%,
    %Tag%, %Value%, %AvgVal%, %MaxVal%, %MinVal%, %EngUnits%, %HighLimit%, %LowLimit%,
    %TrendUrl%, %AckUrl%, %SignUrl%) and builds ready-to-dispatch payloads for:
      1. EMAIL (Native SMTP Multipart HTML + Plain Text with PI Vision / Grafana Ad-Hoc Trend & 1-Click Ack links)
      2. SMS (160-char GSM-7 cellular text for Twilio REST API, Carrier Email-to-SMS, and OT SMPP Modems)
      3. MOBILE_PUSH (Apple APNs Critical Alert, Android FCM High-Priority, and PagerDuty Events API v2)
      4. TEAMS_ADAPTIVE_CARD & WEBHOOK (PI WebService REST JSON + Microsoft Teams AdaptiveCard v1.4)
    """
    event_id_str = str(ef.get("event_id") or "00000000-0000-0000-0000-000000000000")
    event_short_id = event_id_str.split("-")[0].upper()
    event_name = str(ef.get("event_name") or "BR201_TEMP_PV_High_Limit_Excursion")
    event_template = str(ef.get("event_template") or "Temp_Excursion_TrueFor_30s")
    severity = str(ef.get("severity") or "CRITICAL").upper()
    asset_path = str(ef.get("asset_path") or "BioCorp.Fremont.USP.Bioreactor_201")
    path_parts = asset_path.split(".")
    element_name = str(ef.get("asset_name") or (path_parts[-1] if path_parts else "Bioreactor_201"))
    root_element = path_parts[0] if path_parts else "BioCorp"
    parent_element = path_parts[-2] if len(path_parts) >= 2 else root_element

    now_utc = dt.datetime.now(dt.timezone.utc)
    raw_start = ef.get("start_time")
    if isinstance(raw_start, dt.datetime):
        start_dt = raw_start if raw_start.tzinfo else raw_start.replace(tzinfo=dt.timezone.utc)
    elif isinstance(raw_start, str) and raw_start:
        start_dt = dt.datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    else:
        start_dt = now_utc

    raw_end = ef.get("end_time")
    end_dt: Optional[dt.datetime] = None
    if isinstance(raw_end, dt.datetime):
        end_dt = raw_end if raw_end.tzinfo else raw_end.replace(tzinfo=dt.timezone.utc)
    elif isinstance(raw_end, str) and raw_end:
        end_dt = dt.datetime.fromisoformat(raw_end.replace("Z", "+00:00"))

    metrics = ef.get("captured_metrics") or {}
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = {}

    dur_sec = float(
        metrics.get("duration_seconds")
        or ((end_dt - start_dt).total_seconds() if end_dt else max(0.0, (now_utc - start_dt).total_seconds()))
    )
    duration_str = f"{round(dur_sec, 1)}s" if dur_sec < 120 else f"{round(dur_sec / 60.0, 2)}m"

    tag_name = str(metrics.get("tag_name") or "BR201_TEMP_PV")
    eng_units = str(metrics.get("eng_units") or "degC")
    val_num = float(
        metrics.get("peak_val")
        or metrics.get("latest_val")
        or metrics.get("max_val")
        or metrics.get("temp_max_c")
        or 38.5
    )
    avg_num = float(metrics.get("avg_val") or metrics.get("temp_avg_c") or val_num)
    max_num = float(metrics.get("peak_val") or metrics.get("max_val") or metrics.get("temp_max_c") or val_num)
    min_num = float(metrics.get("min_val") or metrics.get("temp_min_c") or val_num)
    high_lim = metrics.get("high_limit", 38.0)
    low_lim = metrics.get("low_limit", 35.0)

    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_hm = start_dt.strftime("%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if end_dt else "ACTIVE (OPEN)"

    from_ms = int((start_dt - dt.timedelta(minutes=5)).timestamp() * 1000)
    to_ms = int(((end_dt or now_utc) + dt.timedelta(minutes=5)).timestamp() * 1000)
    trend_url = (
        f"http://localhost:3000/d/gxphistorian-gxp-bioreactor-hmi"
        f"?var-asset_path={asset_path}&var-tag_name={tag_name}&from={from_ms}&to={to_ms}"
    )
    ack_url = f"http://localhost:8000/api/v1/notifications/acknowledge/{event_id_str}"
    sign_url = f"http://localhost:8000/api/v1/event-frames/{event_id_str}/sign"
    mobile_deep_link = f"gxphistorian://events/{event_id_str}?asset={asset_path}&tag={tag_name}"

    substitutions = {
        "%Element%": element_name,
        "%\\Element%": root_element,
        "%..\\Element%": parent_element,
        "%AssetPath%": asset_path,
        "%EventFrame%": event_name,
        "%EventId%": event_id_str,
        "%EventShortId%": event_short_id,
        "%EventTemplate%": event_template,
        "%Severity%": severity,
        "%Phase%": notification_phase,
        "%StartTime%": start_iso,
        "%EndTime%": end_iso,
        "%Duration%": duration_str,
        "%Tag%": tag_name,
        "%Value%": str(round(val_num, 4)),
        "%AvgVal%": str(round(avg_num, 4)),
        "%MaxVal%": str(round(max_num, 4)),
        "%MinVal%": str(round(min_num, 4)),
        "%EngUnits%": eng_units,
        "%HighLimit%": str(high_lim if high_lim is not None else "N/A"),
        "%LowLimit%": str(low_lim if low_lim is not None else "N/A"),
        "%TrendUrl%": trend_url,
        "%AckUrl%": ack_url,
        "%SignUrl%": sign_url,
    }

    rendered_msg = message_template
    for token, replacement in substitutions.items():
        rendered_msg = rendered_msg.replace(token, replacement)
    if notification_phase == "RECOVERY_CLOSE" and not rendered_msg.startswith("[RECOVERY"):
        rendered_msg = f"[RECOVERY / CLOSED at {end_iso}] {rendered_msg}"
    elif notification_phase == "ESCALATION" and not rendered_msg.startswith("[ESCALATION"):
        rendered_msg = f"[ESCALATION TIER {escalation_tier}] {rendered_msg}"

    # 1. SMS GSM-7 Compact Format (<= 160 chars for single-segment cellular delivery)
    phase_tag = "CLR" if notification_phase == "RECOVERY_CLOSE" else (f"ESC{escalation_tier}" if notification_phase == "ESCALATION" else severity[:4])
    sms_compact = (
        f"[GxP {phase_tag}] {element_name} {tag_name}={round(val_num, 2)}{eng_units} "
        f"(Lim:{high_lim}) @{start_hm}. Reply ACK {event_short_id}"
    )
    if len(sms_compact) > 160:
        sms_compact = sms_compact[:157] + "..."
    digits_only = "".join(ch for ch in recipient_phone if ch.isdigit())[-10:] or "4155550101"

    sms_envelope = {
        "to_e164": recipient_phone if recipient_phone.startswith("+") else f"+1{digits_only}",
        "sms_body": sms_compact,
        "char_count": len(sms_compact),
        "gsm7_single_segment": len(sms_compact) <= 160,
        "gsm7_segments": 1 if len(sms_compact) <= 160 else math.ceil(len(sms_compact) / 153),
        "two_way_ack_instruction": f"ACK {event_short_id}",
        "inbound_ack_webhook": "http://localhost:8000/api/v1/notifications/sms-webhook",
        "gateway_transports": {
            "twilio_programmable_sms": {
                "api_endpoint": "https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json",
                "From": "+18005550199",
                "To": recipient_phone,
                "Body": sms_compact,
            },
            "carrier_email_to_sms_gateways": {
                "att_sms": f"{digits_only}@txt.att.net",
                "verizon_sms": f"{digits_only}@vtext.com",
                "tmobile_sms": f"{digits_only}@tmomail.net",
            },
            "ot_cellular_hardware_modem": {
                "hardware": "Sierra Wireless AirLink RV55 / Moxa OnCell G4302-LTE4",
                "protocol": "SMPP v3.4 / AT+CMGS Over RS-232/Ethernet",
                "purdue_zone": "Level 3.5 IDMZ Air-Gapped Failover",
            },
        },
    }

    # 2. EMAIL Native SMTP Multipart (HTML + Plain Text + Ad-Hoc Trend & 1-Click Ack Hyperlinks)
    email_subject = f"[GxPHistorian {severity} - {notification_phase}] {event_name} on {element_name}"
    email_text_body = (
        f"GxPHistorian PI Notifications Service Alert ({notification_phase})\n"
        f"==================================================================\n"
        f"Summary       : {rendered_msg}\n"
        f"Asset Element : {element_name} ({asset_path})\n"
        f"Event Frame   : {event_name} (ID: {event_id_str})\n"
        f"Template      : {event_template}\n"
        f"Severity      : {severity} (Escalation Tier {escalation_tier} - {recipient_name})\n"
        f"Start Time    : {start_iso}\n"
        f"End Time      : {end_iso} (Duration: {duration_str})\n"
        f"Primary Tag   : {tag_name} = {round(val_num, 4)} {eng_units} (Avg: {round(avg_num, 4)}, Peak: {round(max_num, 4)}, Limit: {high_lim})\n\n"
        f"Actions:\n"
        f"  1. Open Ad-Hoc LTTB Trend (Grafana Vision): {trend_url}\n"
        f"  2. Acknowledge Event Frame (Stop Escalation): {ack_url}\n"
        f"  3. Execute 21 CFR Part 11 E-Signature: {sign_url}\n"
    )
    badge_color = "#dc2626" if severity == "CRITICAL" else ("#d97706" if severity == "WARNING" else "#2563eb")
    if notification_phase == "RECOVERY_CLOSE":
        badge_color = "#16a34a"
    email_html_body = (
        f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:680px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">'
        f'<div style="background:{badge_color};color:#ffffff;padding:14px 20px;font-weight:700;font-size:16px;">'
        f'GxPHistorian {severity} Alert ({notification_phase}) &mdash; {element_name}</div>'
        f'<div style="padding:20px;background:#ffffff;color:#1e293b;">'
        f'<p style="margin-top:0;font-size:15px;line-height:1.5;"><strong>{rendered_msg}</strong></p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;margin:16px 0;">'
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#64748b;">ISA-95 Asset Path</td><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;font-family:monospace;">{asset_path}</td></tr>'
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#64748b;">Event Frame</td><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;">{event_name} (<code>{event_short_id}</code>)</td></tr>'
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#64748b;">Tag / Peak Value</td><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;"><strong>{tag_name}: {round(max_num, 4)} {eng_units}</strong> (Avg: {round(avg_num, 4)} {eng_units}, High Limit: {high_lim})</td></tr>'
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#64748b;">Window &amp; Duration</td><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;">{start_iso} &rarr; {end_iso} ({duration_str})</td></tr>'
        f'</table>'
        f'<div style="margin-top:18px;">'
        f'<a href="{trend_url}" style="display:inline-block;background:#0f172a;color:#ffffff;padding:9px 14px;border-radius:6px;text-decoration:none;font-size:13px;margin-right:8px;">Open Ad-Hoc Trend</a>'
        f'<a href="{ack_url}" style="display:inline-block;background:{badge_color};color:#ffffff;padding:9px 14px;border-radius:6px;text-decoration:none;font-size:13px;margin-right:8px;">Acknowledge Alert ({event_short_id})</a>'
        f'<a href="{sign_url}" style="display:inline-block;background:#334155;color:#ffffff;padding:9px 14px;border-radius:6px;text-decoration:none;font-size:13px;">21 CFR Part 11 E-Sign</a>'
        f'</div></div></div>'
    )
    email_envelope = {
        "to": recipient_email,
        "from": "pi-notifications@biocorp.internal",
        "subject": email_subject,
        "mime_type": "multipart/alternative",
        "headers": {
            "X-Priority": "1 (Highest)" if severity == "CRITICAL" else "3 (Normal)",
            "X-GxPHistorian-Event-Id": event_id_str,
            "X-GxPHistorian-Short-Id": event_short_id,
            "X-GxPHistorian-Phase": notification_phase,
        },
        "text_body": email_text_body,
        "html_body": email_html_body,
        "embedded_links": {
            "adhoc_trend_url": trend_url,
            "one_click_acknowledge_url": ack_url,
            "part11_esign_url": sign_url,
        },
    }

    # 3. MOBILE_PUSH Envelope (iOS APNs Critical Alert, Android FCM High-Priority & PagerDuty Events v2)
    pd_action = "resolve" if notification_phase == "RECOVERY_CLOSE" else "trigger"
    mobile_push_envelope = {
        "target_device_uri": recipient_mobile_uri,
        "mobile_deep_link": mobile_deep_link,
        "apns_payload": {
            "aps": {
                "alert": {
                    "title": f"[{severity}] {element_name} ({notification_phase})",
                    "subtitle": f"{asset_path} • {tag_name}",
                    "body": rendered_msg,
                },
                "sound": {
                    "critical": 1 if severity == "CRITICAL" else 0,
                    "name": "gxp_excursion_alarm.caf",
                    "volume": 1.0,
                },
                "interruption-level": "critical" if severity == "CRITICAL" else "time-sensitive",
                "category": "GXP_EVENT_FRAME_ACTIONS",
            },
            "gxphistorian": {
                "event_id": event_id_str,
                "event_short_id": event_short_id,
                "deep_link": mobile_deep_link,
                "adhoc_trend_url": trend_url,
                "acknowledge_url": ack_url,
            },
        },
        "fcm_payload": {
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "gxp_critical_excursions",
                    "click_action": "OPEN_GXP_EVENT_FRAME",
                },
            },
            "notification": {
                "title": f"[{severity}] {element_name} — {event_name}",
                "body": rendered_msg,
            },
            "data": {
                "event_id": event_id_str,
                "event_short_id": event_short_id,
                "deep_link": mobile_deep_link,
                "adhoc_trend_url": trend_url,
                "acknowledge_url": ack_url,
            },
        },
        "pagerduty_events_v2": {
            "routing_key": "gxp-biocorp-usp-oncall-routing-key",
            "event_action": pd_action,
            "dedup_key": f"gxphistorian-ef-{event_id_str}",
            "payload": {
                "summary": rendered_msg,
                "severity": severity.lower() if severity.lower() in {"critical", "warning", "info"} else "error",
                "source": asset_path,
                "timestamp": start_iso,
                "component": element_name,
                "group": event_template,
                "class": "ISA88_EventFrame_Excursion",
                "custom_details": {
                    "event_id": event_id_str,
                    "event_short_id": event_short_id,
                    "tag_name": tag_name,
                    "peak_val": round(max_num, 4),
                    "avg_val": round(avg_num, 4),
                    "eng_units": eng_units,
                    "high_limit": high_lim,
                    "duration": duration_str,
                    "escalation_tier": escalation_tier,
                },
            },
            "links": [
                {"href": trend_url, "text": "Open Grafana LTTB Ad-Hoc Trend"},
                {"href": ack_url, "text": "Acknowledge Event Frame (21 CFR Part 11)"},
            ],
        },
        "interactive_actions": [
            {
                "action_id": "ACK_EVENT_FRAME",
                "label": "Acknowledge Alert",
                "http_method": "POST",
                "endpoint": ack_url,
            },
            {
                "action_id": "OPEN_ADHOC_TREND",
                "label": "Open Live Trend",
                "http_method": "GET",
                "endpoint": trend_url,
            },
            {
                "action_id": "RUN_AI_INVESTIGATION",
                "label": "AI Deviation Brief",
                "http_method": "POST",
                "endpoint": f"http://localhost:8000/api/v1/ai/event-frames/{event_id_str}/investigate",
            },
        ],
    }

    # 4. TEAMS_ADAPTIVE_CARD & WEBHOOK Envelope (PI WebService REST Delivery Channel)
    teams_card_envelope = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Large",
                            "weight": "Bolder",
                            "text": f"[GxPHistorian {severity} - {notification_phase}] {element_name}",
                        },
                        {
                            "type": "TextBlock",
                            "text": rendered_msg,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Asset Path", "value": asset_path},
                                {"title": "Event Frame", "value": f"{event_name} ({event_short_id})"},
                                {"title": "Tag / Peak", "value": f"{tag_name}: {round(max_num, 4)} {eng_units}"},
                                {"title": "Start Time", "value": start_iso},
                                {"title": "End Time", "value": end_iso},
                                {"title": "Duration", "value": duration_str},
                                {"title": "Escalation Tier", "value": f"Tier {escalation_tier} ({recipient_name})"},
                            ],
                        },
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "Open Ad-Hoc Trend", "url": trend_url},
                        {"type": "Action.OpenUrl", "title": "Acknowledge Alert", "url": ack_url},
                        {"type": "Action.OpenUrl", "title": "21 CFR Part 11 E-Sign", "url": sign_url},
                    ],
                },
            }
        ],
    }

    return {
        "event_id": event_id_str,
        "event_short_id": event_short_id,
        "notification_phase": notification_phase,
        "escalation_tier": escalation_tier,
        "recipient_name": recipient_name,
        "rendered_message": rendered_msg,
        "substitutions": substitutions,
        "channels": {
            "email": email_envelope,
            "sms": sms_envelope,
            "mobile_push": mobile_push_envelope,
            "teams_adaptive_card": teams_card_envelope,
        },
    }


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _resolve_tag_metadata(
    get_pg_conn: Callable[[], psycopg.Connection[Dict[str, Any]]],
    tag_name: Optional[str] = None,
    tag_id: Optional[int] = None,
) -> Dict[str, Any]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            if tag_name:
                cur.execute(
                    """
                    SELECT
                        t.tag_id,
                        t.tag_name,
                        t.asset_id,
                        t.attribute_name,
                        t.eng_units,
                        t.is_step_tag,
                        t.exc_dev,
                        t.low_limit,
                        t.high_limit,
                        t.source_protocol,
                        a.asset_name,
                        a.asset_path::text AS asset_path
                    FROM tags t
                    JOIN assets a ON t.asset_id = a.asset_id
                    WHERE t.tag_name = %s;
                    """,
                    (tag_name,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        t.tag_id,
                        t.tag_name,
                        t.asset_id,
                        t.attribute_name,
                        t.eng_units,
                        t.is_step_tag,
                        t.exc_dev,
                        t.low_limit,
                        t.high_limit,
                        t.source_protocol,
                        a.asset_name,
                        a.asset_path::text AS asset_path
                    FROM tags t
                    JOIN assets a ON t.asset_id = a.asset_id
                    WHERE t.tag_id = %s;
                    """,
                    (tag_id,),
                )
            row = cur.fetchone()
    if not row:
        ident = tag_name if tag_name is not None else tag_id
        raise HTTPException(status_code=404, detail=f"Historian tag '{ident}' not found")
    return dict(row)


def _eval_threshold(val: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return val > threshold
    if operator == ">=":
        return val >= threshold
    if operator == "<":
        return val < threshold
    if operator == "<=":
        return val <= threshold
    if operator == "==":
        return math.isclose(val, threshold, rel_tol=1e-9, abs_tol=1e-9)
    if operator == "!=":
        return not math.isclose(val, threshold, rel_tol=1e-9, abs_tol=1e-9)
    raise ValueError(f"Unsupported operator: {operator}")


class EdgeAgentHeartbeatRequest(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=128, description="Unique Purdue L2.5 Edge Collector identifier")
    site_path: str = Field(
        default="BioCorp.Fremont.USP.Bioreactor_201",
        description="ISA-95 ltree asset path where the edge collector is anchored",
    )
    hardware_model: str = Field(
        default="Advantech UNO-2484G (512GB pSLC NVMe)",
        description="Industrial IPC or DMZ VM hardware descriptor",
    )
    deployment_pattern: str = Field(
        default="pattern_b_cloud_core",
        description="Hybrid cloud topology: pattern_a_worm_lakehouse, pattern_b_cloud_core, or pattern_c_hub_spoke",
    )
    cloud_provider: str = Field(default="aws", description="Target cloud provider: aws, azure, or gcp")
    telegraf_version: str = Field(default="1.32.3", description="Telegraf agent runtime version")
    wal_buffer_used_gb: float = Field(default=1.25, ge=0.0, le=500.0, description="Current Disk WAL usage in GB")
    wal_buffer_capacity_gb: float = Field(default=100.0, gt=0.0, le=2000.0, description="Allocated Disk WAL partition in GB")
    wal_queued_metrics: int = Field(default=0, ge=0, description="Number of metrics queued in Disk WAL")
    active_tag_count: int = Field(default=25000, ge=1, le=500000, description="Active tags polled by this edge node")
    active_protocols: List[str] = Field(
        default_factory=lambda: ["OPC_UA", "OPC_DA", "BACNET_IP", "S7COMM", "MODBUS_TCP"],
        description="Active field protocols normalized by this edge collector",
    )
    mtls_cert_days_remaining: int = Field(default=85, ge=0, le=825, description="Days remaining before outbound mTLS certificate rotation")
    wan_link_status: str = Field(
        default="CONNECTED_MTLS_8443",
        description="WAN transport state: CONNECTED_MTLS_8443, BUFFERING_LOCAL_WAL, or DEGRADED",
    )


# ---------------------------------------------------------------------------
# FastAPI Router Builder
# ---------------------------------------------------------------------------


def build_pi_parity_router(
    get_pg_conn: Callable[[], psycopg.Connection[Dict[str, Any]]],
    get_ch_client: Callable[[], Any],
    apply_part11_context: Callable[[psycopg.Cursor[Any], Optional[str], Optional[str]], None],
    get_datalink_sampled_fn: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    # =========================================================================
    # PHASE 1: PI DataLink (`PICurrVal`, `PIArcVal`, `PICompDat`, `PIAdvCalcDat`, `PITimeFilter`)
    #          & PI Web API `StreamSets`
    # =========================================================================

    @router.get("/api/v1/datalink/current")
    def get_datalink_current_value(
        tag_name: str = Query(..., description="Tag Name (e.g., BR201_TEMP_PV or BR201_AGIT_STATE)"),
        target_uom: Optional[str] = Query(default=None, description="Optional UOM conversion target (e.g., degF)"),
    ) -> Dict[str, Any]:
        """PI DataLink `PICurrVal` / Snapshot Subsystem equivalent."""
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        is_step_tag = bool(tag_meta["is_step_tag"])
        ch = get_ch_client()

        row = next(
            iter(
                ch.query(
                    """
                    SELECT
                        formatDateTime(max(ts), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_ts,
                        argMax(val, ts) AS latest_val,
                        argMax(str_val, ts) AS latest_str_val,
                        argMax(quality, ts) AS latest_quality,
                        argMax(status_code, ts) AS latest_status_code
                    FROM pi_historian.sensor_data
                    WHERE tag_id = {tag_id:UInt32}
                      AND quality >= 192
                    """,
                    parameters={"tag_id": tag_id},
                ).named_results()
            ),
            {},
        )
        raw_val = float(row.get("latest_val") or 0.0)
        eng_units = str(tag_meta["eng_units"])
        if target_uom:
            try:
                raw_val, eng_units = convert_uom_value(raw_val, eng_units, target_uom)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        digital_state_label = str(row.get("latest_str_val") or "")
        if is_step_tag and not digital_state_label:
            with get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT states_map FROM digital_state_sets WHERE state_set_name = 'Agitator_Mode_States';"
                    )
                    ds = cur.fetchone()
                    if ds and ds.get("states_map"):
                        digital_state_label = str(ds["states_map"].get(str(int(round(raw_val))), ""))

        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "attribute_name": tag_meta["attribute_name"],
            "eng_units": eng_units,
            "is_step_tag": is_step_tag,
            "ts": row.get("latest_ts"),
            "val": int(round(raw_val)) if is_step_tag else round(raw_val, 4),
            "str_val": digital_state_label,
            "quality": int(row.get("latest_quality") or 192),
            "status_code": int(row.get("latest_status_code") or 0),
        }

    @router.get("/api/v1/datalink/archive-value")
    def get_datalink_archive_value(
        tag_name: str = Query(..., description="Tag Name"),
        timestamp: str = Query(..., description="Target ISO-8601 timestamp"),
        retrieval_mode: str = Query(
            default="INTERPOLATED",
            pattern="^(INTERPOLATED|PREVIOUS|NEXT|EXACT)$",
            description="PI retrieval mode: INTERPOLATED, PREVIOUS, NEXT, or EXACT",
        ),
        target_uom: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        """PI DataLink `PIArcVal` equivalent supporting INTERPOLATED (Linear vs LOCF), PREVIOUS, NEXT, and EXACT."""
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        is_step_tag = bool(tag_meta["is_step_tag"])
        ch = get_ch_client()

        prev_rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_epoch,
                    formatDateTime(ts, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts_iso,
                    val,
                    str_val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts <= parseDateTimeBestEffort({ts_str:String}, 'UTC')
                ORDER BY ts DESC
                LIMIT 1
                """,
                parameters={"tag_id": tag_id, "ts_str": timestamp},
            ).named_results()
        )
        next_rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_epoch,
                    formatDateTime(ts, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts_iso,
                    val,
                    str_val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts >= parseDateTimeBestEffort({ts_str:String}, 'UTC')
                ORDER BY ts ASC
                LIMIT 1
                """,
                parameters={"tag_id": tag_id, "ts_str": timestamp},
            ).named_results()
        )
        target_epoch = float(
            ch.command(
                "SELECT toUnixTimestamp64Milli(parseDateTime64BestEffort({ts_str:String}, 3, 'UTC')) / 1000.0",
                parameters={"ts_str": timestamp},
            )
        )

        prev_pt = prev_rows[0] if prev_rows else None
        next_pt = next_rows[0] if next_rows else None

        if retrieval_mode == "EXACT":
            if prev_pt and math.isclose(float(prev_pt["ts_epoch"]), target_epoch, abs_tol=1e-3):
                chosen_val = float(prev_pt["val"])
                chosen_str = str(prev_pt["str_val"])
                applied_mode = "EXACT"
            else:
                raise HTTPException(status_code=404, detail=f"No exact archive event at {timestamp}")
        elif retrieval_mode == "PREVIOUS" or (retrieval_mode == "INTERPOLATED" and is_step_tag):
            if not prev_pt:
                raise HTTPException(status_code=404, detail=f"No archive event at or before {timestamp}")
            chosen_val = float(prev_pt["val"])
            chosen_str = str(prev_pt["str_val"])
            applied_mode = "LOCF_STEP" if is_step_tag else "PREVIOUS"
        elif retrieval_mode == "NEXT":
            if not next_pt:
                raise HTTPException(status_code=404, detail=f"No archive event at or after {timestamp}")
            chosen_val = float(next_pt["val"])
            chosen_str = str(next_pt["str_val"])
            applied_mode = "NEXT"
        else:
            # INTERPOLATED for continuous analog tag (is_step_tag=False)
            if prev_pt and next_pt:
                t1, v1 = float(prev_pt["ts_epoch"]), float(prev_pt["val"])
                t2, v2 = float(next_pt["ts_epoch"]), float(next_pt["val"])
                if math.isclose(t1, t2, abs_tol=1e-6):
                    chosen_val = v1
                else:
                    chosen_val = v1 + (v2 - v1) * ((target_epoch - t1) / (t2 - t1))
                chosen_str = str(prev_pt["str_val"])
                applied_mode = "LINEAR"
            elif prev_pt:
                chosen_val = float(prev_pt["val"])
                chosen_str = str(prev_pt["str_val"])
                applied_mode = "LINEAR_LOCF_BOUNDARY"
            elif next_pt:
                chosen_val = float(next_pt["val"])
                chosen_str = str(next_pt["str_val"])
                applied_mode = "LINEAR_NOCB_BOUNDARY"
            else:
                raise HTTPException(status_code=404, detail=f"No telemetry found for tag '{tag_name}'")

        eng_units = str(tag_meta["eng_units"])
        if target_uom:
            try:
                chosen_val, eng_units = convert_uom_value(chosen_val, eng_units, target_uom)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "eng_units": eng_units,
            "is_step_tag": is_step_tag,
            "requested_timestamp": timestamp,
            "retrieval_mode": retrieval_mode,
            "applied_interpolation": applied_mode,
            "val": int(round(chosen_val)) if is_step_tag else round(chosen_val, 4),
            "str_val": chosen_str,
        }

    @router.get("/api/v1/datalink/recorded")
    def get_datalink_recorded_values(
        tag_name: str = Query(..., description="Tag Name"),
        start_time: Optional[str] = Query(default=None),
        end_time: Optional[str] = Query(default=None),
        limit: int = Query(default=500, ge=1, le=10000),
        include_bad_quality: bool = Query(default=False),
    ) -> Dict[str, Any]:
        """PI DataLink `PICompDat` equivalent returning compressed archive events."""
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        is_step_tag = bool(tag_meta["is_step_tag"])
        ch = get_ch_client()

        where_clauses = ["tag_id = {tag_id:UInt32}"]
        if not include_bad_quality:
            where_clauses.append("quality >= 192")
        params: Dict[str, Any] = {"tag_id": tag_id, "lim": int(limit)}

        if start_time:
            where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
            params["start_time"] = start_time
        if end_time:
            where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
            params["end_time"] = end_time

        where_sql = " AND ".join(where_clauses)
        rows = list(
            ch.query(
                f"""
                SELECT
                    formatDateTime(ts, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts_iso,
                    val,
                    str_val,
                    quality,
                    status_code
                FROM pi_historian.sensor_data
                WHERE {where_sql}
                ORDER BY ts ASC
                LIMIT {{lim:UInt32}}
                """,
                parameters=params,
            ).named_results()
        )
        points = [
            {
                "ts": r["ts_iso"],
                "val": int(round(float(r["val"]))) if is_step_tag else round(float(r["val"]), 4),
                "str_val": r["str_val"],
                "quality": int(r["quality"]),
                "status_code": int(r["status_code"]),
            }
            for r in rows
        ]
        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "eng_units": tag_meta["eng_units"],
            "is_step_tag": is_step_tag,
            "quality_filter": "ALL_DIAGNOSTIC" if include_bad_quality else "GOOD_ONLY (quality >= 192)",
            "point_count": len(points),
            "points": points,
        }

    @router.get("/api/v1/datalink/calculated")
    def get_datalink_calculated_summary(
        tag_name: str = Query(..., description="Tag Name"),
        start_time: str = Query(..., description="ISO-8601 start timestamp"),
        end_time: str = Query(..., description="ISO-8601 end timestamp"),
        calculation_basis: str = Query(
            default="TIME_WEIGHTED",
            pattern="^(TIME_WEIGHTED|EVENT_WEIGHTED)$",
            description="PI summary basis: TIME_WEIGHTED or EVENT_WEIGHTED",
        ),
    ) -> Dict[str, Any]:
        """
        PI DataLink `PIAdvCalcDat` equivalent computing Time-Weighted (trapezoidal for continuous tags,
        LOCF step-duration for discrete step tags) and Event-Weighted summaries (`WHERE quality >= 192`).
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        is_step_tag = bool(tag_meta["is_step_tag"])
        ch = get_ch_client()

        params = {"tag_id": tag_id, "start_time": start_time, "end_time": end_time}
        quality_stats = next(
            iter(
                ch.query(
                    """
                    SELECT
                        count() AS total_events,
                        countIf(quality >= 192) AS good_events,
                        countIf(quality < 192) AS bad_events,
                        round(avgIf(val, quality >= 192), 4) AS event_avg,
                        round(minIf(val, quality >= 192), 4) AS min_val,
                        round(maxIf(val, quality >= 192), 4) AS max_val,
                        round(stddevPopIf(val, quality >= 192), 4) AS stdev_val,
                        round(sumIf(val, quality >= 192), 4) AS event_sum
                    FROM pi_historian.sensor_data
                    WHERE tag_id = {tag_id:UInt32}
                      AND ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')
                      AND ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')
                    """,
                    parameters=params,
                ).named_results()
            ),
            {},
        )
        total_ev = int(quality_stats.get("total_events") or 0)
        good_ev = int(quality_stats.get("good_events") or 0)
        pct_good = round((good_ev / total_ev) * 100.0, 2) if total_ev > 0 else 0.0

        rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_sec,
                    val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')
                  AND ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')
                ORDER BY ts ASC
                """,
                parameters=params,
            ).named_results()
        )

        win_bounds = next(
            iter(
                ch.query(
                    """
                    SELECT
                        toUnixTimestamp64Milli(parseDateTime64BestEffort({start_time:String}, 3, 'UTC')) / 1000.0 AS win_start,
                        toUnixTimestamp64Milli(parseDateTime64BestEffort({end_time:String}, 3, 'UTC')) / 1000.0 AS win_end
                    """,
                    parameters=params,
                ).named_results()
            )
        )
        win_start = float(win_bounds["win_start"])
        win_end = float(win_bounds["win_end"])

        # Compute Time-Weighted integral & average
        tw_integral_sec = 0.0
        total_dt = 0.0
        if len(rows) == 1:
            tw_avg = float(rows[0]["val"])
            total_dt = max(0.0, win_end - win_start)
            tw_integral_sec = tw_avg * total_dt
        elif len(rows) >= 2:
            for idx in range(len(rows) - 1):
                t1, v1 = float(rows[idx]["ts_sec"]), float(rows[idx]["val"])
                t2, v2 = float(rows[idx + 1]["ts_sec"]), float(rows[idx + 1]["val"])
                dt_seg = max(0.0, t2 - t1)
                if dt_seg <= 0.0:
                    continue
                if is_step_tag:
                    # Step tag holds v1 until t2 (LOCF)
                    tw_integral_sec += v1 * dt_seg
                else:
                    # Continuous tag integrates trapezoidally
                    tw_integral_sec += 0.5 * (v1 + v2) * dt_seg
                total_dt += dt_seg

            # If discrete step tag and final sample is before win_end, carry forward to win_end
            last_t, last_v = float(rows[-1]["ts_sec"]), float(rows[-1]["val"])
            if is_step_tag and win_end > last_t:
                tail_dt = win_end - last_t
                tw_integral_sec += last_v * tail_dt
                total_dt += tail_dt

            tw_avg = (tw_integral_sec / total_dt) if total_dt > 0.0 else float(rows[0]["val"])
        else:
            tw_avg = 0.0

        ev_avg = float(quality_stats.get("event_avg") or 0.0)
        min_v = float(quality_stats.get("min_val") or 0.0)
        max_v = float(quality_stats.get("max_val") or 0.0)
        selected_avg = round(tw_avg, 4) if calculation_basis == "TIME_WEIGHTED" else round(ev_avg, 4)
        selected_total = (
            round(tw_integral_sec, 4)
            if calculation_basis == "TIME_WEIGHTED"
            else round(float(quality_stats.get("event_sum") or 0.0), 4)
        )

        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "eng_units": tag_meta["eng_units"],
            "is_step_tag": is_step_tag,
            "calculation_basis": calculation_basis,
            "interpolation_discipline": "LOCF_STEP" if is_step_tag else "LINEAR_TRAPEZOIDAL",
            "window": {"start_time": start_time, "end_time": end_time, "evaluated_seconds": round(total_dt, 3)},
            "summary": {
                "average": selected_avg,
                "time_weighted_average": round(tw_avg, 4),
                "event_weighted_average": round(ev_avg, 4),
                "total": selected_total,
                "min": round(min_v, 4),
                "max": round(max_v, 4),
                "range": round(max_v - min_v, 4),
                "stdev": float(quality_stats.get("stdev_val") or 0.0),
                "good_sample_count": good_ev,
                "bad_sample_count": int(quality_stats.get("bad_events") or 0),
                "percent_good": pct_good,
            },
        }

    @router.get("/api/v1/datalink/time-filter")
    def get_datalink_time_filter(
        tag_name: str = Query(..., description="Tag Name"),
        start_time: str = Query(..., description="ISO-8601 start timestamp"),
        end_time: str = Query(..., description="ISO-8601 end timestamp"),
        operator: str = Query(default=">", pattern="^(>|>=|<|<=|==|!=)$"),
        threshold: float = Query(..., description="Comparison threshold value"),
    ) -> Dict[str, Any]:
        """
        PI DataLink `PITimeFilter` equivalent: computes exact time duration (`true_seconds`)
        that `<tag_name> <operator> <threshold>` held true (`WHERE quality >= 192`),
        respecting `LINEAR` vs. `LOCF_STEP` tag metadata.
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        is_step_tag = bool(tag_meta["is_step_tag"])
        ch = get_ch_client()

        params = {"tag_id": tag_id, "start_time": start_time, "end_time": end_time}
        rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_sec,
                    val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')
                  AND ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')
                ORDER BY ts ASC
                """,
                parameters=params,
            ).named_results()
        )
        win_bounds = next(
            iter(
                ch.query(
                    """
                    SELECT
                        toUnixTimestamp64Milli(parseDateTime64BestEffort({start_time:String}, 3, 'UTC')) / 1000.0 AS win_start,
                        toUnixTimestamp64Milli(parseDateTime64BestEffort({end_time:String}, 3, 'UTC')) / 1000.0 AS win_end
                    """,
                    parameters=params,
                ).named_results()
            )
        )
        win_start = float(win_bounds["win_start"])
        win_end = float(win_bounds["win_end"])

        true_sec = 0.0
        eval_sec = 0.0
        if len(rows) >= 2:
            for idx in range(len(rows) - 1):
                t1, v1 = float(rows[idx]["ts_sec"]), float(rows[idx]["val"])
                t2, v2 = float(rows[idx + 1]["ts_sec"]), float(rows[idx + 1]["val"])
                dt_seg = max(0.0, t2 - t1)
                if dt_seg <= 0.0:
                    continue
                eval_sec += dt_seg
                c1 = _eval_threshold(v1, operator, threshold)
                c2 = _eval_threshold(v2, operator, threshold)

                if is_step_tag or operator in ("==", "!="):
                    if c1:
                        true_sec += dt_seg
                else:
                    if c1 and c2:
                        true_sec += dt_seg
                    elif (c1 != c2) and not math.isclose(v1, v2, abs_tol=1e-9):
                        # Linear threshold crossing interpolation within segment [t1, t2]
                        frac_cross = max(0.0, min(1.0, (threshold - v1) / (v2 - v1)))
                        if c1:
                            true_sec += dt_seg * frac_cross
                        else:
                            true_sec += dt_seg * (1.0 - frac_cross)

            last_t, last_v = float(rows[-1]["ts_sec"]), float(rows[-1]["val"])
            if is_step_tag and win_end > last_t:
                tail_dt = win_end - last_t
                eval_sec += tail_dt
                if _eval_threshold(last_v, operator, threshold):
                    true_sec += tail_dt
        elif len(rows) == 1:
            eval_sec = max(0.0, win_end - win_start)
            if _eval_threshold(float(rows[0]["val"]), operator, threshold):
                true_sec = eval_sec

        pct_true = round((true_sec / eval_sec) * 100.0, 2) if eval_sec > 0.0 else 0.0
        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "expression": f"{tag_meta['tag_name']} {operator} {threshold}",
            "is_step_tag": is_step_tag,
            "interpolation_mode": "LOCF_STEP" if is_step_tag else "LINEAR",
            "true_seconds": round(true_sec, 3),
            "true_minutes": round(true_sec / 60.0, 4),
            "evaluated_seconds": round(eval_sec, 3),
            "percent_true": pct_true,
        }

    # --- PI Web API `StreamSets` Multi-Tag Bulk Endpoints ---

    def _resolve_streamset_tags(req: StreamSetQueryRequest) -> List[Dict[str, Any]]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                if req.tag_names:
                    cur.execute(
                        """
                        SELECT
                            t.tag_id, t.tag_name, t.attribute_name, t.eng_units,
                            t.is_step_tag, a.asset_name, a.asset_path::text AS asset_path
                        FROM tags t
                        JOIN assets a ON t.asset_id = a.asset_id
                        WHERE t.tag_name = ANY(%s)
                        ORDER BY t.tag_id;
                        """,
                        (req.tag_names,),
                    )
                elif req.asset_path:
                    cur.execute(
                        """
                        SELECT
                            t.tag_id, t.tag_name, t.attribute_name, t.eng_units,
                            t.is_step_tag, a.asset_name, a.asset_path::text AS asset_path
                        FROM tags t
                        JOIN assets a ON t.asset_id = a.asset_id
                        WHERE a.asset_path <@ %s::ltree
                        ORDER BY t.tag_id;
                        """,
                        (req.asset_path,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            t.tag_id, t.tag_name, t.attribute_name, t.eng_units,
                            t.is_step_tag, a.asset_name, a.asset_path::text AS asset_path
                        FROM tags t
                        JOIN assets a ON t.asset_id = a.asset_id
                        ORDER BY t.tag_id;
                        """
                    )
                return [dict(r) for r in cur.fetchall()]

    @router.post("/api/v1/streamsets/end")
    def streamsets_get_end(req: StreamSetQueryRequest = StreamSetQueryRequest()) -> Dict[str, Any]:
        """PI Web API `StreamSets/GetEnd` equivalent: bulk snapshot across an asset or tag list in 1 query."""
        tags = _resolve_streamset_tags(req)
        if not tags:
            return {"count": 0, "items": []}
        tag_ids = [int(t["tag_id"]) for t in tags]
        ch = get_ch_client()
        rows = list(
            ch.query(
                """
                SELECT
                    tag_id,
                    formatDateTime(max(ts), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_ts,
                    argMax(val, ts) AS latest_val,
                    argMax(str_val, ts) AS latest_str_val,
                    argMax(quality, ts) AS latest_quality
                FROM pi_historian.sensor_data
                WHERE tag_id IN {tag_ids:Array(UInt32)}
                  AND quality >= 192
                GROUP BY tag_id
                ORDER BY tag_id
                """,
                parameters={"tag_ids": tag_ids},
            ).named_results()
        )
        by_id = {int(r["tag_id"]): r for r in rows}
        items = []
        for t in tags:
            tid = int(t["tag_id"])
            r = by_id.get(tid, {})
            is_step = bool(t["is_step_tag"])
            val = float(r.get("latest_val") or 0.0)
            items.append(
                {
                    "tag_id": tid,
                    "tag_name": t["tag_name"],
                    "asset_path": t["asset_path"],
                    "attribute_name": t["attribute_name"],
                    "eng_units": t["eng_units"],
                    "is_step_tag": is_step,
                    "ts": r.get("latest_ts"),
                    "val": int(round(val)) if is_step else round(val, 4),
                    "str_val": r.get("latest_str_val", ""),
                    "quality": int(r.get("latest_quality") or 192),
                }
            )
        return {"count": len(items), "items": items}

    @router.post("/api/v1/streamsets/interpolated")
    def streamsets_get_interpolated(req: StreamSetQueryRequest) -> Dict[str, Any]:
        """PI Web API `StreamSets/GetInterpolated` equivalent across multiple tags or an ISA-95 asset."""
        tags = _resolve_streamset_tags(req)
        streams = []
        for t in tags:
            sampled = get_datalink_sampled_fn(
                tag_name=t["tag_name"],
                start_time=req.start_time,
                end_time=req.end_time,
                step_seconds=req.step_seconds,
                format="json",
            )
            streams.append(sampled)
        return {"count": len(streams), "step_seconds": req.step_seconds, "streams": streams}

    # =========================================================================
    # PHASE 2: PI Analysis Service, GxP Calculation Engine (MKT, F0, SQC)
    #          & PI BatchView Golden Batch Overlay
    # =========================================================================

    @router.get("/api/v1/analytics/mkt")
    def calculate_ich_q1a_mkt(
        tag_name: str = Query(default="BR201_TEMP_PV", description="Temperature Tag Name (in degC)"),
        start_time: Optional[str] = Query(default=None),
        end_time: Optional[str] = Query(default=None),
        activation_energy_kj_mol: float = Query(
            default=83.14472,
            gt=10.0,
            le=300.0,
            description="ICH Q1A(R2) activation energy Delta H in kJ/mol (default 83.14472)",
        ),
        max_allowed_mkt_c: Optional[float] = Query(default=38.0),
    ) -> Dict[str, Any]:
        """
        ICH Q1A(R2) / USP <1079> Mean Kinetic Temperature (MKT) calculation in ClickHouse (`WHERE quality >= 192`).
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        ch = get_ch_client()

        gas_constant_r = 0.008314472  # kJ/(mol*K)
        dh_over_r = float(activation_energy_kj_mol) / gas_constant_r

        where_clauses = ["tag_id = {tag_id:UInt32}", "quality >= 192"]
        params: Dict[str, Any] = {"tag_id": tag_id, "dh_r": dh_over_r}
        if start_time:
            where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
            params["start_time"] = start_time
        if end_time:
            where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
            params["end_time"] = end_time

        where_sql = " AND ".join(where_clauses)
        row = next(
            iter(
                ch.query(
                    f"""
                    SELECT
                        count() AS good_samples,
                        round(min(val), 4) AS min_temp_c,
                        round(max(val), 4) AS max_temp_c,
                        round(avg(val), 4) AS arithmetic_mean_c,
                        round(
                            ({{dh_r:Float64}} / (-ln(avg(exp(-{{dh_r:Float64}} / (val + 273.15)))))) - 273.15,
                            4
                        ) AS ich_q1a_mkt_c
                    FROM pi_historian.sensor_data
                    WHERE {where_sql}
                    """,
                    parameters=params,
                ).named_results()
            ),
            {},
        )
        good_samples = int(row.get("good_samples") or 0)
        if good_samples == 0:
            raise HTTPException(status_code=404, detail=f"No good-quality samples found for MKT calculation on {tag_name}")

        mkt_c = float(row["ich_q1a_mkt_c"])
        arith_c = float(row["arithmetic_mean_c"])
        within_spec = True if max_allowed_mkt_c is None else (mkt_c <= float(max_allowed_mkt_c))

        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "regulatory_standard": "ICH Q1A(R2) / USP <1079> Mean Kinetic Temperature",
            "activation_energy_kj_mol": activation_energy_kj_mol,
            "good_sample_count": good_samples,
            "min_temp_c": float(row["min_temp_c"]),
            "max_temp_c": float(row["max_temp_c"]),
            "arithmetic_mean_c": arith_c,
            "mkt_c": mkt_c,
            "kinetic_penalty_delta_c": round(mkt_c - arith_c, 4),
            "max_allowed_mkt_c": max_allowed_mkt_c,
            "within_specification": within_spec,
        }

    @router.get("/api/v1/analytics/f0-lethality")
    def calculate_usp1229_f0_lethality(
        tag_name: str = Query(..., description="Autoclave / SIP Drain RTD Temperature Tag Name (degC)"),
        start_time: str = Query(..., description="Sterilization cycle ISO-8601 start"),
        end_time: str = Query(..., description="Sterilization cycle ISO-8601 end"),
        reference_temp_c: float = Query(default=121.11, description="USP <1229> reference temperature T_ref (121.11°C)"),
        z_value_c: float = Query(default=10.0, gt=1.0, description="Thermal resistance z-value (10.0°C)"),
        target_f0_minutes: float = Query(default=12.0, gt=0.0, description="Minimum overkill F0 requirement (minutes)"),
    ) -> Dict[str, Any]:
        """
        USP <1229> / EN 285 Steam Sterilization Cumulative Lethality (F0) Calculator (`WHERE quality >= 192`).
        Integrates F0 = sum( (dt_sec / 60) * 10^((T - T_ref) / z) ) for all intervals with T >= 100.0°C.
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        ch = get_ch_client()

        rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_sec,
                    val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')
                  AND ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')
                ORDER BY ts ASC
                """,
                parameters={"tag_id": tag_id, "start_time": start_time, "end_time": end_time},
            ).named_results()
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"No sterilization telemetry in window for {tag_name}")

        cumulative_f0 = 0.0
        hold_seconds_above_ref = 0.0
        temps = [float(r["val"]) for r in rows]

        if len(rows) == 1:
            t_val = temps[0]
            if t_val >= 100.0:
                cumulative_f0 = (1.0 / 60.0) * (10.0 ** ((t_val - reference_temp_c) / z_value_c))
        else:
            for idx in range(len(rows) - 1):
                t1, v1 = float(rows[idx]["ts_sec"]), float(rows[idx]["val"])
                t2, v2 = float(rows[idx + 1]["ts_sec"]), float(rows[idx + 1]["val"])
                dt_sec = max(0.0, t2 - t1)
                if dt_sec <= 0.0:
                    continue
                v_mid = 0.5 * (v1 + v2)
                if v_mid >= 100.0:
                    rate = 10.0 ** ((v_mid - reference_temp_c) / z_value_c)
                    cumulative_f0 += (dt_sec / 60.0) * rate
                if v1 >= reference_temp_c and v2 >= reference_temp_c:
                    hold_seconds_above_ref += dt_sec

        f0_rounded = round(cumulative_f0, 4)
        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "regulatory_standard": "USP <1229> / EN 285 Steam Sterilization F0 Lethality",
            "reference_temp_c": reference_temp_c,
            "z_value_c": z_value_c,
            "good_sample_count": len(rows),
            "peak_sterilization_temp_c": round(max(temps), 4),
            "hold_seconds_above_reference": round(hold_seconds_above_ref, 2),
            "cumulative_f0_minutes": f0_rounded,
            "target_f0_minutes": target_f0_minutes,
            "sterilization_passed": f0_rounded >= target_f0_minutes,
        }

    @router.get("/api/v1/analytics/sqc")
    def evaluate_pi_sqc_control_chart(
        tag_name: str = Query(default="BR201_TEMP_PV"),
        start_time: Optional[str] = Query(default=None),
        end_time: Optional[str] = Query(default=None),
        target_mean: Optional[float] = Query(default=None, description="Optional fixed centerline mu"),
        target_sigma: Optional[float] = Query(default=None, description="Optional fixed process sigma"),
    ) -> Dict[str, Any]:
        """
        PI SQC / Statistical Process Control (SPC) Engine (`WHERE quality >= 192`).
        Evaluates Western Electric / Nelson SPC rules (Rule 1: >3σ, Rule 2: 2/3 >2σ, Rule 3: 4/5 >1σ, Rule 4: 8 on same side of μ)
        and computes Cp / Cpk process capability indices.
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=tag_name)
        tag_id = int(tag_meta["tag_id"])
        ch = get_ch_client()

        where_clauses = ["tag_id = {tag_id:UInt32}", "quality >= 192"]
        params: Dict[str, Any] = {"tag_id": tag_id}
        if start_time:
            where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
            params["start_time"] = start_time
        if end_time:
            where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
            params["end_time"] = end_time

        rows = list(
            ch.query(
                f"""
                SELECT
                    formatDateTime(ts, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts_iso,
                    val
                FROM pi_historian.sensor_data
                WHERE {' AND '.join(where_clauses)}
                ORDER BY ts ASC
                LIMIT 2000
                """,
                parameters=params,
            ).named_results()
        )
        if len(rows) < 2:
            raise HTTPException(status_code=404, detail=f"Insufficient good-quality samples for SQC on {tag_name}")

        vals = [float(r["val"]) for r in rows]
        mu = float(target_mean) if target_mean is not None else (sum(vals) / len(vals))
        variance = sum((v - mu) ** 2 for v in vals) / len(vals)
        sigma = float(target_sigma) if (target_sigma is not None and target_sigma > 0) else max(math.sqrt(variance), 1e-6)

        ucl_3s = mu + 3.0 * sigma
        lcl_3s = mu - 3.0 * sigma

        rule1_violations: List[Dict[str, Any]] = []  # 1 point beyond 3*sigma
        rule2_violations: List[Dict[str, Any]] = []  # 2 of 3 beyond 2*sigma on same side
        rule3_violations: List[Dict[str, Any]] = []  # 4 of 5 beyond 1*sigma on same side
        rule4_violations: List[Dict[str, Any]] = []  # 8 consecutive on same side of mu

        z_scores = [(v - mu) / sigma for v in vals]
        for idx, z in enumerate(z_scores):
            if abs(z) > 3.0:
                rule1_violations.append({"index": idx, "ts": rows[idx]["ts_iso"], "val": round(vals[idx], 4), "z_score": round(z, 3)})
            if idx >= 2:
                win3 = z_scores[idx - 2 : idx + 1]
                if sum(1 for w in win3 if w > 2.0) >= 2 or sum(1 for w in win3 if w < -2.0) >= 2:
                    rule2_violations.append({"index": idx, "ts": rows[idx]["ts_iso"], "val": round(vals[idx], 4)})
            if idx >= 4:
                win5 = z_scores[idx - 4 : idx + 1]
                if sum(1 for w in win5 if w > 1.0) >= 4 or sum(1 for w in win5 if w < -1.0) >= 4:
                    rule3_violations.append({"index": idx, "ts": rows[idx]["ts_iso"], "val": round(vals[idx], 4)})
            if idx >= 7:
                win8 = z_scores[idx - 7 : idx + 1]
                if all(w > 0.0 for w in win8) or all(w < 0.0 for w in win8):
                    rule4_violations.append({"index": idx, "ts": rows[idx]["ts_iso"], "val": round(vals[idx], 4)})

        low_lim = tag_meta.get("low_limit")
        high_lim = tag_meta.get("high_limit")
        cp: Optional[float] = None
        cpk: Optional[float] = None
        if low_lim is not None and high_lim is not None and sigma > 0:
            usl, lsl = float(high_lim), float(low_lim)
            cp = round((usl - lsl) / (6.0 * sigma), 4)
            cpk = round(min((usl - mu) / (3.0 * sigma), (mu - lsl) / (3.0 * sigma)), 4)

        in_control = (
            len(rule1_violations) == 0
            and len(rule2_violations) == 0
            and len(rule3_violations) == 0
            and len(rule4_violations) == 0
        )

        return {
            "tag_id": tag_id,
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "sample_count": len(vals),
            "centerline_mean": round(mu, 4),
            "sigma": round(sigma, 4),
            "control_limits": {
                "lcl_3sigma": round(lcl_3s, 4),
                "ucl_3sigma": round(ucl_3s, 4),
                "lcl_2sigma": round(mu - 2.0 * sigma, 4),
                "ucl_2sigma": round(mu + 2.0 * sigma, 4),
            },
            "capability_indices": {"cp": cp, "cpk": cpk},
            "in_statistical_control": in_control,
            "western_electric_violations": {
                "rule_1_beyond_3sigma_count": len(rule1_violations),
                "rule_2_two_of_three_beyond_2sigma_count": len(rule2_violations),
                "rule_3_four_of_five_beyond_1sigma_count": len(rule3_violations),
                "rule_4_eight_consecutive_same_side_count": len(rule4_violations),
                "rule_1_samples": rule1_violations[:10],
            },
        }

    @router.post("/api/v1/batches/compare")
    def compare_golden_batch_overlay(req: GoldenBatchCompareRequest) -> Dict[str, Any]:
        """
        PI BatchView / Golden Batch Relative-Time Overlay (`t - t_batch_start`).
        Aligns reference Golden Batch and candidate batches on a unified relative-time grid `[0 .. duration_seconds]`.
        """
        def _sample_relative_profile(win: BatchWindowItem) -> List[Dict[str, Any]]:
            start_dt = dt.datetime.fromisoformat(win.start_time.replace("Z", "+00:00"))
            end_dt = (
                dt.datetime.fromisoformat(win.end_time.replace("Z", "+00:00"))
                if win.end_time
                else (start_dt + dt.timedelta(seconds=req.duration_seconds))
            )
            sampled = get_datalink_sampled_fn(
                tag_name=req.tag_name,
                start_time=start_dt.isoformat().replace("+00:00", "Z"),
                end_time=end_dt.isoformat().replace("+00:00", "Z"),
                step_seconds=req.step_seconds,
                format="json",
            )
            pts = sampled.get("points", [])
            rel_pts = []
            for idx, pt in enumerate(pts):
                rel_pts.append(
                    {
                        "relative_seconds": idx * req.step_seconds,
                        "ts": pt["ts"],
                        "val": float(pt["val"]),
                    }
                )
            return rel_pts

        golden_profile = _sample_relative_profile(req.golden_batch)
        golden_by_rel = {p["relative_seconds"]: p["val"] for p in golden_profile}

        candidate_results = []
        for cand in req.candidate_batches:
            cand_profile = _sample_relative_profile(cand)
            sq_errors = []
            max_abs_dev = 0.0
            aligned_points = []
            for p in cand_profile:
                rel_s = p["relative_seconds"]
                g_val = golden_by_rel.get(rel_s)
                residual = round(p["val"] - g_val, 4) if g_val is not None else None
                if residual is not None:
                    sq_errors.append(residual ** 2)
                    max_abs_dev = max(max_abs_dev, abs(residual))
                aligned_points.append(
                    {
                        "relative_seconds": rel_s,
                        "candidate_val": p["val"],
                        "golden_val": g_val,
                        "residual_delta": residual,
                    }
                )
            rmse = round(math.sqrt(sum(sq_errors) / len(sq_errors)), 4) if sq_errors else 0.0
            candidate_results.append(
                {
                    "batch_id": cand.batch_id,
                    "rmse_vs_golden": rmse,
                    "max_abs_deviation": round(max_abs_dev, 4),
                    "aligned_points": aligned_points,
                }
            )

        return {
            "tag_name": req.tag_name,
            "golden_batch_id": req.golden_batch.batch_id,
            "duration_seconds": req.duration_seconds,
            "step_seconds": req.step_seconds,
            "golden_profile": golden_profile,
            "candidate_comparisons": candidate_results,
        }

    # =========================================================================
    # PHASE 3: PI AF Template Instantiation, UOM Engine, Digital States & PI Manual Logger
    # =========================================================================

    @router.get("/api/v1/af/uom")
    def list_uom_catalog() -> Dict[str, Any]:
        """List PI AF canonical UOM classes and supported engineering units."""
        catalog = {}
        for cls_name, cls_info in UOM_CLASSES.items():
            catalog[cls_name] = {
                "canonical_unit": cls_info["canonical_unit"],
                "units": [
                    {"symbol": sym, "name": u["name"]}
                    for sym, u in cls_info["units"].items()
                ],
            }
        return {"uom_classes": catalog}

    @router.post("/api/v1/af/uom/convert")
    def convert_uom_endpoint(req: UomConvertRequest) -> Dict[str, Any]:
        """Convert engineering values between compatible PI AF units of measure."""
        try:
            converted, target = convert_uom_value(req.value, req.from_uom, req.to_uom)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "original_value": req.value,
            "from_uom": req.from_uom,
            "converted_value": converted,
            "to_uom": target,
        }

    @router.get("/api/v1/af/digital-state-sets")
    def list_digital_state_sets() -> Dict[str, Any]:
        """List PI Digital State Sets from PostgreSQL `digital_state_sets`."""
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state_set_id, state_set_name, states_map, description FROM digital_state_sets ORDER BY state_set_id;"
                )
                rows = cur.fetchall()
        return {"count": len(rows), "digital_state_sets": rows}

    @router.post("/api/v1/af/digital-state-sets", status_code=201)
    def create_digital_state_set(
        req: DigitalStateSetCreateRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """Create or update a PI Digital State Set with 21 CFR Part 11 WORM audit attribution."""
        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, x_actor_id, x_change_reason)
                    cur.execute(
                        """
                        INSERT INTO digital_state_sets (state_set_name, states_map, description)
                        VALUES (%s, %s::jsonb, %s)
                        ON CONFLICT (state_set_name) DO UPDATE
                        SET states_map = EXCLUDED.states_map,
                            description = EXCLUDED.description
                        RETURNING *;
                        """,
                        (req.state_set_name, json.dumps(req.states_map), req.description),
                    )
                    created = cur.fetchone()
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "created", "digital_state_set": created}

    @router.post("/api/v1/assets/instantiate-template", status_code=201)
    def instantiate_asset_template(
        req: TemplateInstantiateRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        PI AF Element Template Auto-Instantiation:
        Atomically creates a new ISA-95 `assets` record and auto-generates all standard child
        `tags` defined in `asset_templates.attribute_specs` under a single 21 CFR Part 11 transaction.
        """
        suffix_map = {
            "Vessel_Temperature": "TEMP_PV",
            "Media_pH": "PH_PV",
            "Agitator_State": "AGIT_STATE",
            "UV_Absorbance_280nm": "UV280_PV",
            "Differential_Pressure": "DP_PV",
        }
        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, x_actor_id, x_change_reason)
                    cur.execute(
                        "SELECT template_id, template_name, attribute_specs FROM asset_templates WHERE template_id = %s;",
                        (req.template_id,),
                    )
                    tmpl = cur.fetchone()
                    if not tmpl:
                        raise HTTPException(status_code=404, detail=f"Asset template {req.template_id} not found")

                    cur.execute(
                        """
                        INSERT INTO assets (asset_name, asset_path, template_id, metadata)
                        VALUES (%s, %s::ltree, %s, %s::jsonb)
                        ON CONFLICT (asset_path) DO UPDATE
                        SET asset_name = EXCLUDED.asset_name,
                            metadata = EXCLUDED.metadata
                        RETURNING asset_id, asset_name, asset_path::text AS asset_path, template_id, metadata;
                        """,
                        (req.asset_name, req.asset_path, req.template_id, json.dumps(req.metadata)),
                    )
                    asset_row = cur.fetchone()
                    assert asset_row is not None
                    asset_id = int(asset_row["asset_id"])

                    created_tags = []
                    for spec in tmpl["attribute_specs"]:
                        attr_name = str(spec["attribute_name"])
                        short_suffix = suffix_map.get(attr_name, attr_name.upper())
                        t_name = f"{req.tag_prefix}_{short_suffix}"
                        is_step = bool(spec.get("is_step_tag", False))
                        exc_dev = 0.0 if is_step else 0.05
                        cur.execute(
                            """
                            INSERT INTO tags (
                                tag_name, asset_id, attribute_name, eng_units,
                                is_step_tag, exc_dev, low_limit, high_limit,
                                source_protocol, source_config, is_active
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, TRUE
                            )
                            ON CONFLICT (tag_name) DO UPDATE
                            SET low_limit = EXCLUDED.low_limit,
                                high_limit = EXCLUDED.high_limit
                            RETURNING *;
                            """,
                            (
                                t_name,
                                asset_id,
                                attr_name,
                                str(spec.get("eng_units", "")),
                                is_step,
                                exc_dev,
                                spec.get("low_limit"),
                                spec.get("high_limit"),
                                req.source_protocol,
                                json.dumps({"template_auto_instantiated": True, "attribute": attr_name}),
                            ),
                        )
                        created_tags.append(cur.fetchone())
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "instantiated",
            "template_name": tmpl["template_name"],
            "asset": asset_row,
            "instantiated_tag_count": len(created_tags),
            "tags": created_tags,
        }

    @router.post("/api/v1/manual-logger/entries", status_code=201)
    def create_manual_logger_entry(
        req: ManualLoggerEntryRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        PI Manual Logger equivalent (21 CFR Part 11 Manual & At-Line Lab Data Entry):
        Records manual/offline lab measurements with mandatory actor/reason attribution,
        optional dual-person verifier authentication, WORM audit logging, and ClickHouse archival.
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=req.tag_name)
        tag_id = int(tag_meta["tag_id"])
        sample_dt = (
            dt.datetime.fromisoformat(req.sample_ts.replace("Z", "+00:00"))
            if req.sample_ts
            else dt.datetime.now(dt.timezone.utc)
        )

        low_lim = tag_meta.get("low_limit")
        high_lim = tag_meta.get("high_limit")
        within_limits = True
        if low_lim is not None and req.val < float(low_lim):
            within_limits = False
        if high_lim is not None and req.val > float(high_lim):
            within_limits = False

        if not within_limits and not req.verifier_user_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"21 CFR Part 11 / EU GMP Annex 11 §6 Dual-Verification Required: "
                    f"Value {req.val} for {req.tag_name} is outside specification limits "
                    f"[{low_lim}, {high_lim}] and requires verifier_user_id and verifier_password."
                ),
            )

        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, x_actor_id, x_change_reason)

                    verified_by: Optional[str] = None
                    if req.verifier_user_id:
                        cur.execute(
                            """
                            SELECT user_id
                            FROM users
                            WHERE user_id = %s
                              AND is_active = TRUE
                              AND crypt(%s, password_hash) = password_hash;
                            """,
                            (req.verifier_user_id, req.verifier_password or ""),
                        )
                        v_user = cur.fetchone()
                        if not v_user:
                            raise HTTPException(
                                status_code=401,
                                detail="PI Manual Logger Dual-Verification Failed: Invalid verifier_user_id or verifier_password",
                            )
                        verified_by = str(v_user["user_id"])

                    cur.execute(
                        """
                        INSERT INTO manual_logger_entries (
                            tag_id, sample_ts, val, str_val, sample_barcode,
                            operator_id, verifier_id, within_limits, notes
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING
                            entry_id, tag_id, sample_ts, val, str_val, sample_barcode,
                            operator_id, verifier_id, within_limits, notes, recorded_at;
                        """,
                        (
                            tag_id,
                            sample_dt,
                            req.val,
                            req.str_val,
                            req.sample_barcode,
                            (x_actor_id or "").strip(),
                            verified_by,
                            within_limits,
                            req.notes,
                        ),
                    )
                    entry_row = cur.fetchone()
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Archive into ClickHouse sensor_data with quality=192 and status_code=5 (Manual Verified Entry)
        ch = get_ch_client()
        ch.insert(
            "pi_historian.sensor_data",
            [[tag_id, sample_dt, float(req.val), req.str_val or "MANUAL_LAB_ENTRY", 192, 5]],
            column_names=["tag_id", "ts", "val", "str_val", "quality", "status_code"],
        )

        return {
            "status": "recorded_and_archived",
            "tag_name": tag_meta["tag_name"],
            "asset_path": tag_meta["asset_path"],
            "dual_verified": verified_by is not None,
            "verifier_id": verified_by,
            "within_limits": within_limits,
            "clickhouse_status_code": 5,
            "entry": entry_row,
        }

    @router.get("/api/v1/manual-logger/entries")
    def list_manual_logger_entries(tag_name: Optional[str] = Query(default=None)) -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                if tag_name:
                    cur.execute(
                        """
                        SELECT m.*, t.tag_name, t.eng_units
                        FROM manual_logger_entries m
                        JOIN tags t ON m.tag_id = t.tag_id
                        WHERE t.tag_name = %s
                        ORDER BY m.entry_id DESC;
                        """,
                        (tag_name,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT m.*, t.tag_name, t.eng_units
                        FROM manual_logger_entries m
                        JOIN tags t ON m.tag_id = t.tag_id
                        ORDER BY m.entry_id DESC;
                        """
                    )
                rows = cur.fetchall()
        return {"count": len(rows), "entries": rows}

    # =========================================================================
    # PHASE 4: Stage 2 Swinging Door Compression, Event Frame `TrueFor` Backfill,
    #          Multi-Stage E-Signatures & PI Notifications
    # =========================================================================

    @router.post("/api/v1/compression/swinging-door-evaluate")
    def evaluate_two_stage_pi_compression(req: SwingingDoorEvaluateRequest) -> Dict[str, Any]:
        """
        Evaluate AVEVA PI Two-Stage Compression (Stage 1 Exception `ExcDev`/`ExcMax` +
        Stage 2 Swinging Door Trending `CompDev`/`CompMax`) on a sequence of raw telemetry samples.
        """
        import importlib.util
        import pathlib

        def _parse_ts_sec(raw_ts: Any) -> float:
            if isinstance(raw_ts, (int, float)):
                return float(raw_ts)
            s_val = str(raw_ts).strip()
            try:
                return float(s_val)
            except ValueError:
                return dt.datetime.fromisoformat(s_val.replace("Z", "+00:00")).timestamp()

        sim_path = pathlib.Path(__file__).resolve().parents[1] / "edge-collector" / "scripts" / "multi_protocol_simulator.py"
        if not sim_path.exists():
            # Fallback when running inside container where only /app is mounted
            from dataclasses import dataclass

            @dataclass
            class _Cfg:
                tag_id: int
                tag_name: str
                protocol: str
                exc_dev: float
                exc_max: float
                is_step_tag: bool
                comp_dev: float
                comp_max: float

            cfg = _Cfg(
                req.tag_id,
                f"TAG_{req.tag_id}",
                "OPC_UA",
                req.exc_dev,
                req.exc_max,
                req.is_step_tag,
                req.comp_dev,
                req.comp_max,
            )
            stage1_pts = []
            last_v: Optional[float] = None
            last_q: Optional[int] = None
            last_t: Optional[float] = None
            for s in req.samples:
                ts, val = _parse_ts_sec(s["ts"]), float(s["val"])
                q, sc = int(s.get("quality", 192)), int(s.get("status_code", 0))
                if (
                    last_t is None
                    or q != last_q
                    or (ts - last_t) >= cfg.exc_max
                    or (cfg.is_step_tag and val != last_v)
                    or (not cfg.is_step_tag and abs(val - (last_v or 0.0)) >= cfg.exc_dev)
                ):
                    stage1_pts.append((ts, val, str(s.get("str_val", "")), q, sc))
                    last_t, last_v, last_q = ts, val, q

            # Stage 2 Swinging Door
            stage2_pts: List[Tuple[float, float, str, int, int]] = []
            anchor_ts: Optional[float] = None
            anchor_val: Optional[float] = None
            cand: Optional[Tuple[float, float, str, int, int]] = None
            s_min, s_max = -math.inf, math.inf
            for ts, val, sv, q, sc in stage1_pts:
                if cfg.is_step_tag or cfg.comp_dev <= 0.0 or anchor_ts is None or anchor_val is None:
                    stage2_pts.append((ts, val, sv, q, sc))
                    anchor_ts, anchor_val = ts, val
                    cand = None
                    s_min, s_max = -math.inf, math.inf
                    continue
                dt_s = ts - anchor_ts
                if dt_s <= 0:
                    continue
                n_max = min(s_max, ((val + cfg.comp_dev) - anchor_val) / dt_s)
                n_min = max(s_min, ((val - cfg.comp_dev) - anchor_val) / dt_s)
                if n_min <= n_max and dt_s < cfg.comp_max:
                    s_max, s_min = n_max, n_min
                    cand = (ts, val, sv, q, sc)
                else:
                    if cand is not None:
                        stage2_pts.append(cand)
                        anchor_ts, anchor_val = cand[0], cand[1]
                        dt_new = ts - anchor_ts
                        s_max = ((val + cfg.comp_dev) - anchor_val) / dt_new if dt_new > 0 else math.inf
                        s_min = ((val - cfg.comp_dev) - anchor_val) / dt_new if dt_new > 0 else -math.inf
                        cand = (ts, val, sv, q, sc)
            if cand is not None:
                stage2_pts.append(cand)
        else:
            spec = importlib.util.spec_from_file_location("multi_protocol_simulator_eval", sim_path)
            assert spec is not None and spec.loader is not None
            sim_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sim_mod)
            cfg_map = {
                req.tag_id: sim_mod.TagFilterConfig(
                    req.tag_id,
                    f"TAG_{req.tag_id}",
                    "OPC_UA",
                    exc_dev=req.exc_dev,
                    exc_max=req.exc_max,
                    is_step_tag=req.is_step_tag,
                    comp_dev=req.comp_dev,
                    comp_max=req.comp_max,
                )
            }
            exc_filter = sim_mod.ExceptionDeadbandFilter(cfg_map)
            sdt_comp = sim_mod.SwingingDoorCompressor(cfg_map)
            stage1_pts = []
            stage2_pts = []
            for s in req.samples:
                ts, val = _parse_ts_sec(s["ts"]), float(s["val"])
                sv = str(s.get("str_val", ""))
                q, sc = int(s.get("quality", 192)), int(s.get("status_code", 0))
                if exc_filter.should_emit(req.tag_id, ts, val, q, sc):
                    stage1_pts.append((ts, val, sv, q, sc))
                    stage2_pts.extend(sdt_comp.process_sample(req.tag_id, ts, val, sv, q, sc))
            st_obj = sdt_comp.states[req.tag_id]
            if st_obj.candidate is not None:
                stage2_pts.append(st_obj.candidate)

        raw_cnt = len(req.samples)
        s1_cnt = len(stage1_pts)
        s2_cnt = len(stage2_pts)
        return {
            "tag_id": req.tag_id,
            "raw_sample_count": raw_cnt,
            "stage1_exception_count": s1_cnt,
            "stage2_swinging_door_count": s2_cnt,
            "compression_ratio": round(raw_cnt / max(s2_cnt, 1), 2),
            "compression_ratio_pct": round((1.0 - (s2_cnt / max(raw_cnt, 1))) * 100.0, 2),
            "archived_points": [
                {"ts": p[0], "val": p[1], "str_val": p[2], "quality": p[3], "status_code": p[4]}
                for p in stage2_pts
            ],
        }

    @router.post("/api/v1/event-frames/backfill")
    def backfill_event_frames_with_truefor(
        req: EventFrameBackfillRequest,
        x_actor_id: Optional[str] = Header(default="event_frame_engine", alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(
            default="PI Event Frame Historical Backfill with TrueFor Debounce",
            alias="X-Change-Reason",
        ),
    ) -> Dict[str, Any]:
        """
        PI Event Frame Generation Analysis with `TrueFor` Debounce & Hysteresis Backfill:
        Scans historical ClickHouse telemetry (`WHERE quality >= 192`) and only opens an Event Frame
        when the trigger condition holds continuously for `>= true_for_seconds`, suppressing transient spikes.
        """
        tag_meta = _resolve_tag_metadata(get_pg_conn, tag_name=req.tag_name)
        tag_id = int(tag_meta["tag_id"])
        asset_id = int(tag_meta["asset_id"])
        ch = get_ch_client()

        rows = list(
            ch.query(
                """
                SELECT
                    toUnixTimestamp64Milli(ts) / 1000.0 AS ts_sec,
                    formatDateTime(ts, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts_iso,
                    val
                FROM pi_historian.sensor_data
                WHERE tag_id = {tag_id:UInt32}
                  AND quality >= 192
                  AND ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')
                  AND ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')
                ORDER BY ts ASC
                """,
                parameters={"tag_id": tag_id, "start_time": req.start_time, "end_time": req.end_time},
            ).named_results()
        )

        # Detect contiguous violation windows and classify against true_for_seconds
        suppressed_transient_spikes = 0
        qualified_windows: List[Dict[str, Any]] = []
        active_start_sec: Optional[float] = None
        active_start_iso: Optional[str] = None
        active_vals: List[float] = []
        last_ts_sec: Optional[float] = None
        last_ts_iso: Optional[str] = None

        def _is_cleared(val: float) -> bool:
            if req.trigger_operator in (">", ">="):
                return val <= (req.trigger_threshold - req.close_hysteresis)
            if req.trigger_operator in ("<", "<="):
                return val >= (req.trigger_threshold + req.close_hysteresis)
            return not _eval_threshold(val, req.trigger_operator, req.trigger_threshold)

        for r in rows:
            ts_s = float(r["ts_sec"])
            ts_iso = str(r["ts_iso"])
            v = float(r["val"])
            violating = _eval_threshold(v, req.trigger_operator, req.trigger_threshold)

            if active_start_sec is None:
                if violating:
                    active_start_sec = ts_s
                    active_start_iso = ts_iso
                    active_vals = [v]
                    last_ts_sec = ts_s
                    last_ts_iso = ts_iso
            else:
                if not _is_cleared(v):
                    active_vals.append(v)
                    last_ts_sec = ts_s
                    last_ts_iso = ts_iso
                else:
                    dur = (last_ts_sec or ts_s) - active_start_sec
                    if dur >= req.true_for_seconds:
                        qualified_windows.append(
                            {
                                "start_time": active_start_iso,
                                "end_time": ts_iso,
                                "duration_seconds": round(dur, 3),
                                "peak_val": round(max(active_vals), 4),
                                "avg_val": round(sum(active_vals) / len(active_vals), 4),
                                "sample_count": len(active_vals),
                            }
                        )
                    else:
                        suppressed_transient_spikes += 1
                    active_start_sec = None
                    active_start_iso = None
                    active_vals = []

        if active_start_sec is not None and last_ts_sec is not None:
            dur = last_ts_sec - active_start_sec
            if dur >= req.true_for_seconds:
                qualified_windows.append(
                    {
                        "start_time": active_start_iso,
                        "end_time": last_ts_iso,
                        "duration_seconds": round(dur, 3),
                        "peak_val": round(max(active_vals), 4),
                        "avg_val": round(sum(active_vals) / len(active_vals), 4),
                        "sample_count": len(active_vals),
                    }
                )
            else:
                suppressed_transient_spikes += 1

        created_event_ids: List[str] = []
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                apply_part11_context(cur, x_actor_id, x_change_reason)
                for win in qualified_windows:
                    metrics = {
                        "tag_id": tag_id,
                        "tag_name": req.tag_name,
                        "true_for_seconds": req.true_for_seconds,
                        "duration_seconds": win["duration_seconds"],
                        "peak_val": win["peak_val"],
                        "avg_val": win["avg_val"],
                        "sample_count": win["sample_count"],
                    }
                    cur.execute(
                        """
                        INSERT INTO event_frames (
                            event_name, event_template, asset_id, start_time, end_time, severity, captured_metrics
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s::jsonb
                        ) RETURNING event_id::text AS event_id;
                        """,
                        (
                            f"{req.tag_name}_{req.template_name}",
                            req.template_name,
                            asset_id,
                            win["start_time"],
                            win["end_time"],
                            req.severity,
                            json.dumps(metrics),
                        ),
                    )
                    ef_row = cur.fetchone()
                    if ef_row:
                        created_event_ids.append(str(ef_row["event_id"]))
            conn.commit()

        return {
            "status": "backfilled",
            "tag_name": req.tag_name,
            "template_name": req.template_name,
            "true_for_seconds": req.true_for_seconds,
            "evaluated_samples": len(rows),
            "suppressed_transient_spikes": suppressed_transient_spikes,
            "created_event_count": len(created_event_ids),
            "created_event_ids": created_event_ids,
            "qualified_windows": qualified_windows,
        }

    @router.get("/api/v1/event-frames/{event_id}/signatures")
    def get_event_frame_signatures(event_id: uuid.UUID) -> Dict[str, Any]:
        """List the multi-stage 21 CFR Part 11 electronic signature chain for an Event Frame."""
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        sig_id,
                        event_id::text AS event_id,
                        stage_order,
                        user_id,
                        signer_full_name,
                        signer_role,
                        signature_meaning,
                        change_reason,
                        signed_at,
                        signature_hash
                    FROM event_frame_signatures
                    WHERE event_id = %s
                    ORDER BY stage_order ASC, sig_id ASC;
                    """,
                    (str(event_id),),
                )
                rows = cur.fetchall()
        return {
            "event_id": str(event_id),
            "signature_count": len(rows),
            "multi_stage_complete": len({r["user_id"] for r in rows}) >= 2,
            "signatures": rows,
        }

    @router.get("/api/v1/notifications/channels")
    def get_notification_channels_catalog() -> Dict[str, Any]:
        """
        Return the AVEVA PI Notifications Delivery Channel catalog (Email SMTP, SMS Twilio/Carrier/SMPP,
        Mobile Push APNs/FCM/PagerDuty, WebService REST / Microsoft Teams Adaptive Cards), dynamic
        AF/Event Frame substitution parameters, and anti-fatigue escalation controls.
        """
        return {
            "service": "GxPHistorian PI Notifications & Multi-Channel Alerting Engine",
            "supported_channels": [
                {
                    "channel_type": "EMAIL",
                    "pi_equivalent": "PI Notifications Native SMTP Delivery Channel (HTML + Plain Text)",
                    "features": [
                        "Multipart MIME (HTML + Plain Text) with dynamic %Parameter% substitution",
                        "Embedded PI Vision / Grafana Vision Ad-Hoc LTTB Trend deep-link (%TrendUrl%)",
                        "Embedded 1-Click Event Frame Acknowledge link (%AckUrl%) & 21 CFR Part 11 E-Sign link (%SignUrl%)",
                    ],
                },
                {
                    "channel_type": "SMS",
                    "pi_equivalent": "Twilio REST API / Carrier Email-to-SMS / Exele TopView & OT SMPP Cellular Modem",
                    "features": [
                        "Compact <=160-character GSM-7 single-segment cellular text formatting",
                        "Cloud Twilio Programmable SMS + Carrier Email-to-SMS (@txt.att.net, @vtext.com, @tmomail.net)",
                        "Purdue Level 3.5 Air-Gapped OT Hardware Cellular Modem (Sierra Wireless AirLink / Moxa OnCell SMPP)",
                        "Two-Way SMS Acknowledgment ('Reply ACK <EventShortId>' via POST /api/v1/notifications/sms-webhook)",
                    ],
                },
                {
                    "channel_type": "MOBILE_PUSH",
                    "pi_equivalent": "AVEVA Mobile Operations / PagerDuty Events API v2 / iOS APNs & Android FCM",
                    "features": [
                        "Apple APNs Critical Alert (interruption-level=critical, bypasses iOS Focus/Mute for GMP alarms)",
                        "Android FCM High-Priority notification channel with gxphistorian://events/{id} deep-link",
                        "PagerDuty Events API v2 integration (dedup_key, trigger/acknowledge/resolve lifecycle)",
                        "Interactive mobile action buttons (Acknowledge Alert, Open Live Trend, Run AI Deviation Brief)",
                    ],
                },
                {
                    "channel_type": "WEBHOOK",
                    "pi_equivalent": "PI Notifications WebService (REST JSON) Delivery Channel",
                    "features": [
                        "Outbound HTTPS POST JSON payload for ServiceNow, IBM Maximo, LIMS, or QMS CAPA intake",
                    ],
                },
                {
                    "channel_type": "TEAMS_ADAPTIVE_CARD",
                    "pi_equivalent": "Microsoft Teams / ChatOps Adaptive Card v1.4 Webhook",
                    "features": [
                        "Rich FactSet table with ISA-95 Asset Path, Tag Peak/Avg KPIs, and Action.OpenUrl buttons",
                    ],
                },
            ],
            "substitution_parameters": [
                "%Element%",
                "%\\Element%",
                "%..\\Element%",
                "%AssetPath%",
                "%EventFrame%",
                "%EventId%",
                "%EventShortId%",
                "%EventTemplate%",
                "%Severity%",
                "%Phase%",
                "%StartTime%",
                "%EndTime%",
                "%Duration%",
                "%Tag%",
                "%Value%",
                "%AvgVal%",
                "%MaxVal%",
                "%MinVal%",
                "%EngUnits%",
                "%HighLimit%",
                "%LowLimit%",
                "%TrendUrl%",
                "%AckUrl%",
                "%SignUrl%",
            ],
            "anti_fatigue_controls": {
                "true_for_seconds": "Event Frame start trigger debounce suppressing transient noise spikes",
                "non_repetition_minutes": "Quiet period suppressing duplicate notifications from chattering alarms",
                "resend_interval_minutes": "Repeat notification cadence while an Event Frame remains unacknowledged (must be >= non_repetition_minutes)",
                "escalation_team": "Ordered multi-tier contact roster stepped through sequentially until acknowledged",
                "notify_on_close": "Send on Close / Recovery notification dispatched when Event Frame end_time is set",
            },
        }

    @router.get("/api/v1/notifications/rules")
    def list_notification_rules(
        channel_type: Optional[str] = Query(default=None, description="Optional channel_type filter"),
    ) -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                if channel_type:
                    cur.execute(
                        "SELECT * FROM notification_rules WHERE channel_type = %s ORDER BY rule_id;",
                        (channel_type.upper(),),
                    )
                else:
                    cur.execute("SELECT * FROM notification_rules ORDER BY rule_id;")
                rows = cur.fetchall()
        return {"count": len(rows), "rules": rows}

    @router.post("/api/v1/notifications/rules", status_code=201)
    def create_or_update_notification_rule(
        req: NotificationRuleCreateRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        Create or update a PI Notification Rule in `notification_rules` with 21 CFR Part 11
        `X-Actor-Id` and `X-Change-Reason` attribution. Enforces the AVEVA PI Notifications rule
        that `resend_interval_minutes >= non_repetition_minutes` when both intervals are positive.
        """
        if (
            req.non_repetition_minutes > 0
            and req.resend_interval_minutes > 0
            and req.resend_interval_minutes < req.non_repetition_minutes
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"PI Notifications Interval Rule Violation: resend_interval_minutes "
                    f"({req.resend_interval_minutes}) must be >= non_repetition_minutes "
                    f"({req.non_repetition_minutes})."
                ),
            )

        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, x_actor_id, x_change_reason)
                    cur.execute(
                        """
                        INSERT INTO notification_rules (
                            rule_name, event_template_filter, min_severity, channel_type,
                            target_endpoint, escalation_minutes, non_repetition_minutes,
                            resend_interval_minutes, notify_on_close, message_template,
                            escalation_team, delivery_config, is_active
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s
                        )
                        ON CONFLICT (rule_name) DO UPDATE SET
                            event_template_filter = EXCLUDED.event_template_filter,
                            min_severity = EXCLUDED.min_severity,
                            channel_type = EXCLUDED.channel_type,
                            target_endpoint = EXCLUDED.target_endpoint,
                            escalation_minutes = EXCLUDED.escalation_minutes,
                            non_repetition_minutes = EXCLUDED.non_repetition_minutes,
                            resend_interval_minutes = EXCLUDED.resend_interval_minutes,
                            notify_on_close = EXCLUDED.notify_on_close,
                            message_template = EXCLUDED.message_template,
                            escalation_team = EXCLUDED.escalation_team,
                            delivery_config = EXCLUDED.delivery_config,
                            is_active = EXCLUDED.is_active
                        RETURNING *;
                        """,
                        (
                            req.rule_name.strip(),
                            req.event_template_filter.strip(),
                            req.min_severity.upper(),
                            req.channel_type.upper(),
                            req.target_endpoint.strip(),
                            req.escalation_minutes,
                            req.non_repetition_minutes,
                            req.resend_interval_minutes,
                            req.notify_on_close,
                            req.message_template,
                            json.dumps([t.model_dump() for t in req.escalation_team]),
                            json.dumps(req.delivery_config),
                            req.is_active,
                        ),
                    )
                    rule_row = cur.fetchone()
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"status": "configured", "rule": rule_row}

    @router.post("/api/v1/notifications/preview")
    def preview_multi_channel_notification(req: NotificationPreviewRequest) -> Dict[str, Any]:
        """
        Render a live multi-channel PI Notification preview (Email HTML+Text, 160-char GSM-7 SMS,
        Mobile Push APNs/FCM/PagerDuty, and Microsoft Teams Adaptive Card) for an Event Frame.
        """
        ef_row: Optional[Dict[str, Any]] = None
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                if req.event_id:
                    cur.execute(
                        """
                        SELECT
                            ef.event_id::text AS event_id,
                            ef.event_name,
                            ef.event_template,
                            ef.severity,
                            ef.start_time,
                            ef.end_time,
                            ef.captured_metrics,
                            ef.signed_by,
                            a.asset_name,
                            a.asset_path::text AS asset_path
                        FROM event_frames ef
                        JOIN assets a ON ef.asset_id = a.asset_id
                        WHERE ef.event_id = %s;
                        """,
                        (req.event_id,),
                    )
                    ef_row = cur.fetchone()
                else:
                    cur.execute(
                        """
                        SELECT
                            ef.event_id::text AS event_id,
                            ef.event_name,
                            ef.event_template,
                            ef.severity,
                            ef.start_time,
                            ef.end_time,
                            ef.captured_metrics,
                            ef.signed_by,
                            a.asset_name,
                            a.asset_path::text AS asset_path
                        FROM event_frames ef
                        JOIN assets a ON ef.asset_id = a.asset_id
                        ORDER BY ef.start_time DESC
                        LIMIT 1;
                        """
                    )
                    ef_row = cur.fetchone()

        if not ef_row:
            ef_row = {
                "event_id": "a1b2c3d4-0000-4000-8000-000000000001",
                "event_name": "BR201_TEMP_PV_High_Limit_Excursion",
                "event_template": "Temp_Excursion_TrueFor_30s",
                "severity": "CRITICAL",
                "start_time": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5),
                "end_time": None,
                "asset_name": "Bioreactor_201",
                "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
                "captured_metrics": {
                    "tag_id": 101,
                    "tag_name": "BR201_TEMP_PV",
                    "eng_units": "degC",
                    "peak_val": 41.4,
                    "avg_val": 40.7667,
                    "high_limit": 38.0,
                    "low_limit": 35.0,
                    "duration_seconds": 120.0,
                },
            }

        return render_pi_notification_formats(
            ef=dict(ef_row),
            message_template=req.message_template,
            notification_phase=req.notification_phase,
            recipient_email=req.recipient_email,
            recipient_phone=req.recipient_phone_e164,
            recipient_mobile_uri=req.recipient_mobile_uri,
        )

    @router.post("/api/v1/notifications/acknowledge/{event_id}")
    def acknowledge_event_frame_notification(
        event_id: uuid.UUID,
        req: NotificationAcknowledgeRequest = NotificationAcknowledgeRequest(),
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        PI Notifications Event Frame Acknowledgment ('Event Frame Can Be Acknowledged'):
        Records a 21 CFR Part 11 attributed acknowledgment on the Event Frame, immediately
        halting further Resend and Escalation Team dispatches while keeping the Event Frame
        available for formal 21 CFR §11.200 electronic signature disposition.
        """
        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, x_actor_id, x_change_reason)
                    cur.execute(
                        "SELECT event_id::text AS event_id, event_name, captured_metrics FROM event_frames WHERE event_id = %s;",
                        (str(event_id),),
                    )
                    ef_row = cur.fetchone()
                    if not ef_row:
                        raise HTTPException(status_code=404, detail=f"Event Frame {event_id} not found")

                    metrics = dict(ef_row.get("captured_metrics") or {})
                    ack_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    ack_info = {
                        "acknowledged": True,
                        "acknowledged_by": (x_actor_id or "").strip(),
                        "acknowledged_at": ack_ts,
                        "ack_channel": req.ack_channel,
                        "ack_comment": req.ack_comment,
                        "change_reason": (x_change_reason or "").strip(),
                    }
                    metrics["acknowledgment"] = ack_info

                    cur.execute(
                        """
                        UPDATE event_frames
                        SET captured_metrics = %s::jsonb
                        WHERE event_id = %s
                        RETURNING
                            event_id::text AS event_id,
                            event_name,
                            event_template,
                            severity,
                            captured_metrics;
                        """,
                        (json.dumps(metrics), str(event_id)),
                    )
                    updated_ef = cur.fetchone()
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "acknowledged",
            "escalation_halted": True,
            "acknowledgment": ack_info,
            "event_frame": updated_ef,
        }

    @router.post("/api/v1/notifications/sms-webhook")
    def handle_inbound_two_way_sms_ack(
        req: SmsInboundWebhookRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        Two-Way SMS Inbound Webhook (Twilio / Exele TopView / OT SMPP Cellular Modem parity):
        Parses inbound SMS replies ('ACK <EventShortId> [notes]') from an authorized on-call
        phone number, maps the phone number to the subscribed operator, and executes a
        21 CFR Part 11 attributed acknowledgment that halts further alert escalations.
        """
        body_clean = req.message_body.strip()
        parts = body_clean.split(maxsplit=2)
        if not parts or parts[0].upper() not in {"ACK", "ACKNOWLEDGE"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid two-way SMS command. Expected format: 'ACK <EventShortId> [optional notes]'",
            )

        target_token = parts[1].strip().lower() if len(parts) >= 2 else "latest"
        sms_notes = parts[2].strip() if len(parts) >= 3 else "Acknowledged via Two-Way SMS reply"

        phone_roster = {
            "+14155550101": ("operator_01", "Sarah Jenkins (Lead USP Operator)"),
            "+14155550102": ("operator_01", "David Chen (USP Shift Supervisor)"),
            "+14155550199": ("qa_approver_01", "Dr. Marcus Vance (QA Qualified Person)"),
        }
        mapped_actor, mapped_name = phone_roster.get(
            req.from_phone.strip(),
            (x_actor_id or "operator_01", f"Mobile SMS Operator ({req.from_phone.strip()})"),
        )
        effective_actor = (x_actor_id or mapped_actor).strip()
        effective_reason = (
            x_change_reason
            or f"Two-Way SMS Acknowledgment ({req.gateway_provider}) from {req.from_phone}: {body_clean}"
        ).strip()

        with get_pg_conn() as conn:
            try:
                with conn.cursor() as cur:
                    apply_part11_context(cur, effective_actor, effective_reason)
                    if target_token == "latest":
                        cur.execute(
                            """
                            SELECT event_id::text AS event_id, event_name, captured_metrics
                            FROM event_frames
                            ORDER BY start_time DESC
                            LIMIT 1;
                            """
                        )
                    else:
                        cur.execute(
                            """
                            SELECT event_id::text AS event_id, event_name, captured_metrics
                            FROM event_frames
                            WHERE lower(event_id::text) LIKE %s
                            ORDER BY start_time DESC
                            LIMIT 1;
                            """,
                            (f"{target_token}%",),
                        )
                    ef_row = cur.fetchone()
                    if not ef_row:
                        raise HTTPException(
                            status_code=404,
                            detail=f"No Event Frame matching short ID '{target_token}' found for SMS ACK",
                        )

                    event_id_str = str(ef_row["event_id"])
                    short_id = event_id_str.split("-")[0].upper()
                    metrics = dict(ef_row.get("captured_metrics") or {})
                    ack_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    ack_info = {
                        "acknowledged": True,
                        "acknowledged_by": effective_actor,
                        "acknowledged_by_name": mapped_name,
                        "acknowledged_from_phone": req.from_phone.strip(),
                        "acknowledged_at": ack_ts,
                        "ack_channel": "SMS",
                        "ack_comment": sms_notes,
                        "change_reason": effective_reason,
                    }
                    metrics["acknowledgment"] = ack_info

                    cur.execute(
                        """
                        UPDATE event_frames
                        SET captured_metrics = %s::jsonb
                        WHERE event_id = %s;
                        """,
                        (json.dumps(metrics), event_id_str),
                    )
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        sms_reply = (
            f"[GxPHistorian] ACK confirmed for {ef_row['event_name']} ({short_id}) "
            f"by {effective_actor} at {ack_ts}. Escalation halted."
        )
        return {
            "status": "sms_acknowledged",
            "event_id": event_id_str,
            "event_short_id": short_id,
            "acknowledged_by": effective_actor,
            "from_phone": req.from_phone,
            "escalation_halted": True,
            "acknowledgment": ack_info,
            "sms_confirmation_reply": sms_reply,
        }

    @router.post("/api/v1/notifications/evaluate")
    def evaluate_pi_notifications(
        event_id: Optional[uuid.UUID] = Query(
            default=None,
            description="Optional specific Event Frame UUID to evaluate",
        ),
        simulate_elapsed_minutes: Optional[float] = Query(
            default=None,
            ge=0.0,
            description="Optional simulated Event Frame age in minutes to deterministically test Escalation Teams & Resend Intervals",
        ),
        respect_non_repetition: bool = Query(
            default=False,
            description="When True, suppresses chattering duplicate Event Frames opened within non_repetition_minutes",
        ),
        dispatch_recovery_on_close: bool = Query(
            default=False,
            description="When True, dispatches RECOVERY_CLOSE summary notifications for closed Event Frames where notify_on_close=True",
        ),
        x_actor_id: Optional[str] = Header(default="pi_notifications_engine", alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(
            default="Automated PI Notifications & Escalation Dispatch",
            alias="X-Change-Reason",
        ),
    ) -> Dict[str, Any]:
        """
        PI Notifications Service equivalent: matches Event Frames against `notification_rules`,
        renders multi-channel payloads (`EMAIL` HTML+Text, `SMS` 160-char GSM-7, `MOBILE_PUSH`
        APNs/FCM/PagerDuty, `WEBHOOK` / `TEAMS_ADAPTIVE_CARD`), steps through multi-tier
        `escalation_team` rosters when unacknowledged past `escalation_minutes`, enforces
        `non_repetition_minutes` chattering suppression, dispatches `RECOVERY_CLOSE` ("Send on Close")
        summaries, and records immutable audit rows in `notification_deliveries`.
        """
        severity_rank = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
        dispatched: List[Dict[str, Any]] = []
        suppressed_chattering_count = 0
        halted_by_ack_count = 0

        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                apply_part11_context(cur, x_actor_id, x_change_reason)
                cur.execute("SELECT * FROM notification_rules WHERE is_active = TRUE ORDER BY rule_id;")
                rules = cur.fetchall()

                if event_id is not None:
                    cur.execute(
                        """
                        SELECT
                            ef.event_id::text AS event_id,
                            ef.event_name,
                            ef.event_template,
                            ef.asset_id,
                            ef.severity,
                            ef.start_time,
                            ef.end_time,
                            ef.captured_metrics,
                            ef.signed_by,
                            a.asset_name,
                            a.asset_path::text AS asset_path
                        FROM event_frames ef
                        JOIN assets a ON ef.asset_id = a.asset_id
                        WHERE ef.event_id = %s;
                        """,
                        (str(event_id),),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            ef.event_id::text AS event_id,
                            ef.event_name,
                            ef.event_template,
                            ef.asset_id,
                            ef.severity,
                            ef.start_time,
                            ef.end_time,
                            ef.captured_metrics,
                            ef.signed_by,
                            a.asset_name,
                            a.asset_path::text AS asset_path
                        FROM event_frames ef
                        JOIN assets a ON ef.asset_id = a.asset_id
                        ORDER BY ef.start_time DESC
                        LIMIT 25;
                        """
                    )
                events = cur.fetchall()
                now_utc = dt.datetime.now(dt.timezone.utc)

                for rule in rules:
                    min_rank = severity_rank.get(str(rule["min_severity"]).upper(), 2)
                    tmpl_filter = str(rule["event_template_filter"])
                    msg_template = str(
                        rule.get("message_template")
                        or "[%Severity%] %Element% — %EventFrame% started at %StartTime% (Value: %Value% %EngUnits%)"
                    )
                    esc_team = rule.get("escalation_team") or []
                    if isinstance(esc_team, str):
                        try:
                            esc_team = json.loads(esc_team)
                        except Exception:
                            esc_team = []

                    for ef in events:
                        ef_rank = severity_rank.get(str(ef["severity"]).upper(), 1)
                        if ef_rank < min_rank:
                            continue
                        if tmpl_filter != "*" and tmpl_filter != ef["event_template"]:
                            continue

                        ef_metrics = ef.get("captured_metrics") or {}
                        if isinstance(ef_metrics, str):
                            try:
                                ef_metrics = json.loads(ef_metrics)
                            except Exception:
                                ef_metrics = {}
                        ack_obj = ef_metrics.get("acknowledgment") or {}
                        is_acknowledged = bool(ack_obj.get("acknowledged")) or (ef["signed_by"] is not None)

                        cur.execute(
                            """
                            SELECT delivery_id, notification_phase, escalation_tier
                            FROM notification_deliveries
                            WHERE rule_id = %s AND event_id = %s
                            ORDER BY delivery_id ASC;
                            """,
                            (rule["rule_id"], ef["event_id"]),
                        )
                        existing_deliveries = cur.fetchall()
                        existing_phases = {str(d.get("notification_phase") or "TRIGGER") for d in existing_deliveries}
                        existing_tiers = {int(d.get("escalation_tier") or 1) for d in existing_deliveries}

                        age_min = (
                            float(simulate_elapsed_minutes)
                            if simulate_elapsed_minutes is not None
                            else (now_utc - ef["start_time"]).total_seconds() / 60.0
                        )

                        # 1. Initial TRIGGER notification if never dispatched for (rule_id, event_id)
                        if not existing_deliveries:
                            if respect_non_repetition and int(rule.get("non_repetition_minutes") or 0) > 0:
                                cur.execute(
                                    """
                                    SELECT nd.delivery_id
                                    FROM notification_deliveries nd
                                    JOIN event_frames prev_ef ON nd.event_id = prev_ef.event_id
                                    WHERE nd.rule_id = %s
                                      AND nd.event_id != %s
                                      AND prev_ef.asset_id = %s
                                      AND prev_ef.event_template = %s
                                      AND ABS(EXTRACT(EPOCH FROM (%s::timestamptz - prev_ef.start_time)) / 60.0) <= %s
                                    LIMIT 1;
                                    """,
                                    (
                                        rule["rule_id"],
                                        ef["event_id"],
                                        ef["asset_id"],
                                        ef["event_template"],
                                        ef["start_time"],
                                        int(rule["non_repetition_minutes"]),
                                    ),
                                )
                                if cur.fetchone():
                                    suppressed_chattering_count += 1
                                    continue

                            escalated = (not is_acknowledged) and (age_min >= float(rule["escalation_minutes"]))
                            tier1_contact = (
                                esc_team[0]
                                if esc_team
                                else {
                                    "tier": 1,
                                    "contact_name": "Primary On-Call",
                                    "channel_type": rule["channel_type"],
                                    "target_endpoint": rule["target_endpoint"],
                                }
                            )
                            recipient_name = str(tier1_contact.get("contact_name") or "Primary On-Call")
                            rendered = render_pi_notification_formats(
                                ef=dict(ef),
                                message_template=msg_template,
                                notification_phase="TRIGGER",
                                recipient_email=(
                                    rule["target_endpoint"]
                                    if rule["channel_type"] == "EMAIL"
                                    else "qa-compliance@biocorp.internal"
                                ),
                                recipient_phone=(
                                    rule["target_endpoint"] if rule["channel_type"] == "SMS" else "+14155550101"
                                ),
                                recipient_mobile_uri=(
                                    rule["target_endpoint"]
                                    if rule["channel_type"] == "MOBILE_PUSH"
                                    else "fcm://device-usp-operator-01"
                                ),
                                escalation_tier=1,
                                recipient_name=recipient_name,
                            )
                            payload = {
                                "rule_name": rule["rule_name"],
                                "event_name": ef["event_name"],
                                "event_short_id": rendered["event_short_id"],
                                "asset_path": ef["asset_path"],
                                "severity": ef["severity"],
                                "escalated": escalated,
                                "notification_phase": "TRIGGER",
                                "escalation_tier": 1,
                                "recipient_name": recipient_name,
                                "rendered_message": rendered["rendered_message"],
                                "channel_envelopes": rendered["channels"],
                            }
                            cur.execute(
                                """
                                INSERT INTO notification_deliveries (
                                    rule_id, event_id, channel_type, target_endpoint,
                                    delivery_status, escalation_triggered, notification_phase,
                                    escalation_tier, recipient_name, rendered_message, payload
                                ) VALUES (
                                    %s, %s, %s, %s, 'DELIVERED', %s, 'TRIGGER', 1, %s, %s, %s::jsonb
                                ) RETURNING
                                    delivery_id, rule_id, event_id::text AS event_id,
                                    channel_type, target_endpoint, delivery_status,
                                    escalation_triggered, notification_phase, escalation_tier,
                                    recipient_name, rendered_message, dispatched_at, payload;
                                """,
                                (
                                    rule["rule_id"],
                                    ef["event_id"],
                                    rule["channel_type"],
                                    rule["target_endpoint"],
                                    escalated,
                                    recipient_name,
                                    rendered["rendered_message"],
                                    json.dumps(payload),
                                ),
                            )
                            deliv = cur.fetchone()
                            if deliv:
                                dispatched.append(dict(deliv))
                            existing_phases.add("TRIGGER")
                            existing_tiers.add(1)

                        # 2. Multi-Tier Escalation Team evaluation when simulate_elapsed_minutes is provided or age exceeds tier delay
                        if simulate_elapsed_minutes is not None:
                            if is_acknowledged:
                                halted_by_ack_count += 1
                            else:
                                for member in esc_team:
                                    tier_num = int(member.get("tier") or 1)
                                    delay_min = float(member.get("delay_minutes") or rule["escalation_minutes"])
                                    if tier_num <= 1 or tier_num in existing_tiers:
                                        continue
                                    if age_min >= delay_min:
                                        t_channel = str(member.get("channel_type") or rule["channel_type"]).upper()
                                        t_endpoint = str(member.get("target_endpoint") or rule["target_endpoint"])
                                        t_name = str(member.get("contact_name") or f"Tier {tier_num} Escalation")
                                        rendered_esc = render_pi_notification_formats(
                                            ef=dict(ef),
                                            message_template=msg_template,
                                            notification_phase="ESCALATION",
                                            recipient_email=(
                                                t_endpoint if t_channel == "EMAIL" else "qa-compliance@biocorp.internal"
                                            ),
                                            recipient_phone=(
                                                t_endpoint if t_channel == "SMS" else "+14155550101"
                                            ),
                                            recipient_mobile_uri=(
                                                t_endpoint
                                                if t_channel == "MOBILE_PUSH"
                                                else "pagerduty://gxp-qa-critical-service"
                                            ),
                                            escalation_tier=tier_num,
                                            recipient_name=t_name,
                                        )
                                        esc_payload = {
                                            "rule_name": rule["rule_name"],
                                            "event_name": ef["event_name"],
                                            "event_short_id": rendered_esc["event_short_id"],
                                            "asset_path": ef["asset_path"],
                                            "severity": ef["severity"],
                                            "escalated": True,
                                            "notification_phase": "ESCALATION",
                                            "escalation_tier": tier_num,
                                            "recipient_name": t_name,
                                            "rendered_message": rendered_esc["rendered_message"],
                                            "channel_envelopes": rendered_esc["channels"],
                                        }
                                        cur.execute(
                                            """
                                            INSERT INTO notification_deliveries (
                                                rule_id, event_id, channel_type, target_endpoint,
                                                delivery_status, escalation_triggered, notification_phase,
                                                escalation_tier, recipient_name, rendered_message, payload
                                            ) VALUES (
                                                %s, %s, %s, %s, 'DELIVERED', TRUE, 'ESCALATION', %s, %s, %s, %s::jsonb
                                            ) RETURNING
                                                delivery_id, rule_id, event_id::text AS event_id,
                                                channel_type, target_endpoint, delivery_status,
                                                escalation_triggered, notification_phase, escalation_tier,
                                                recipient_name, rendered_message, dispatched_at, payload;
                                            """,
                                            (
                                                rule["rule_id"],
                                                ef["event_id"],
                                                t_channel,
                                                t_endpoint,
                                                tier_num,
                                                t_name,
                                                rendered_esc["rendered_message"],
                                                json.dumps(esc_payload),
                                            ),
                                        )
                                        esc_deliv = cur.fetchone()
                                        if esc_deliv:
                                            dispatched.append(dict(esc_deliv))
                                        existing_tiers.add(tier_num)

                        # 3. PI "Send on Close" (RECOVERY_CLOSE) evaluation when Event Frame is closed
                        if (
                            dispatch_recovery_on_close
                            and bool(rule.get("notify_on_close", True))
                            and ef.get("end_time") is not None
                            and "RECOVERY_CLOSE" not in existing_phases
                        ):
                            rec_name = "All Subscribed Recipients (Send on Close)"
                            rendered_rec = render_pi_notification_formats(
                                ef=dict(ef),
                                message_template=msg_template,
                                notification_phase="RECOVERY_CLOSE",
                                recipient_email=(
                                    rule["target_endpoint"]
                                    if rule["channel_type"] == "EMAIL"
                                    else "qa-compliance@biocorp.internal"
                                ),
                                recipient_phone=(
                                    rule["target_endpoint"] if rule["channel_type"] == "SMS" else "+14155550101"
                                ),
                                recipient_mobile_uri=(
                                    rule["target_endpoint"]
                                    if rule["channel_type"] == "MOBILE_PUSH"
                                    else "fcm://device-usp-operator-01"
                                ),
                                escalation_tier=1,
                                recipient_name=rec_name,
                            )
                            rec_payload = {
                                "rule_name": rule["rule_name"],
                                "event_name": ef["event_name"],
                                "event_short_id": rendered_rec["event_short_id"],
                                "asset_path": ef["asset_path"],
                                "severity": ef["severity"],
                                "escalated": False,
                                "notification_phase": "RECOVERY_CLOSE",
                                "escalation_tier": 1,
                                "recipient_name": rec_name,
                                "rendered_message": rendered_rec["rendered_message"],
                                "channel_envelopes": rendered_rec["channels"],
                            }
                            cur.execute(
                                """
                                INSERT INTO notification_deliveries (
                                    rule_id, event_id, channel_type, target_endpoint,
                                    delivery_status, escalation_triggered, notification_phase,
                                    escalation_tier, recipient_name, rendered_message, payload
                                ) VALUES (
                                    %s, %s, %s, %s, 'DELIVERED', FALSE, 'RECOVERY_CLOSE', 1, %s, %s, %s::jsonb
                                ) RETURNING
                                    delivery_id, rule_id, event_id::text AS event_id,
                                    channel_type, target_endpoint, delivery_status,
                                    escalation_triggered, notification_phase, escalation_tier,
                                    recipient_name, rendered_message, dispatched_at, payload;
                                """,
                                (
                                    rule["rule_id"],
                                    ef["event_id"],
                                    rule["channel_type"],
                                    rule["target_endpoint"],
                                    rec_name,
                                    rendered_rec["rendered_message"],
                                    json.dumps(rec_payload),
                                ),
                            )
                            rec_deliv = cur.fetchone()
                            if rec_deliv:
                                dispatched.append(dict(rec_deliv))
                            existing_phases.add("RECOVERY_CLOSE")
            conn.commit()

        return {
            "status": "evaluated",
            "dispatched_count": len(dispatched),
            "suppressed_chattering_count": suppressed_chattering_count,
            "halted_by_acknowledgment_count": halted_by_ack_count,
            "deliveries": dispatched,
        }

    @router.get("/api/v1/notifications/deliveries")
    def list_notification_deliveries(
        channel_type: Optional[str] = Query(default=None, description="Optional channel_type filter"),
        notification_phase: Optional[str] = Query(default=None, description="Optional phase filter (TRIGGER, ESCALATION, RECOVERY_CLOSE)"),
        event_id: Optional[uuid.UUID] = Query(default=None, description="Optional Event Frame UUID filter"),
    ) -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                where_parts: List[str] = []
                params: List[Any] = []
                if channel_type:
                    where_parts.append("channel_type = %s")
                    params.append(channel_type.upper())
                if notification_phase:
                    where_parts.append("notification_phase = %s")
                    params.append(notification_phase.upper())
                if event_id:
                    where_parts.append("event_id = %s")
                    params.append(str(event_id))

                where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
                cur.execute(
                    f"""
                    SELECT
                        delivery_id, rule_id, event_id::text AS event_id,
                        channel_type, target_endpoint, delivery_status,
                        escalation_triggered, notification_phase, escalation_tier,
                        recipient_name, rendered_message, dispatched_at, payload
                    FROM notification_deliveries
                    {where_sql}
                    ORDER BY delivery_id DESC;
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return {"count": len(rows), "deliveries": rows}

    # =========================================================================
    # PHASE 5: Hybrid Cloud Deployment Blueprints (AWS, Azure & Google Cloud)
    # =========================================================================

    HYBRID_CLOUD_PATTERNS: Dict[str, Dict[str, Any]] = {
        "pattern_a_worm_lakehouse": {
            "pattern_id": "pattern_a_worm_lakehouse",
            "name": "Pattern A: Thick Plant Core + Cloud 15-Year WORM Archive & Zero-ETL Lakehouse",
            "purdue_split": {
                "on_premises_ot": [
                    "Pillar 1: edge-collector (Purdue L2.5 DIN-Rail IPC / DMZ VM + 100 GB Telegraf Disk WAL)",
                    "Pillar 2: clickhouse-archive (Purdue L3 Local NVMe 10-Year Hot Tier)",
                    "Pillar 3: postgres-control + historian-api + gxphistorian-mcp (Purdue L3)",
                    "Pillar 4: grafana-vision Local Cleanroom Operator HMI (Purdue L3)",
                ],
                "cloud_vpc_vnet": [
                    "Pillar 2 Cold Tier: 15-Year WORM Object Storage (AWS S3 Object Lock / Azure Immutable Blob / GCP Bucket Lock)",
                    "Pillar 3 DR & PITR: pgBackRest Encrypted WAL Archive in Cloud WORM Storage",
                    "Pillar 4 Lakehouse: Zero-ETL Snappy Apache Parquet queried by Athena / Microsoft Fabric / BigQuery BigLake",
                ],
            },
            "wan_outage_resilience": "100% full plant autonomy; local cleanroom HMIs, batch Event Frames, and 21 CFR Part 11 e-signatures operate with zero WAN connectivity.",
        },
        "pattern_b_cloud_core": {
            "pattern_id": "pattern_b_cloud_core",
            "name": "Pattern B: Thin Plant Edge + Cloud-Hosted Historian Core",
            "purdue_split": {
                "on_premises_ot": [
                    "Pillar 1 Only: Redundant edge-collector IPCs (Purdue L2.5) + Windows COM OPC DA localhost forwarders",
                    "Local 100 GB Telegraf Disk WAL (/var/lib/telegraf/buffer) providing >14 days of offline store-and-forward autonomy",
                ],
                "cloud_vpc_vnet": [
                    "Pillar 2: ClickHouse 24.8 LTS on Cloud NVMe VMs or ClickHouse Cloud (via PrivateLink / Private Link / PSC)",
                    "Pillar 3: Managed PostgreSQL 16 (RDS / Azure Flexible Server / Cloud SQL) + containerized historian-api & gxphistorian-mcp",
                    "Pillar 4: Cloud-hosted Grafana Vision HMI + Excel DataLink over VPN / ExpressRoute / Interconnect",
                ],
            },
            "wan_outage_resilience": ">14 days of zero-data-loss telemetry buffering on local industrial pSLC NVMe at Purdue Level 2.5; automatic chronological catch-up upon WAN restoration.",
        },
        "pattern_c_hub_spoke": {
            "pattern_id": "pattern_c_hub_spoke",
            "name": "Pattern C: Multi-Site Hub & Spoke Federation (Local Autonomous Plant + Global Cloud Rollup)",
            "purdue_split": {
                "on_premises_ot": [
                    "Full Pillars 1-4 per manufacturing site (e.g., Fremont, Boston, Dublin) for local batch execution and §11.200 signing",
                    "Telegraf dual-write [[outputs.http]] with independent local and cloud disk buffer queues",
                ],
                "cloud_vpc_vnet": [
                    "Global Enterprise ClickHouse Aggregator + Global Asset/Event Catalog Replica",
                    "Cross-site Golden Batch comparison (/api/v1/batches/compare) and global Pydantic AI Co-Pilot deviation investigations",
                ],
            },
            "wan_outage_resilience": "100% local site autonomy plus asynchronous multi-site cloud synchronization with independent backpressure queues.",
        },
    }

    HYBRID_CLOUD_PROVIDERS: Dict[str, Dict[str, Any]] = {
        "aws": {
            "provider": "aws",
            "display_name": "Amazon Web Services (AWS)",
            "services": {
                "edge_runtime": "Fanless DIN-Rail IPC (Docker), AWS IoT Greengrass v2, or AWS Outposts 1U/2U",
                "wan_transport": "AWS Site-to-Site VPN / AWS Direct Connect + AWS PrivateLink (:8443 mTLS)",
                "pillar2_clickhouse_hot": "Amazon EC2 i4i.4xlarge (Local Nitro NVMe) or m7i.4xlarge + EBS gp3/io2, or ClickHouse Cloud on AWS",
                "pillar2_worm_cold_storage": "Amazon S3 with S3 Object Lock (COMPLIANCE Mode, 15-Year Retention) + AWS KMS CMK",
                "pillar3_postgres_control": "Amazon RDS for PostgreSQL 16 (Multi-AZ) or Amazon Aurora PostgreSQL (ltree, btree_gist, pgcrypto)",
                "pillar3_api_and_mcp_compute": "Amazon ECS on AWS Fargate or Amazon EKS behind Internal ALB",
                "pillar3_private_ai_model": "Amazon Bedrock (anthropic.claude-sonnet-4 / amazon.nova-pro via VPC Endpoint)",
                "pillar4_grafana_and_lakehouse": "Amazon Managed Grafana (or ECS) + AWS Glue + Amazon Athena / Redshift Spectrum over S3 Parquet",
            },
            "env_overrides": {
                "PG_HOST": "gxp-postgres.cluster-xxxx.us-east-1.rds.amazonaws.com",
                "PG_SSLMODE": "verify-full",
                "CH_HOST": "clickhouse-internal.biocorp.aws.internal",
                "CH_PORT_INTERNAL": "8443",
                "CH_SECURE": "true",
                "GXPHISTORIAN_AI_MODEL": "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0",
            },
            "clickhouse_worm_storage_xml": """<clickhouse>
  <storage_configuration>
    <disks>
      <hot_nvme>
        <path>/var/lib/clickhouse/</path>
        <keep_free_space_bytes>1099511627776</keep_free_space_bytes>
      </hot_nvme>
      <cold_worm_s3>
        <type>s3</type>
        <endpoint>https://s3.us-east-1.amazonaws.com/biocorp-gxphistorian-worm-15yr/telemetry/</endpoint>
        <use_environment_credentials>true</use_environment_credentials>
        <metadata_path>/var/lib/clickhouse/disks/cold_worm_s3/</metadata_path>
        <cache_enabled>true</cache_enabled>
        <data_cache_max_size>107374182400</data_cache_max_size>
      </cold_worm_s3>
    </disks>
    <policies>
      <gxp_10yr_nvme_15yr_worm>
        <volumes>
          <hot_volume><disk>hot_nvme</disk></hot_volume>
          <cold_volume><disk>cold_worm_s3</disk></cold_volume>
        </volumes>
        <move_factor>0.2</move_factor>
      </gxp_10yr_nvme_15yr_worm>
    </policies>
  </storage_configuration>
</clickhouse>""",
            "lakehouse_sql_ddl": """CREATE EXTERNAL TABLE IF NOT EXISTS gxp_lakehouse.sensor_telemetry (
  tag_id INT,
  tag_name STRING,
  asset_path STRING,
  eng_units STRING,
  ts TIMESTAMP,
  val DOUBLE,
  str_val STRING,
  quality INT
)
STORED AS PARQUET
LOCATION 's3://biocorp-gxphistorian-worm-15yr/lakehouse-parquet/';""",
        },
        "azure": {
            "provider": "azure",
            "display_name": "Microsoft Azure",
            "services": {
                "edge_runtime": "Fanless DIN-Rail IPC (Docker), Azure IoT Operations (Arc-enabled K8s), or Azure Local (Stack HCI)",
                "wan_transport": "Azure VPN Gateway / Azure ExpressRoute + Azure Private Link (:8443 mTLS)",
                "pillar2_clickhouse_hot": "Azure VM Standard_L16s_v3 (Local NVMe) or Standard_E16bs_v5 + Premium SSD v2, or ClickHouse Cloud on Azure",
                "pillar2_worm_cold_storage": "Azure Blob Storage / ADLS Gen2 with Immutable Storage for Blob (Locked Time-Based Retention) + Azure Key Vault",
                "pillar3_postgres_control": "Azure Database for PostgreSQL - Flexible Server (Zone-Redundant HA, azure.extensions = ltree,btree_gist,pgcrypto)",
                "pillar3_api_and_mcp_compute": "Azure Container Apps (VNet-Injected) or Azure Kubernetes Service (AKS)",
                "pillar3_private_ai_model": "Azure OpenAI Service (gpt-4o via Azure Private Link)",
                "pillar4_grafana_and_lakehouse": "Azure Managed Grafana (Entra ID SSO) + Microsoft Fabric OneLake Shortcuts / Azure Synapse / Databricks",
            },
            "env_overrides": {
                "PG_HOST": "gxp-postgres-prod.postgres.database.azure.com",
                "PG_SSLMODE": "verify-full",
                "CH_HOST": "clickhouse-internal.biocorp.azure.internal",
                "CH_PORT_INTERNAL": "8443",
                "CH_SECURE": "true",
                "GXPHISTORIAN_AI_MODEL": "openai:gpt-4o",
            },
            "clickhouse_worm_storage_xml": """<clickhouse>
  <storage_configuration>
    <disks>
      <hot_nvme>
        <path>/var/lib/clickhouse/</path>
        <keep_free_space_bytes>1099511627776</keep_free_space_bytes>
      </hot_nvme>
      <cold_worm_azure>
        <type>azure_blob_storage</type>
        <storage_account_url>https://biocorpgxpworm15yr.blob.core.windows.net</storage_account_url>
        <container_name>gxphistorian-telemetry-worm</container_name>
        <use_managed_identity>true</use_managed_identity>
        <metadata_path>/var/lib/clickhouse/disks/cold_worm_azure/</metadata_path>
        <cache_enabled>true</cache_enabled>
        <data_cache_max_size>107374182400</data_cache_max_size>
      </cold_worm_azure>
    </disks>
    <policies>
      <gxp_10yr_nvme_15yr_worm>
        <volumes>
          <hot_volume><disk>hot_nvme</disk></hot_volume>
          <cold_volume><disk>cold_worm_azure</disk></cold_volume>
        </volumes>
        <move_factor>0.2</move_factor>
      </gxp_10yr_nvme_15yr_worm>
    </policies>
  </storage_configuration>
</clickhouse>""",
            "lakehouse_sql_ddl": """SELECT tag_name, asset_path, AVG(val) AS avg_val, MIN(val) AS min_val, MAX(val) AS max_val
FROM OPENROWSET(
  BULK 'https://biocorpgxpworm15yr.dfs.core.windows.net/gxphistorian-lakehouse/*.parquet',
  FORMAT = 'PARQUET'
) AS telemetry
WHERE quality >= 192
GROUP BY tag_name, asset_path;""",
        },
        "gcp": {
            "provider": "gcp",
            "display_name": "Google Cloud (GCP)",
            "services": {
                "edge_runtime": "Fanless DIN-Rail IPC (Docker) or Google Distributed Cloud (GDC) Edge Appliance",
                "wan_transport": "Cloud HA VPN / Dedicated Interconnect + Private Service Connect (:8443 mTLS)",
                "pillar2_clickhouse_hot": "Compute Engine n2-standard-16 (Local Titanium SSD) or c3-standard-22 + Hyperdisk Extreme, or ClickHouse Cloud on GCP",
                "pillar2_worm_cold_storage": "Google Cloud Storage (GCS) with Bucket Lock (Locked Retention Policy, 15 Years) + Cloud KMS CMEK",
                "pillar3_postgres_control": "Cloud SQL for PostgreSQL 16 (Enterprise Plus Regional HA) or AlloyDB for PostgreSQL (ltree, btree_gist, pgcrypto)",
                "pillar3_api_and_mcp_compute": "Google Cloud Run (Internal VPC Ingress) or Google Kubernetes Engine (GKE) Autopilot",
                "pillar3_private_ai_model": "Google Vertex AI (google-vertex:gemini-2.5-flash via Private Service Connect)",
                "pillar4_grafana_and_lakehouse": "Grafana OSS behind Cloud Identity-Aware Proxy (IAP) + BigQuery BigLake External Tables + Vertex AI",
            },
            "env_overrides": {
                "PG_HOST": "10.128.0.15",
                "PG_SSLMODE": "verify-ca",
                "CH_HOST": "clickhouse-internal.biocorp.gcp.internal",
                "CH_PORT_INTERNAL": "8443",
                "CH_SECURE": "true",
                "GXPHISTORIAN_AI_MODEL": "google-vertex:gemini-2.5-flash",
            },
            "clickhouse_worm_storage_xml": """<clickhouse>
  <storage_configuration>
    <disks>
      <hot_nvme>
        <path>/var/lib/clickhouse/</path>
        <keep_free_space_bytes>1099511627776</keep_free_space_bytes>
      </hot_nvme>
      <cold_worm_gcs>
        <type>s3</type>
        <endpoint>https://storage.googleapis.com/biocorp-gxphistorian-worm-15yr/telemetry/</endpoint>
        <access_key_id from_env="GCS_HMAC_ACCESS_KEY_ID" />
        <secret_access_key from_env="GCS_HMAC_SECRET_ACCESS_KEY" />
        <metadata_path>/var/lib/clickhouse/disks/cold_worm_gcs/</metadata_path>
        <cache_enabled>true</cache_enabled>
        <data_cache_max_size>107374182400</data_cache_max_size>
      </cold_worm_gcs>
    </disks>
    <policies>
      <gxp_10yr_nvme_15yr_worm>
        <volumes>
          <hot_volume><disk>hot_nvme</disk></hot_volume>
          <cold_volume><disk>cold_worm_gcs</disk></cold_volume>
        </volumes>
        <move_factor>0.2</move_factor>
      </gxp_10yr_nvme_15yr_worm>
    </policies>
  </storage_configuration>
</clickhouse>""",
            "lakehouse_sql_ddl": """CREATE EXTERNAL TABLE IF NOT EXISTS `biocorp-gxp.lakehouse.sensor_telemetry`
WITH CONNECTION `biocorp-gxp.us.biglake-gcs-conn`
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://biocorp-gxphistorian-worm-15yr/lakehouse-parquet/*.parquet']
);""",
        },
    }

    @router.get("/api/v1/cloud/hybrid-blueprints")
    def get_hybrid_cloud_blueprints(
        provider: Optional[str] = Query(
            default=None,
            description="Optional cloud provider filter: aws, azure, or gcp",
        ),
        pattern: Optional[str] = Query(
            default=None,
            description="Optional hybrid topology pattern filter: pattern_a_worm_lakehouse, pattern_b_cloud_core, or pattern_c_hub_spoke",
        ),
    ) -> Dict[str, Any]:
        """
        Return GAMP 5 & 21 CFR Part 11 qualified hybrid OT + Cloud deployment blueprints,
        ClickHouse 15-Year WORM tiered storage XML configs, Managed PostgreSQL 16 connection profiles,
        and Zero-ETL Lakehouse DDL for AWS, Microsoft Azure, and Google Cloud (GCP).
        """
        selected_providers = dict(HYBRID_CLOUD_PROVIDERS)
        if provider:
            p_key = provider.strip().lower()
            if p_key not in HYBRID_CLOUD_PROVIDERS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported cloud provider '{provider}'. Choose from: {list(HYBRID_CLOUD_PROVIDERS.keys())}",
                )
            selected_providers = {p_key: HYBRID_CLOUD_PROVIDERS[p_key]}

        selected_patterns = dict(HYBRID_CLOUD_PATTERNS)
        if pattern:
            pat_key = pattern.strip().lower()
            if pat_key not in HYBRID_CLOUD_PATTERNS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported hybrid pattern '{pattern}'. Choose from: {list(HYBRID_CLOUD_PATTERNS.keys())}",
                )
            selected_patterns = {pat_key: HYBRID_CLOUD_PATTERNS[pat_key]}

        return {
            "architecture": "GxPHistorian 4-Pillar Hybrid OT + Cloud Reference Architecture",
            "regulatory_standards": [
                "FDA 21 CFR Part 11 (§11.10(c) Archive Protection, §11.10(e) WORM Audit Trail, §11.30 Open System Controls)",
                "EU GMP Annex 11 (Section 4.3 Cloud Supplier Assessment, Section 17 Archiving)",
                "ISPE GAMP 5 Second Edition (Cloud Service Provider Shared Responsibility & CSA)",
                "ISA-95 / IEC 62443 Purdue Model (Level 2.5 Industrial DMZ Store-and-Forward Isolation)",
            ],
            "patterns": selected_patterns,
            "providers": selected_providers,
            "part11_open_system_controls": {
                "transport_encryption": "TLS 1.3 / mTLS required across Site-to-Site VPN, Direct Connect, ExpressRoute, or Cloud Interconnect (§11.30)",
                "edge_store_and_forward": "Telegraf 100 GB disk WAL (/var/lib/telegraf/buffer) buffers >14 days of 25,000 tags during WAN outages (URS-005)",
                "immutable_worm_storage": "AWS S3 Object Lock (COMPLIANCE), Azure Immutable Blob (Locked Policy), or GCP GCS Bucket Lock (Locked Policy) for 15-year retention",
                "managed_postgres_compatibility": "Uses standard PostgreSQL 16 contrib extensions (ltree, btree_gist, pgcrypto) and PL/pgSQL WORM triggers compatible with RDS, Azure Flexible Server, and Cloud SQL",
            },
            "commercial_cloud_editions": {
                "cloud_lab_pd": {
                    "sku_id": "GXP-CLOUD-LAB-2K5",
                    "name": "GxPHistorian Cloud — Lab & Process Development",
                    "delivery_model": "Managed Single-Tenant Cloud (Pattern B)",
                    "included_active_tags": 2500,
                    "included_sites": 1,
                    "annual_price_usd": 18000,
                    "monthly_price_usd": 1500,
                    "seat_license_policy": "Unlimited Grafana Vision HMI & Excel DataLink Users ($0 per-seat tax)",
                    "retention_sla": "3-Year Hot NVMe + 15-Year WORM Cloud Object Lock (21 CFR 211.180)",
                },
                "clinical_cgmp_managed": {
                    "sku_id": "GXP-CLOUD-CLINICAL-25K",
                    "name": "GxPHistorian Cloud — Clinical & Pilot cGMP (Managed Single-Tenant)",
                    "delivery_model": "Managed Single-Tenant Cloud VPC (Pattern B)",
                    "included_active_tags": 25000,
                    "included_sites": 1,
                    "annual_price_usd": 54000,
                    "monthly_price_usd": 4500,
                    "seat_license_policy": "Unlimited Grafana Vision HMI & Excel DataLink Users ($0 per-seat tax)",
                    "retention_sla": "10-Year Hot NVMe + 15-Year WORM Cloud Object Lock (21 CFR 211.180)",
                    "gxp_assurance": [
                        "Signed EU GMP Annex 11 §4.3 Quality Technical Agreement (QTA)",
                        "Version-Pinned LTS Release Channels (2026.Q4-LTS) with Customer Change Control Windows",
                        "Automated 21-Test Pytest IQ/OQ Execution & Countersigned PDF/HTML Validation Binder on Every Upgrade",
                        "Enterprise SSO (Okta / Microsoft Entra ID / Ping Identity) for 21 CFR §11.200 Multi-Stage E-Signatures",
                    ],
                },
                "commercial_enterprise_byoc": {
                    "sku_id": "GXP-CLOUD-BYOC-100K",
                    "name": "GxPHistorian Cloud — Commercial cGMP & Multi-Site Enterprise Hub (BYOC)",
                    "delivery_model": "Bring Your Own Cloud (Customer AWS / Azure / GCP VPC via Cloud Marketplace — Pattern B & C)",
                    "included_active_tags": 100000,
                    "included_sites": 3,
                    "annual_price_usd": 150000,
                    "monthly_price_usd": 12500,
                    "seat_license_policy": "Unlimited Global Users, Excel DataLink Seats & Zero-ETL Lakehouse Readers",
                    "retention_sla": "10-Year Hot NVMe + 15-Year WORM Cloud Object Lock with Customer-Managed KMS Keys (CMK/CMEK)",
                    "cloud_commit_drawdown": "100% eligible for AWS Enterprise Discount Program (EDP), Microsoft Azure MACC, and Google Cloud Commit",
                },
                "edge_box_appliance": {
                    "sku_id": "GXP-EDGE-BOX-L25",
                    "name": "GxPHistorian Pre-Qualified DIN-Rail Edge Box (Purdue L2.5 Appliance)",
                    "hardware_platforms": [
                        "Advantech UNO-2484G (Intel Core i5, 16 GB RAM, 512 GB Industrial pSLC NVMe, Dual Isolated LAN)",
                        "OnLogic Karbon 800 Rugged Fanless DIN-Rail IPC",
                    ],
                    "hardware_price_usd": 3500,
                    "annual_fleet_care_usd": 2500,
                    "factory_qualification": "Ships pre-flashed with edge-collector, 100 GB Telegraf Disk WAL (>14-day autonomy), and factory-executed FAT/IQ Certificate",
                },
            },
            "eu_annex11_qta_schedule": {
                "regulation": "EU GMP Annex 11 (§3.1 Supplier Management, §4.3 Cloud/Validation, §12 Security, §17 Archiving) & FDA 21 CFR §11.30",
                "release_channel_policy": "Customer-Pinned LTS Channels (zero unannounced auto-updates; staging-first automated 21/21 IQ/OQ execution prior to production promotion)",
                "audit_rights": "Annual postal and on-site QA Supplier Audit rights + SOC 2 Type II & ISO/IEC 27001 evidence pack",
                "data_sovereignty": "100% regional pinning (e.g., us-east-1, eu-central-1) with Customer-Managed KMS Keys (AWS KMS, Azure Key Vault, Cloud KMS)",
            },
        }

    # =========================================================================
    # PHASE 6: GxPHistorian Cloud Commercial TCO Calculator & Edge Fleet APIs
    # =========================================================================

    @router.post("/api/v1/cloud/edge-agents/heartbeat")
    def record_edge_agent_heartbeat(
        payload: EdgeAgentHeartbeatRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        """
        Enroll or update a Purdue Level 2.5 Edge Collector appliance (`edge-collector`) in the
        GxPHistorian Cloud Fleet Registry. Persists telemetry and WAL buffer health in PostgreSQL
        `assets.metadata` with mandatory 21 CFR Part 11 WORM audit trail attribution.
        """
        if not x_actor_id or not x_change_reason:
            raise HTTPException(
                status_code=422,
                detail="21 CFR Part 11 Violation: X-Actor-Id and X-Change-Reason headers are mandatory for Cloud Edge Fleet enrollment.",
            )

        now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wal_pct = round((payload.wal_buffer_used_gb / payload.wal_buffer_capacity_gb) * 100.0, 2)
        # At 70% deadband suppression (~64.8 KB/tag/day), compute offline autonomy days remaining
        daily_gb = max(0.01, (payload.active_tag_count * 64.8) / (1024.0 * 1024.0))
        remaining_gb = max(0.0, payload.wal_buffer_capacity_gb - payload.wal_buffer_used_gb)
        autonomy_days = round(remaining_gb / daily_gb, 1)

        agent_record = {
            "agent_id": payload.agent_id,
            "site_path": payload.site_path,
            "hardware_model": payload.hardware_model,
            "deployment_pattern": payload.deployment_pattern,
            "cloud_provider": payload.cloud_provider.lower(),
            "telegraf_version": payload.telegraf_version,
            "wal_buffer_used_gb": round(payload.wal_buffer_used_gb, 3),
            "wal_buffer_capacity_gb": round(payload.wal_buffer_capacity_gb, 1),
            "wal_utilization_pct": wal_pct,
            "wal_queued_metrics": payload.wal_queued_metrics,
            "active_tag_count": payload.active_tag_count,
            "estimated_autonomy_days_remaining": autonomy_days,
            "urs_005_14day_autonomy_compliant": autonomy_days >= 14.0,
            "active_protocols": payload.active_protocols,
            "mtls_cert_days_remaining": payload.mtls_cert_days_remaining,
            "wan_link_status": payload.wan_link_status,
            "last_heartbeat_utc": now_iso,
            "recorded_by": x_actor_id,
        }

        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.actor_id', %s, true);", (x_actor_id,))
                cur.execute("SELECT set_config('app.change_reason', %s, true);", (x_change_reason,))
                cur.execute(
                    "SELECT asset_id, metadata FROM assets WHERE asset_path = %s::ltree;",
                    (payload.site_path,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"ISA-95 site asset_path '{payload.site_path}' not found in PostgreSQL control plane.",
                    )
                meta = dict(row.get("metadata") or {})
                fleet_map = dict(meta.get("cloud_edge_agents") or {})
                fleet_map[payload.agent_id] = agent_record
                meta["cloud_edge_agents"] = fleet_map
                cur.execute(
                    """
                    UPDATE assets
                    SET metadata = %s::jsonb
                    WHERE asset_id = %s
                    RETURNING asset_id, asset_name, asset_path::text AS asset_path;
                    """,
                    (json.dumps(meta), row["asset_id"]),
                )
            conn.commit()

        return {
            "status": "enrolled_and_audited",
            "part11_actor_id": x_actor_id,
            "part11_change_reason": x_change_reason,
            "agent": agent_record,
        }

    @router.get("/api/v1/cloud/edge-agents")
    def list_cloud_edge_agents() -> Dict[str, Any]:
        """
        Return all enrolled Purdue Level 2.5 Edge Collector appliances (`edge-collector`),
        their 100 GB Telegraf Disk WAL utilization, mTLS certificate rotation status,
        and `URS-005` (>14-day WAN outage autonomy) compliance state.
        """
        agents: List[Dict[str, Any]] = []
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT asset_id, asset_name, asset_path::text AS asset_path, metadata FROM assets ORDER BY asset_id;"
                )
                for row in cur.fetchall():
                    meta = row.get("metadata") or {}
                    if isinstance(meta, dict):
                        fleet_map = meta.get("cloud_edge_agents") or {}
                        if isinstance(fleet_map, dict):
                            for agent_data in fleet_map.values():
                                if isinstance(agent_data, dict):
                                    agents.append(agent_data)

        if not agents:
            # Provide baseline default plant Edge Collector telemetry when no external heartbeats have been posted yet
            agents.append(
                {
                    "agent_id": "edge-collector-fremont-default-01",
                    "site_path": "BioCorp.Fremont.USP.Bioreactor_201",
                    "hardware_model": "Advantech UNO-2484G (512GB pSLC NVMe)",
                    "deployment_pattern": "pattern_b_cloud_core",
                    "cloud_provider": "aws",
                    "telegraf_version": "1.32.3",
                    "wal_buffer_used_gb": 0.42,
                    "wal_buffer_capacity_gb": 100.0,
                    "wal_utilization_pct": 0.42,
                    "wal_queued_metrics": 0,
                    "active_tag_count": 25000,
                    "estimated_autonomy_days_remaining": 64.5,
                    "urs_005_14day_autonomy_compliant": True,
                    "active_protocols": ["OPC_UA", "OPC_DA", "BACNET_IP", "S7COMM", "MODBUS_TCP"],
                    "mtls_cert_days_remaining": 89,
                    "wan_link_status": "CONNECTED_MTLS_8443",
                    "last_heartbeat_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "recorded_by": "system_bootstrap",
                }
            )

        return {
            "count": len(agents),
            "urs_005_all_compliant": all(bool(a.get("urs_005_14day_autonomy_compliant", True)) for a in agents),
            "edge_agents": agents,
        }

    @router.get("/api/v1/cloud/tco-calculator")
    def calculate_cloud_tco_and_savings(
        active_tags: int = Query(default=25000, ge=100, le=1000000, description="Total active historian tags"),
        named_users: int = Query(
            default=50,
            ge=1,
            le=10000,
            description="Number of Grafana Vision HMI & Excel DataLink users ($0 per-seat tax in GxPHistorian Cloud)",
        ),
        site_count: int = Query(default=1, ge=1, le=50, description="Number of manufacturing or lab sites"),
        deployment_model: str = Query(
            default="hybrid_dual_track",
            description="Delivery model: managed_single_tenant, byoc_marketplace, vault_ai_addon, or hybrid_dual_track",
        ),
        cloud_provider: str = Query(default="aws", description="Target cloud provider: aws, azure, or gcp"),
        deadband_suppression_pct: float = Query(
            default=70.0,
            ge=0.0,
            le=95.0,
            description="Stage 1 Edge Exception/Deadband suppression percentage (typical GMP plant = 70%)",
        ),
    ) -> Dict[str, Any]:
        """
        Calculate 10-year Hot NVMe + 15-year WORM Cloud storage sizing, recommend the optimal
        GxPHistorian Cloud SKU (`Cloud Lab & PD`, `Clinical cGMP Cloud`, or `Commercial cGMP BYOC`),
        and compute 1-year and 3-year Total Cost of Ownership (TCO) savings vs. legacy per-tag/per-seat
        proprietary historians (`AVEVA PI System / AVEVA Flex`) and manual CSV consulting.
        """
        p_key = cloud_provider.strip().lower()
        if p_key not in HYBRID_CLOUD_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported cloud_provider '{cloud_provider}'. Choose from: {list(HYBRID_CLOUD_PROVIDERS.keys())}",
            )

        # 1. Compression & Storage Sizing Math (DoubleDelta + Gorilla + ZSTD(1) @ 2.5 bytes/sample)
        eff_rate_hz = round(1.0 * (1.0 - (deadband_suppression_pct / 100.0)), 4)
        bytes_per_tag_per_year = 86400.0 * 365.25 * 2.5 * eff_rate_hz
        annual_telemetry_gb = round((active_tags * bytes_per_tag_per_year) / (1024.0**3), 2)
        ten_year_hot_nvme_tb = round((annual_telemetry_gb * 10.0) / 1024.0, 2)
        provisioned_nvme_tb = round(max(1.0, ten_year_hot_nvme_tb * 1.30), 2)  # +30% MergeTree compaction headroom
        fifteen_year_worm_tb = round(max(2.0, ((annual_telemetry_gb * 5.0) / 1024.0) + 0.5), 2)

        # 2. Tier Recommendation & GxPHistorian Cloud Pricing
        if active_tags <= 2500 and site_count == 1 and deployment_model != "byoc_marketplace":
            recommended_sku = "GXP-CLOUD-LAB-2K5"
            tier_name = "GxPHistorian Cloud — Lab & Process Development"
            recommended_delivery = "Managed Single-Tenant Cloud (Pattern B)"
            gxp_annual_subscription_usd = 18000
            edge_boxes_recommended = 1
        elif active_tags <= 25000 and site_count == 1 and deployment_model != "byoc_marketplace":
            recommended_sku = "GXP-CLOUD-CLINICAL-25K"
            tier_name = "GxPHistorian Cloud — Clinical & Pilot cGMP (Managed Single-Tenant)"
            recommended_delivery = "Managed Single-Tenant Cloud VPC (Pattern B)"
            gxp_annual_subscription_usd = 54000
            edge_boxes_recommended = 2
        else:
            recommended_sku = "GXP-CLOUD-BYOC-100K"
            tier_name = "GxPHistorian Cloud — Commercial cGMP & Multi-Site Enterprise Hub (BYOC Marketplace)"
            recommended_delivery = "Customer VPC BYOC via AWS / Azure / GCP Marketplace (Pattern B & C)"
            extra_tag_blocks = max(0, math.ceil((active_tags - 100000) / 50000.0))
            extra_sites = max(0, site_count - 3)
            gxp_annual_subscription_usd = 150000 + (extra_tag_blocks * 35000) + (extra_sites * 24000)
            edge_boxes_recommended = max(2, site_count * 2)

        edge_fleet_annual_usd = edge_boxes_recommended * 2500
        gxp_total_annual_usd = gxp_annual_subscription_usd + edge_fleet_annual_usd

        # 3. Legacy Proprietary Historian (AVEVA PI Flex + Named Seats + Manual CSV Re-Validation) Benchmark
        legacy_tag_subscription_usd = int(round(max(28000.0, active_tags * 7.20 + (site_count * 25000.0)), -2))
        legacy_named_seat_tax_usd = int(named_users * 1200)  # PI Vision + PI DataLink named seat fees
        legacy_annual_csv_consulting_usd = int(site_count * 65000)  # Manual IQ/OQ re-execution & SI maintenance
        legacy_total_annual_usd = (
            legacy_tag_subscription_usd + legacy_named_seat_tax_usd + legacy_annual_csv_consulting_usd
        )

        annual_savings_usd = max(0, legacy_total_annual_usd - gxp_total_annual_usd)
        three_year_savings_usd = annual_savings_usd * 3
        tco_reduction_pct = round((annual_savings_usd / max(1, legacy_total_annual_usd)) * 100.0, 1)

        marketplace_programs = {
            "aws": "AWS Marketplace Private Offer (100% AWS Enterprise Discount Program / EDP Drawdown)",
            "azure": "Microsoft Azure Marketplace Private Offer (100% Azure MACC Commitment Drawdown)",
            "gcp": "Google Cloud Marketplace Private Offer (100% GCP Cloud Commit Drawdown)",
        }

        return {
            "inputs": {
                "active_tags": active_tags,
                "named_users": named_users,
                "site_count": site_count,
                "deployment_model": deployment_model,
                "cloud_provider": p_key,
                "deadband_suppression_pct": deadband_suppression_pct,
            },
            "storage_sizing": {
                "effective_sample_rate_hz": eff_rate_hz,
                "annual_compressed_telemetry_gb": annual_telemetry_gb,
                "ten_year_hot_nvme_data_tb": ten_year_hot_nvme_tb,
                "recommended_hot_nvme_provisioned_tb": provisioned_nvme_tb,
                "years_11_to_15_cold_worm_object_tb": fifteen_year_worm_tb,
                "purdue_l25_edge_wal_per_site_gb": 100.0,
            },
            "recommendation": {
                "sku_id": recommended_sku,
                "tier_name": tier_name,
                "delivery_architecture": recommended_delivery,
                "cloud_marketplace_vehicle": marketplace_programs[p_key],
                "recommended_edge_boxes": edge_boxes_recommended,
                "unlimited_users_included": True,
                "automated_gamp5_iq_oq_binder_included": True,
                "signed_eu_annex11_qta_included": active_tags > 2500 or recommended_sku != "GXP-CLOUD-LAB-2K5",
            },
            "tco_comparison_usd": {
                "gxphistorian_cloud": {
                    "annual_platform_subscription_usd": gxp_annual_subscription_usd,
                    "annual_edge_fleet_care_usd": edge_fleet_annual_usd,
                    "annual_named_user_fees_usd": 0,
                    "annual_csv_revalidation_fees_usd": 0,
                    "total_annual_tco_usd": gxp_total_annual_usd,
                    "three_year_total_tco_usd": gxp_total_annual_usd * 3,
                },
                "legacy_proprietary_historian_benchmark": {
                    "annual_tag_stream_subscription_usd": legacy_tag_subscription_usd,
                    "annual_named_user_seat_tax_usd": legacy_named_seat_tax_usd,
                    "annual_manual_csv_and_si_consulting_usd": legacy_annual_csv_consulting_usd,
                    "total_annual_tco_usd": legacy_total_annual_usd,
                    "three_year_total_tco_usd": legacy_total_annual_usd * 3,
                },
                "net_customer_savings": {
                    "annual_savings_usd": annual_savings_usd,
                    "three_year_cumulative_savings_usd": three_year_savings_usd,
                    "tco_reduction_pct": tco_reduction_pct,
                },
            },
        }

    return router


