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

            # Seed default Notification Rule if empty
            cur.execute("SELECT count(*) AS cnt FROM notification_rules;")
            if int((cur.fetchone() or {}).get("cnt", 0)) == 0:
                cur.execute(
                    """
                    INSERT INTO notification_rules (
                        rule_name, event_template_filter, min_severity, channel_type, target_endpoint, escalation_minutes, is_active
                    ) VALUES
                        ('QA_Critical_Excursion_Webhook', '*', 'CRITICAL', 'WEBHOOK', 'https://qa-alerts.biocorp.internal/api/v1/gxp-incidents', 15, TRUE)
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


class NotificationRuleCreateRequest(BaseModel):
    rule_name: str
    event_template_filter: str = "*"
    min_severity: str = "WARNING"
    channel_type: str = "WEBHOOK"
    target_endpoint: str
    escalation_minutes: int = 15
    is_active: bool = True


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

    @router.get("/api/v1/notifications/rules")
    def list_notification_rules() -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM notification_rules ORDER BY rule_id;")
                rows = cur.fetchall()
        return {"count": len(rows), "rules": rows}

    @router.post("/api/v1/notifications/evaluate")
    def evaluate_pi_notifications(
        x_actor_id: Optional[str] = Header(default="pi_notifications_engine", alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(
            default="Automated PI Notifications & Escalation Dispatch",
            alias="X-Change-Reason",
        ),
    ) -> Dict[str, Any]:
        """
        PI Notifications Service equivalent: matches unsigned/active Event Frames against
        `notification_rules`, flags escalations if unacknowledged past `escalation_minutes`,
        and records immutable delivery audit records in `notification_deliveries`.
        """
        severity_rank = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
        dispatched: List[Dict[str, Any]] = []

        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                apply_part11_context(cur, x_actor_id, x_change_reason)
                cur.execute("SELECT * FROM notification_rules WHERE is_active = TRUE ORDER BY rule_id;")
                rules = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        ef.event_id::text AS event_id,
                        ef.event_name,
                        ef.event_template,
                        ef.severity,
                        ef.start_time,
                        ef.signed_by,
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
                    for ef in events:
                        ef_rank = severity_rank.get(str(ef["severity"]).upper(), 1)
                        if ef_rank < min_rank:
                            continue
                        if tmpl_filter != "*" and tmpl_filter != ef["event_template"]:
                            continue

                        cur.execute(
                            """
                            SELECT delivery_id FROM notification_deliveries
                            WHERE rule_id = %s AND event_id = %s;
                            """,
                            (rule["rule_id"], ef["event_id"]),
                        )
                        if cur.fetchone():
                            continue

                        age_min = (now_utc - ef["start_time"]).total_seconds() / 60.0
                        escalated = (ef["signed_by"] is None) and (age_min >= float(rule["escalation_minutes"]))
                        payload = {
                            "rule_name": rule["rule_name"],
                            "event_name": ef["event_name"],
                            "asset_path": ef["asset_path"],
                            "severity": ef["severity"],
                            "escalated": escalated,
                        }
                        cur.execute(
                            """
                            INSERT INTO notification_deliveries (
                                rule_id, event_id, channel_type, target_endpoint,
                                delivery_status, escalation_triggered, payload
                            ) VALUES (
                                %s, %s, %s, %s, 'DELIVERED', %s, %s::jsonb
                            ) RETURNING
                                delivery_id, rule_id, event_id::text AS event_id,
                                channel_type, target_endpoint, delivery_status,
                                escalation_triggered, dispatched_at, payload;
                            """,
                            (
                                rule["rule_id"],
                                ef["event_id"],
                                rule["channel_type"],
                                rule["target_endpoint"],
                                escalated,
                                json.dumps(payload),
                            ),
                        )
                        deliv = cur.fetchone()
                        if deliv:
                            dispatched.append(dict(deliv))
            conn.commit()

        return {"status": "evaluated", "dispatched_count": len(dispatched), "deliveries": dispatched}

    @router.get("/api/v1/notifications/deliveries")
    def list_notification_deliveries() -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        delivery_id, rule_id, event_id::text AS event_id,
                        channel_type, target_endpoint, delivery_status,
                        escalation_triggered, dispatched_at, payload
                    FROM notification_deliveries
                    ORDER BY delivery_id DESC;
                    """
                )
                rows = cur.fetchall()
        return {"count": len(rows), "deliveries": rows}

    return router
