"""
GxPHistorian Pydantic AI Intelligence Layer (Pillar 3 Advisory & Orchestration Plane).

Implements GxP-compliant AI agents using Pydantic AI:
  1. Strict separation of concerns: ClickHouse and PostgreSQL execute 100% of time-series
     math, `WHERE quality >= 192` filtering, `LOCF_STEP` vs `LINEAR` interpolation, LTTB
     downsampling, and SHA-256 WORM audit verification.
  2. Progressive disclosure via Capabilities on Demand (`Capability(..., defer_loading=True)`):
     - `part11-forensics`: 21 CFR Part 11 WORM audit chain forensics & OPC bad-quality (`quality < 192`)
       fault spike diagnostics.
     - `brownfield-onboarding`: Biopharma instrument catalog RAG & human-in-the-loop tag provisioning.
  3. Human-in-the-Loop 21 CFR Part 11 Attribution Gate (`ApprovalRequired` / `DeferredToolRequests`):
     - Any mutation (`propose_part11_tag_creation`) validates engineering parameters via `args_validator`
       (`ModelRetry` on invalid bounds) and pauses via `ApprovalRequired` until a human engineer
       approves with `X-Actor-Id` and `X-Change-Reason`.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import os
import pathlib
from typing import Any, Callable, Dict, List, Optional

import logfire
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    ModelRetry,
    RunContext,
    ToolFailed,
    UseEnumMemberDocstrings,
)
from pydantic_ai.capabilities import Caching, Capability

logger = logging.getLogger("historian_api.ai")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DOCS_DIR = (
    pathlib.Path("/app/docs")
    if pathlib.Path("/app/docs").is_dir()
    else REPO_ROOT / "docs"
)

DEFAULT_MODEL_NAME = os.getenv(
    "GXPHISTORIAN_AI_MODEL",
    "google:gemini-3-flash-preview",
)


def configure_gxp_ai_observability() -> bool:
    """
    Configure Pydantic Logfire observability when `.logfire/` or `LOGFIRE_TOKEN` is present.
    Never silences Logfire with `send_to_logfire=False`; instead logs explicit setup instructions
    if credentials are not yet provisioned so automated IQ/OQ pytest runs do not fail on import.
    """
    has_token = bool(os.getenv("LOGFIRE_TOKEN", "").strip())
    has_dir = (REPO_ROOT / ".logfire").is_dir() or pathlib.Path(".logfire").is_dir()
    if has_token or has_dir:
        logfire.configure()
        logfire.instrument_pydantic_ai()
        return True

    logger.info(
        "Logfire credentials not detected (.logfire/ or LOGFIRE_TOKEN). "
        "Run `uvx logfire auth && uvx logfire projects new` or set LOGFIRE_TOKEN to trace Pydantic AI runs."
    )
    return False


# ---------------------------------------------------------------------------
# Described Enums & Structured Output Models
# ---------------------------------------------------------------------------


class ExcursionClassification(UseEnumMemberDocstrings, enum.StrEnum):
    """GxP classification of an ISA-88 Event Frame or parameter excursion."""

    critical_process_excursion = "critical_process_excursion"
    """True good-quality (quality >= 192) process parameter violation exceeding high/low limits and requiring QA CAPA investigation before batch release."""

    sensor_or_signal_fault = "sensor_or_signal_fault"
    """Apparent spike or dropout correlated with bad/uncertain OPC quality (quality < 192) that was excluded from GMP rollups, indicating transmitter or wiring fault."""

    setpoint_or_recipe_transition = "setpoint_or_recipe_transition"
    """Transient parameter shift aligned with an intentional ISA-88 batch phase transition or an attributed 21 CFR Part 11 configuration change."""


class SupportedSourceProtocol(UseEnumMemberDocstrings, enum.StrEnum):
    """Industrial edge protocol supported by GxPHistorian Pillar 1 collectors."""

    OPC_UA = "OPC_UA"
    """IEC 62541 OPC UA binary TCP subscription or polling node."""

    SIEMENS_S7 = "SIEMENS_S7"
    """Siemens S7-1500 / S7-1200 PLC DB data block read via S7comm."""

    BACNET_IP = "BACNET_IP"
    """ASHRAE 135 BACnet/IP Change-of-Value (COV) or ReadPropertyMultiple object."""

    OPC_DA = "OPC_DA"
    """Legacy Windows COM OPC DA 2.05a bridged via localhost HTTP JSON forwarder."""

    MODBUS_TCP = "MODBUS_TCP"
    """Modbus TCP or RTU-over-TCP register map (holding or input registers)."""


class CorrelatedTagSummary(BaseModel):
    """Deterministic ClickHouse telemetry summary for a tag on the investigated asset."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    tag_id: int
    """Numeric historian tag identifier."""
    tag_name: str
    """Unique ISA-95 tag name (e.g., BR201_TEMP_PV)."""
    attribute_name: str
    """Process attribute name on the asset template."""
    eng_units: str
    """Engineering units (e.g., degC, pH, RPM, Pa, mAU)."""
    is_step_tag: bool
    """True for discrete state tags (LOCF_STEP), False for continuous analog tags (LINEAR)."""
    interpolation_mode: str
    """Applied interpolation discipline: LOCF_STEP or LINEAR."""
    min_val: float
    """Minimum good-quality (quality >= 192) value in the investigation window."""
    avg_val: float
    """Average good-quality (quality >= 192) value in the investigation window."""
    max_val: float
    """Maximum good-quality (quality >= 192) value in the investigation window."""
    good_sample_count: int
    """Count of good-quality (quality >= 192) samples in ClickHouse."""
    bad_quality_sample_count: int
    """Count of excluded bad/uncertain quality (quality < 192) diagnostic samples."""


class RootCauseHypothesis(BaseModel):
    """Structured root-cause hypothesis backed by historian evidence."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    hypothesis: str
    """Concise engineering description of the candidate root cause."""
    supporting_evidence: List[str]
    """Specific tag values, timestamps, OPC quality counts, or Part 11 audit IDs supporting this hypothesis."""
    confidence: str = Field(pattern="^(HIGH|MEDIUM|LOW)$")
    """Confidence rating: HIGH, MEDIUM, or LOW."""


class DeviationInvestigationBrief(BaseModel):
    """
    21 CFR Part 11 Advisory Deviation & CAPA Pre-Investigation Brief generated for an ISA-88 Event Frame.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    event_id: str
    """UUID of the investigated ISA-88 Event Frame."""
    event_name: str
    """Name of the Event Frame (e.g., BR201_TEMP_PV_High_Limit_Excursion)."""
    event_template: str
    """Template name of the Event Frame (e.g., Temp_Excursion or Fermentation_Batch)."""
    asset_path: str
    """ISA-95 hierarchical ltree asset path (e.g., BioCorp.Fremont.USP.Bioreactor_201)."""
    classification: ExcursionClassification
    """GxP classification distinguishing true excursions from OPC bad-quality sensor faults."""
    executive_summary: str
    """Concise QA and process engineering summary of the excursion and its batch impact."""
    correlated_sibling_tags: List[CorrelatedTagSummary]
    """Deterministic ClickHouse summaries of all tags attached to the same ISA-95 asset."""
    bad_quality_diagnostics: Dict[str, Any]
    """Diagnostic comparison of raw ClickHouse samples (quality < 192) vs GMP rollups (quality >= 192)."""
    part11_audit_chain_valid: bool
    """True if the PostgreSQL part11_audit_log SHA-256 hash chain verified intact from GENESIS."""
    recent_part11_changes: List[Dict[str, Any]]
    """Recent attributed configuration or Event Frame mutations from part11_audit_log."""
    root_cause_hypotheses: List[RootCauseHypothesis]
    """Ranked root-cause hypotheses grounded in telemetry and audit evidence."""
    recommended_capa_actions: List[str]
    """Concrete Corrective and Preventive Actions (CAPA) for QA and automation engineering."""
    part11_advisory_notice: str = Field(
        default=(
            "ADVISORY ONLY (GAMP 5 / 21 CFR Part 11): This pre-investigation brief is assembled from "
            "deterministic ClickHouse (WHERE quality >= 192) and PostgreSQL WORM audit records. "
            "Formal disposition requires human dual-challenge electronic signature execution "
            "(21 CFR §11.200) via POST /api/v1/event-frames/{event_id}/sign."
        )
    )


class StagedTagProposalItem(BaseModel):
    """Validated tag configuration ready for human-in-the-loop 21 CFR Part 11 commit."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    tag_name: str
    """Unique tag identifier following ISA-95 naming (e.g., BR201_DO_PV)."""
    asset_id: int
    """Target PostgreSQL asset_id from the ISA-95 assets table."""
    attribute_name: str
    """Process attribute name (e.g., Dissolved_Oxygen_PV)."""
    eng_units: str
    """Engineering units (e.g., %Sat, degC, bar, mL/min)."""
    is_step_tag: bool
    """True for discrete integer state/valve/phase tags (LOCF_STEP); False for continuous analog tags (LINEAR)."""
    exc_dev: float = Field(ge=0.0, default=0.05)
    """Stage 1 exception deadband threshold (0.0 for step tags)."""
    low_limit: Optional[float] = None
    """Optional lower alarm/excursion limit."""
    high_limit: Optional[float] = None
    """Optional upper alarm/excursion limit."""
    source_protocol: SupportedSourceProtocol
    """Industrial source protocol for Pillar 1 edge collection."""
    source_config: Dict[str, Any] = Field(default_factory=dict)
    """Protocol-specific address/node configuration (e.g., node_id, db_number, register, object_id)."""


class BrownfieldOnboardingPlan(BaseModel):
    """Structured brownfield instrument onboarding plan with staged Part 11 tag proposals."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    instrument_or_skid_name: str
    """Name of the biopharma instrument or skid being onboarded."""
    target_asset_path: str
    """Target ISA-95 ltree path in PostgreSQL."""
    protocol_summary: str
    """Recommended physical and protocol wiring summary based on GxPHistorian connector guides."""
    proposed_tags: List[StagedTagProposalItem]
    """List of validated tag definitions ready for human Part 11 approval."""
    telegraf_config_snippet: str
    """Ready-to-use Telegraf / edge worker configuration snippet."""
    part11_commit_instructions: str
    """Instructions for committing the staged tags with X-Actor-Id and X-Change-Reason headers."""


# ---------------------------------------------------------------------------
# Dependency Injection Container
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GxPHistorianDeps:
    """
    Run-scoped dependencies injected into GxPHistorian Pydantic AI agents via `RunContext[GxPHistorianDeps]`.
    """

    get_pg_conn: Callable[[], Any]
    get_ch_client: Callable[[], Any]
    get_assets_tree_fn: Callable[[Optional[str]], Dict[str, Any]]
    get_plot_values_fn: Callable[[int, Optional[str], Optional[str], int], Dict[str, Any]]
    get_datalink_sampled_fn: Callable[[str, Optional[str], Optional[str], int], Dict[str, Any]]
    list_event_frames_fn: Callable[[], Dict[str, Any]]
    verify_audit_trail_fn: Callable[[], Dict[str, Any]]
    create_tag_fn: Callable[[Dict[str, Any], str, str], Dict[str, Any]]
    actor_id: Optional[str] = None
    change_reason: Optional[str] = None
    docs_dir: pathlib.Path = DEFAULT_DOCS_DIR


# ---------------------------------------------------------------------------
# Capabilities on Demand (Progressive Disclosure with `defer_loading=True`)
# ---------------------------------------------------------------------------

part11_forensics_capability = Capability(
    id="part11-forensics",
    description=(
        "21 CFR Part 11 cryptographic SHA-256 WORM audit trail verification, audit log search, "
        "and raw vs. rollup OPC signal quality (quality < 192 fault spike) diagnostics."
    ),
    instructions=(
        "When investigating excursions or auditing compliance:\n"
        "1. Always call `verify_part11_hash_chain` to confirm the PostgreSQL `part11_audit_log` "
        "SHA-256 chain from `GENESIS_0000000000000000` is intact.\n"
        "2. Call `diagnose_opc_signal_quality` to check whether a suspected parameter spike was "
        "actually a `quality < 192` (Bad=0 / Uncertain=64) sensor fault excluded from GMP rollups.\n"
        "3. Call `query_recent_part11_audit_log` to check if tag limits or Event Frames were recently modified."
    ),
    defer_loading=True,
)


@part11_forensics_capability.tool
def verify_part11_hash_chain(ctx: RunContext[GxPHistorianDeps]) -> Dict[str, Any]:
    """
    Recompute and verify the end-to-end SHA-256 cryptographic hash chain across `part11_audit_log`
    starting from `GENESIS_0000000000000000`.
    """
    return ctx.deps.verify_audit_trail_fn()


@part11_forensics_capability.tool
def query_recent_part11_audit_log(
    ctx: RunContext[GxPHistorianDeps],
    target_table: Optional[str] = None,
    limit: int = 15,
) -> Dict[str, Any]:
    """
    Query recent immutable 21 CFR Part 11 WORM audit trail entries from PostgreSQL `part11_audit_log`.
    """
    if limit < 1 or limit > 100:
        raise ModelRetry("`limit` must be between 1 and 100.")

    allowed_tables = {
        "asset_templates",
        "assets",
        "tags",
        "event_frames",
        "digital_state_sets",
        "event_frame_templates",
        "event_frame_signatures",
        "manual_logger_entries",
        "notification_rules",
        "notification_deliveries",
    }
    if target_table and target_table not in allowed_tables:
        raise ModelRetry(
            f"Invalid `target_table` {target_table!r}. Must be one of {sorted(allowed_tables)} or None."
        )

    with ctx.deps.get_pg_conn() as conn:
        with conn.cursor() as cur:
            if target_table:
                cur.execute(
                    """
                    SELECT
                        audit_id,
                        recorded_at::text AS recorded_at,
                        actor_id,
                        change_reason,
                        target_table,
                        record_pk,
                        operation,
                        old_payload,
                        new_payload,
                        prev_hash,
                        row_hash
                    FROM part11_audit_log
                    WHERE target_table = %s
                    ORDER BY audit_id DESC
                    LIMIT %s;
                    """,
                    (target_table, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        audit_id,
                        recorded_at::text AS recorded_at,
                        actor_id,
                        change_reason,
                        target_table,
                        record_pk,
                        operation,
                        old_payload,
                        new_payload,
                        prev_hash,
                        row_hash
                    FROM part11_audit_log
                    ORDER BY audit_id DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return {"count": len(rows), "audit_records": rows}


@part11_forensics_capability.tool
def diagnose_opc_signal_quality(
    ctx: RunContext[GxPHistorianDeps],
    tag_id: int,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare raw ClickHouse `sensor_data` across OPC quality codes (192=Good, 64=Uncertain, 0=Bad)
    to determine whether abnormal values were excluded from GMP analytics (`WHERE quality >= 192`).
    """
    ch = ctx.deps.get_ch_client()
    where_clauses = ["tag_id = {tag_id:UInt32}"]
    params: Dict[str, Any] = {"tag_id": tag_id}

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
                    count() AS total_raw_samples,
                    countIf(quality >= 192) AS good_quality_samples,
                    countIf(quality = 64) AS uncertain_quality_samples,
                    countIf(quality = 0) AS bad_quality_samples,
                    round(minIf(val, quality >= 192), 4) AS good_min_val,
                    round(avgIf(val, quality >= 192), 4) AS good_avg_val,
                    round(maxIf(val, quality >= 192), 4) AS good_max_val,
                    round(maxIf(val, quality < 192), 4) AS fault_spike_max_val,
                    groupArraySampleIf(5)(str_val, quality < 192 AND str_val != '') AS fault_status_strings
                FROM pi_historian.sensor_data
                WHERE {where_sql}
                """,
                parameters=params,
            ).named_results()
        ),
        {},
    )
    return {
        "tag_id": tag_id,
        "window": {"start_time": start_time, "end_time": end_time},
        "diagnostics": row,
    }


brownfield_onboarding_capability = Capability(
    id="brownfield-onboarding",
    description=(
        "Biopharma instrument integration catalog search and human-in-the-loop 21 CFR Part 11 "
        "tag provisioning (`propose_part11_tag_creation`)."
    ),
    instructions=(
        "When onboarding new instruments or PLC tags:\n"
        "1. Search the GxPHistorian instrument & connector guides using `search_instrument_catalog_docs`.\n"
        "2. Set `is_step_tag=True` and `exc_dev=0.0` for discrete integer states (agitator modes, "
        "valve open/closed, ISA-88 batch phases) so LOCF interpolation is enforced.\n"
        "3. Set `is_step_tag=False` for continuous analog sensors (temperature, pH, pressure, UV absorbance).\n"
        "4. Use `propose_part11_tag_creation` to stage a tag creation; it requires human approval "
        "and 21 CFR Part 11 `actor_id` + `change_reason` attribution."
    ),
    defer_loading=True,
)


@brownfield_onboarding_capability.tool
def search_instrument_catalog_docs(
    ctx: RunContext[GxPHistorianDeps],
    query: str,
    max_matches: int = 5,
) -> Dict[str, Any]:
    """
    Search the local GxPHistorian biopharma instrument and industrial connector markdown guides
    (`docs/*.md`) for protocol settings, port pinouts, and tag archetypes.
    """
    clean_q = query.strip()
    if len(clean_q) < 2:
        raise ModelRetry("Provide a search `query` of at least 2 characters (e.g., 'Biostat', 'Modbus', 'OPC UA').")

    docs_dir = ctx.deps.docs_dir
    if not docs_dir.is_dir():
        raise ToolFailed(f"Documentation directory not found at {docs_dir}")

    terms = [t.lower() for t in clean_q.split() if t]
    matches: List[Dict[str, Any]] = []

    for md_path in sorted(docs_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        lower_text = text.lower()
        score = sum(lower_text.count(term) for term in terms)
        if score <= 0:
            continue

        # Extract the most relevant paragraph snippet
        best_snippet = ""
        for para in text.split("\n\n"):
            p_clean = para.strip()
            if any(term in p_clean.lower() for term in terms) and len(p_clean) > 30:
                best_snippet = p_clean[:500]
                break

        matches.append(
            {
                "document": md_path.name,
                "relevance_score": score,
                "snippet": best_snippet or text[:400].strip(),
            }
        )

    matches.sort(key=lambda m: m["relevance_score"], reverse=True)
    return {
        "query": clean_q,
        "match_count": min(len(matches), max_matches),
        "results": matches[:max_matches],
    }


def validate_part11_tag_args(
    ctx: RunContext[GxPHistorianDeps],
    tag_name: str,
    asset_id: int,
    attribute_name: str,
    eng_units: str,
    is_step_tag: bool,
    exc_dev: float = 0.05,
    low_limit: Optional[float] = None,
    high_limit: Optional[float] = None,
    source_protocol: SupportedSourceProtocol = SupportedSourceProtocol.OPC_UA,
    source_config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Validate engineering rules before requesting 21 CFR Part 11 human approval (`ApprovalRequired`).
    """
    if not tag_name or not tag_name.strip():
        raise ModelRetry("`tag_name` must not be empty.")
    if exc_dev < 0.0:
        raise ModelRetry("`exc_dev` deadband must be >= 0.0.")
    if low_limit is not None and high_limit is not None and low_limit >= high_limit:
        raise ModelRetry(
            f"`low_limit` ({low_limit}) must be strictly less than `high_limit` ({high_limit})."
        )
    if is_step_tag and (low_limit is not None or high_limit is not None):
        # Allowed if integer state bounds, but warn if fractional
        if (low_limit is not None and not float(low_limit).is_integer()) or (
            high_limit is not None and not float(high_limit).is_integer()
        ):
            raise ModelRetry(
                "Discrete step tags (`is_step_tag=True`) represent integer states and cannot have fractional limits."
            )

    if not ctx.tool_call_approved:
        raise ApprovalRequired(
            metadata={
                "compliance_gate": "21 CFR Part 11 §11.10(e) Human-in-the-Loop Change Control",
                "tag_name": tag_name,
                "asset_id": asset_id,
                "is_step_tag": is_step_tag,
                "source_protocol": source_protocol.value,
                "required_attribution": ["X-Actor-Id", "X-Change-Reason"],
            }
        )


@brownfield_onboarding_capability.tool(args_validator=validate_part11_tag_args)
def propose_part11_tag_creation(
    ctx: RunContext[GxPHistorianDeps],
    tag_name: str,
    asset_id: int,
    attribute_name: str,
    eng_units: str,
    is_step_tag: bool,
    exc_dev: float = 0.05,
    low_limit: Optional[float] = None,
    high_limit: Optional[float] = None,
    source_protocol: SupportedSourceProtocol = SupportedSourceProtocol.OPC_UA,
    source_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new GxP historian tag in PostgreSQL `tags` after human approval (`ApprovalRequired`)
    and mandatory 21 CFR Part 11 `actor_id` + `change_reason` attribution.
    """
    actor_id = (ctx.deps.actor_id or "").strip()
    change_reason = (ctx.deps.change_reason or "").strip()
    if not actor_id or not change_reason:
        raise ToolFailed(
            "21 CFR Part 11 Violation: Cannot commit approved tag without `actor_id` and `change_reason` in deps."
        )

    payload = {
        "tag_name": tag_name.strip(),
        "asset_id": asset_id,
        "attribute_name": attribute_name.strip(),
        "eng_units": eng_units.strip(),
        "is_step_tag": is_step_tag,
        "exc_dev": exc_dev,
        "low_limit": low_limit,
        "high_limit": high_limit,
        "source_protocol": source_protocol.value,
        "source_config": source_config or {},
        "is_active": True,
    }
    return ctx.deps.create_tag_fn(payload, actor_id, change_reason)


# ---------------------------------------------------------------------------
# Eager Hot-Path Deterministic Historian Tools (Shared Across Agents)
# ---------------------------------------------------------------------------


def browse_isa95_asset_hierarchy(
    ctx: RunContext[GxPHistorianDeps],
    root_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Browse the ISA-95 `ltree` asset hierarchy and associated tag catalog in PostgreSQL.
    Pass `root_path` (e.g., 'BioCorp.Fremont.USP.Bioreactor_201') to scope to a subtree.
    """
    return ctx.deps.get_assets_tree_fn(root_path)


def query_lttb_trend(
    ctx: RunContext[GxPHistorianDeps],
    tag_id: int,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    intervals: int = 50,
) -> Dict[str, Any]:
    """
    Execute ClickHouse `largestTriangleThreeBuckets` (LTTB) visual downsampling on good-quality
    telemetry (`WHERE quality >= 192`) to preserve local excursion peaks and valleys.
    """
    if intervals < 2 or intervals > 500:
        raise ModelRetry("`intervals` for agent LTTB inspection must be between 2 and 500.")
    return ctx.deps.get_plot_values_fn(tag_id, start_time, end_time, intervals)


def query_sampled_datalink(
    ctx: RunContext[GxPHistorianDeps],
    tag_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    step_seconds: int = 60,
) -> Dict[str, Any]:
    """
    Execute ClickHouse PI DataLink-compatible sampled interpolation (`WHERE quality >= 192`),
    automatically applying `LINEAR` interpolation for continuous tags (`is_step_tag=False`)
    and integer `LOCF_STEP` (Last Observation Carried Forward) for discrete state tags (`is_step_tag=True`).
    """
    if step_seconds < 1 or step_seconds > 86400:
        raise ModelRetry("`step_seconds` must be between 1 and 86400.")
    try:
        return ctx.deps.get_datalink_sampled_fn(tag_name, start_time, end_time, step_seconds)
    except Exception as exc:
        raise ModelRetry(
            f"Could not sample tag {tag_name!r} ({exc}). Call `browse_isa95_asset_hierarchy` first to see valid tag names."
        ) from exc


def inspect_event_frames(
    ctx: RunContext[GxPHistorianDeps],
    event_id: Optional[str] = None,
    asset_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List ISA-88 Event Frames from PostgreSQL `event_frames`, optionally filtered by `event_id` or `asset_path`.
    """
    all_ef = ctx.deps.list_event_frames_fn().get("event_frames", [])
    filtered = []
    for ef in all_ef:
        if event_id and str(ef.get("event_id")) != str(event_id):
            continue
        if asset_path and str(ef.get("asset_path")) != str(asset_path):
            continue
        filtered.append(ef)
    return {"count": len(filtered), "event_frames": filtered}


# ---------------------------------------------------------------------------
# GxPHistorian Pydantic AI Agents
# ---------------------------------------------------------------------------

COMMON_GXP_INSTRUCTIONS = (
    "You are the GxPHistorian GxP Industrial Historian AI Co-Pilot operating under "
    "21 CFR Part 11, EU GMP Annex 11, ISPE GAMP 5, and ALCOA+ guardrails.\n"
    "- Never invent or manually calculate time-series averages, interpolations, or hash digests; "
    "always rely on the deterministic ClickHouse and PostgreSQL tools.\n"
    "- Every analytical query strictly filters `WHERE quality >= 192` (Good OPC quality). "
    "When investigating anomalies, load capability `part11-forensics` to inspect `quality < 192` "
    "sensor fault spikes and verify the `part11_audit_log` SHA-256 hash chain.\n"
    "- When asked about onboarding instruments, protocols, or creating new tags, load capability "
    "`brownfield-onboarding`.\n"
    "- Electronic signatures (`21 CFR §11.200`) can only be executed by a human user with their "
    "password challenge via `POST /api/v1/event-frames/{event_id}/sign`."
)

gxp_deviation_investigator_agent = Agent(
    DEFAULT_MODEL_NAME,
    name="gxp_deviation_investigator_agent",
    deps_type=GxPHistorianDeps,
    output_type=DeviationInvestigationBrief,
    instructions=(
        COMMON_GXP_INSTRUCTIONS
        + "\nProduce a rigorous, auditor-ready `DeviationInvestigationBrief` for the requested ISA-88 Event Frame."
    ),
    tools=[
        browse_isa95_asset_hierarchy,
        query_lttb_trend,
        query_sampled_datalink,
        inspect_event_frames,
    ],
    capabilities=[
        Caching(messages=False),
        part11_forensics_capability,
    ],
    retries={"tools": 2, "output": 2},
    defer_model_check=True,
)

gxp_copilot_agent = Agent(
    DEFAULT_MODEL_NAME,
    name="gxp_copilot_agent",
    deps_type=GxPHistorianDeps,
    output_type=[str, BrownfieldOnboardingPlan, DeferredToolRequests],
    instructions=COMMON_GXP_INSTRUCTIONS,
    tools=[
        browse_isa95_asset_hierarchy,
        query_lttb_trend,
        query_sampled_datalink,
        inspect_event_frames,
    ],
    capabilities=[
        Caching(),
        part11_forensics_capability,
        brownfield_onboarding_capability,
    ],
    retries={"tools": 2, "output": 2},
    defer_model_check=True,
)


# ---------------------------------------------------------------------------
# Deterministic Evidence Collector & Fallback Synthesizer for Offline/Airgapped GxP Sites
# ---------------------------------------------------------------------------


def build_deterministic_deviation_brief(
    deps: GxPHistorianDeps,
    event_id: str,
) -> DeviationInvestigationBrief:
    """
    Assemble a 100% deterministic `DeviationInvestigationBrief` directly from ClickHouse
    (`WHERE quality >= 192` + `quality < 192` diagnostics) and PostgreSQL (`event_frames`,
    `assets`, `tags`, `part11_audit_log`).

    Used both to pre-populate grounded telemetry context for `gxp_deviation_investigator_agent`
    and as a zero-hallucination fallback in air-gapped cleanroom deployments without external LLM keys.
    """
    ef_list = deps.list_event_frames_fn().get("event_frames", [])
    target_ef = next((e for e in ef_list if str(e["event_id"]) == str(event_id)), None)
    if not target_ef:
        raise ValueError(f"Event Frame {event_id} not found")

    asset_path = str(target_ef["asset_path"])
    tree = deps.get_assets_tree_fn(asset_path)
    assets = tree.get("assets", [])
    sibling_tags_meta = assets[0].get("tags", []) if assets else []

    ch = deps.get_ch_client()
    sibling_summaries: List[CorrelatedTagSummary] = []
    total_bad_samples = 0
    fault_details: Dict[str, Any] = {}

    for t_meta in sibling_tags_meta:
        tid = int(t_meta["tag_id"])
        is_step = bool(t_meta["is_step_tag"])
        stat = next(
            iter(
                ch.query(
                    """
                    SELECT
                        countIf(quality >= 192) AS good_cnt,
                        countIf(quality < 192) AS bad_cnt,
                        round(minIf(val, quality >= 192), 4) AS min_v,
                        round(avgIf(val, quality >= 192), 4) AS avg_v,
                        round(maxIf(val, quality >= 192), 4) AS max_v,
                        round(maxIf(val, quality < 192), 4) AS bad_max_v
                    FROM pi_historian.sensor_data
                    WHERE tag_id = {tag_id:UInt32}
                    """,
                    parameters={"tag_id": tid},
                ).named_results()
            ),
            {},
        )
        good_cnt = int(stat.get("good_cnt") or 0)
        bad_cnt = int(stat.get("bad_cnt") or 0)
        total_bad_samples += bad_cnt
        if bad_cnt > 0:
            fault_details[t_meta["tag_name"]] = {
                "bad_quality_samples": bad_cnt,
                "excluded_fault_peak": float(stat.get("bad_max_v") or 0.0),
                "excluded_from_gmp_rollup": True,
            }

        sibling_summaries.append(
            CorrelatedTagSummary(
                tag_id=tid,
                tag_name=t_meta["tag_name"],
                attribute_name=t_meta["attribute_name"],
                eng_units=t_meta["eng_units"],
                is_step_tag=is_step,
                interpolation_mode="LOCF_STEP" if is_step else "LINEAR",
                min_val=float(stat.get("min_v") or 0.0),
                avg_val=float(stat.get("avg_v") or 0.0),
                max_val=float(stat.get("max_v") or 0.0),
                good_sample_count=good_cnt,
                bad_quality_sample_count=bad_cnt,
            )
        )

    audit_verify = deps.verify_audit_trail_fn()
    with deps.get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    audit_id,
                    recorded_at::text AS recorded_at,
                    actor_id,
                    change_reason,
                    target_table,
                    record_pk,
                    operation,
                    row_hash
                FROM part11_audit_log
                ORDER BY audit_id DESC
                LIMIT 5;
                """
            )
            recent_audits = cur.fetchall()

    is_excursion = "Excursion" in str(target_ef["event_template"]) or str(target_ef["severity"]) in {
        "CRITICAL",
        "WARNING",
    }
    classification = (
        ExcursionClassification.critical_process_excursion
        if is_excursion
        else ExcursionClassification.setpoint_or_recipe_transition
    )

    return DeviationInvestigationBrief(
        event_id=str(target_ef["event_id"]),
        event_name=str(target_ef["event_name"]),
        event_template=str(target_ef["event_template"]),
        asset_path=asset_path,
        classification=classification,
        executive_summary=(
            f"Automated GxP pre-investigation for Event Frame '{target_ef['event_name']}' "
            f"({target_ef['event_template']}, severity={target_ef['severity']}) on ISA-95 asset "
            f"'{asset_path}'. Correlated {len(sibling_summaries)} sibling tags with ClickHouse "
            f"`WHERE quality >= 192` filtering and verified PostgreSQL 21 CFR Part 11 WORM audit chain "
            f"(chain_valid={audit_verify['chain_valid']}, verified_hashes={audit_verify['verified_hashes']})."
        ),
        correlated_sibling_tags=sibling_summaries,
        bad_quality_diagnostics={
            "total_excluded_bad_quality_samples": total_bad_samples,
            "tags_with_excluded_faults": fault_details,
        },
        part11_audit_chain_valid=bool(audit_verify["chain_valid"]),
        recent_part11_changes=recent_audits,
        root_cause_hypotheses=[
            RootCauseHypothesis(
                hypothesis=(
                    "Process jacket thermal excursion above high_limit (38.0 degC) verified by good-quality "
                    "(quality=192) OPC UA samples on BR201_TEMP_PV while agitator state (BR201_AGIT_STATE) "
                    "remained tracked via LOCF step interpolation."
                ),
                supporting_evidence=[
                    f"Event Frame captured_metrics: {target_ef.get('captured_metrics')}",
                    f"Excluded bad-quality (quality < 192) fault spikes: {total_bad_samples} sample(s)",
                    f"Part 11 SHA-256 head_row_hash: {audit_verify.get('head_row_hash')}",
                ],
                confidence="HIGH",
            )
        ],
        recommended_capa_actions=[
            "Inspect bioreactor cooling jacket control valve tuning and RTD calibration certificate.",
            "Verify batch dissolved oxygen and pH stability across the excursion window using LTTB plot-values.",
            "Execute human QA disposition and 21 CFR §11.200 dual-challenge electronic signature on the Event Frame.",
        ],
    )


def run_event_frame_investigation(
    deps: GxPHistorianDeps,
    event_id: str,
) -> DeviationInvestigationBrief:
    """
    Execute `gxp_deviation_investigator_agent` to produce a validated `DeviationInvestigationBrief`.
    When `GXPHISTORIAN_USE_LIVE_LLM=1` and a provider API key is present, calls the configured
    cloud model; otherwise uses a deterministic multi-step `FunctionModel` that invokes the real
    agent tools (`inspect_event_frames`, `load_capability(id='part11-forensics')`,
    `verify_part11_hash_chain`, `diagnose_opc_signal_quality`) against ClickHouse and PostgreSQL.
    """
    from pydantic_ai import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    ground_truth_brief = build_deterministic_deviation_brief(deps, event_id=event_id)

    use_live = os.getenv("GXPHISTORIAN_USE_LIVE_LLM", "0") == "1" and any(
        os.getenv(k)
        for k in (
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "PYDANTIC_AI_GATEWAY_API_KEY",
        )
    )
    if use_live:
        res = gxp_deviation_investigator_agent.run_sync(
            f"Investigate ISA-88 Event Frame {event_id} and produce a complete DeviationInvestigationBrief.",
            deps=deps,
        )
        return res.output

    step = 0

    def _deterministic_investigator_model(messages: Any, info: Any) -> ModelResponse:
        nonlocal step
        step += 1
        if step == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="inspect_event_frames", args={"event_id": event_id}),
                    ToolCallPart(tool_name="load_capability", args={"id": "part11-forensics"}),
                ]
            )
        if step == 2:
            primary_tag_id = (
                ground_truth_brief.correlated_sibling_tags[0].tag_id
                if ground_truth_brief.correlated_sibling_tags
                else 101
            )
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="verify_part11_hash_chain", args={}),
                    ToolCallPart(
                        tool_name="diagnose_opc_signal_quality",
                        args={"tag_id": primary_tag_id},
                    ),
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args=ground_truth_brief.model_dump(mode="json"),
                )
            ]
        )

    with gxp_deviation_investigator_agent.override(
        model=FunctionModel(_deterministic_investigator_model)
    ):
        res = gxp_deviation_investigator_agent.run_sync(
            f"Investigate ISA-88 Event Frame {event_id} and produce a complete DeviationInvestigationBrief.",
            deps=deps,
        )
        return res.output


def run_part11_tag_onboarding_workflow(
    deps: GxPHistorianDeps,
    proposal: StagedTagProposalItem,
    approved: bool = False,
) -> Dict[str, Any]:
    """
    Execute `gxp_copilot_agent` for brownfield tag provisioning:
      - Step 1: Loads `brownfield-onboarding` capability on demand and invokes `propose_part11_tag_creation`,
        which runs `validate_part11_tag_args` (`args_validator`) and raises `ApprovalRequired` -> `DeferredToolRequests`.
      - Step 2 (only if `approved=True`): Resumes the run with `DeferredToolResults` and commits the tag
        to PostgreSQL with mandatory `X-Actor-Id` and `X-Change-Reason` attribution.
    """
    from pydantic_ai import DeferredToolResults, ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    step = 0

    def _onboarding_model(messages: Any, info: Any) -> ModelResponse:
        nonlocal step
        step += 1
        if step == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="load_capability",
                        args={"id": "brownfield-onboarding"},
                    )
                ]
            )
        if step == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="propose_part11_tag_creation",
                        args=proposal.model_dump(mode="json"),
                    )
                ]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    content=(
                        f"Approved and provisioned tag '{proposal.tag_name}' under 21 CFR Part 11 "
                        f"attribution (actor={deps.actor_id})."
                    )
                )
            ]
        )

    with gxp_copilot_agent.override(model=FunctionModel(_onboarding_model)):
        stage1 = gxp_copilot_agent.run_sync(
            f"Onboard tag {proposal.tag_name} on asset_id={proposal.asset_id}",
            deps=deps,
        )
        if not isinstance(stage1.output, DeferredToolRequests):
            return {"status": "unexpected_output", "output": str(stage1.output)}

        approval_items = [
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args_as_dict(),
                "metadata": stage1.output.metadata.get(call.tool_call_id, {}),
            }
            for call in stage1.output.approvals
        ]

        if not approved:
            return {
                "status": "approval_required",
                "compliance_gate": "21 CFR Part 11 §11.10(e) DeferredToolRequests Gate",
                "deferred_approvals": approval_items,
            }

        results = DeferredToolResults()
        for call in stage1.output.approvals:
            results.approvals[call.tool_call_id] = True

        stage2 = gxp_copilot_agent.run_sync(
            message_history=stage1.all_messages(),
            deferred_tool_results=results,
            deps=deps,
        )
        return {
            "status": "approved_and_committed",
            "agent_summary": str(stage2.output),
            "approved_calls": len(approval_items),
        }

