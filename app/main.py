"""
GxP Open-Source Industrial Historian Control Plane & Analytics API (Pillar 3).

Provides:
  - ISA-95 Asset Hierarchy Browser (PostgreSQL ltree) & Tag Provisioning
  - 21 CFR Part 11 Mandatory Actor/Reason Context & Hash-Chain Verification
  - PI Vision Replacement: LTTB Visual Downsampling (/api/v1/trends/plot-values)
  - PI DataLink Replacement: Linear vs. LOCF Step Sampled Interpolation (/api/v1/datalink/sampled)
  - ISA-88 Event Frame Engine & 21 CFR Part 11 Electronic Signatures (/api/v1/event-frames/*)
  - PI Integrator Replacement: Apache Parquet Lakehouse Exporter (/api/v1/lakehouse/export-parquet)
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import os
import pathlib
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import clickhouse_connect
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("historian_api")

PG_HOST = os.getenv("PG_HOST", "postgres-control")
PG_PORT = int(os.getenv("PG_PORT_INTERNAL", "5432"))
PG_USER = os.getenv("PG_USER", "historian_admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "GxP_Pg_Secret_2026!")
PG_DB = os.getenv("PG_DB", "pi_control_plane")

CH_HOST = os.getenv("CH_HOST", "clickhouse-archive")
CH_PORT = int(os.getenv("CH_PORT_INTERNAL", "8123"))
CH_USER = os.getenv("CH_USER", "historian_admin")
CH_PASSWORD = os.getenv("CH_PASSWORD", "GxP_Ch_Secret_2026!")
CH_DB = os.getenv("CH_DB", "pi_historian")

ESIG_SECRET_KEY = os.getenv("ESIG_SECRET_KEY", "Part11_Hmac_Key_2026!")
_DEFAULT_EXPORT_DIR = (
    "/app/exports"
    if pathlib.Path("/app").is_dir()
    else str(pathlib.Path(__file__).resolve().parents[1] / "exports")
)
EXPORT_DIR = pathlib.Path(os.getenv("EXPORT_DIR", _DEFAULT_EXPORT_DIR))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def get_pg_conn() -> psycopg.Connection[Dict[str, Any]]:
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB,
        row_factory=dict_row,
        autocommit=False,
    )


def get_ch_client() -> Any:
    return clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USER,
        password=CH_PASSWORD,
        database=CH_DB,
    )


def apply_part11_context(
    cur: psycopg.Cursor[Any],
    actor_id: Optional[str],
    change_reason: Optional[str],
) -> None:
    """Enforce and bind 21 CFR Part 11 session context inside the current PostgreSQL transaction."""
    clean_actor = (actor_id or "").strip()
    clean_reason = (change_reason or "").strip()
    if not clean_actor or not clean_reason:
        raise HTTPException(
            status_code=400,
            detail="21 CFR Part 11 Violation: X-Actor-Id and X-Change-Reason headers are mandatory",
        )
    cur.execute("SELECT set_config('app.actor_id', %s, true);", (clean_actor,))
    cur.execute("SELECT set_config('app.change_reason', %s, true);", (clean_reason,))


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class TagCreateRequest(BaseModel):
    tag_id: Optional[int] = None
    tag_name: str
    asset_id: int
    attribute_name: str
    eng_units: str = ""
    is_step_tag: bool = False
    exc_dev: float = 0.05
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None
    source_protocol: str = "OPC_UA"
    source_config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ElectronicSignatureRequest(BaseModel):
    user_id: str
    password: str
    signature_meaning: str = Field(
        ...,
        examples=["Batch Release Approval", "Excursion Investigation Reviewed"],
    )
    change_reason: str = Field(
        default="21 CFR Part 11 Electronic Signature Execution",
    )


class ParquetExportRequest(BaseModel):
    asset_path: Optional[str] = "BioCorp.Fremont.USP.Bioreactor_201"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    filename_prefix: str = "gxp_telemetry_export"


# ---------------------------------------------------------------------------
# Event Frame Evaluation Engine (ISA-88 Batch & Limit Excursions)
# ---------------------------------------------------------------------------


def evaluate_event_frames_sync(
    actor_id: str = "event_frame_engine",
    change_reason: str = "Automated ISA-88 Event Frame Limit Evaluation",
) -> Dict[str, Any]:
    """
    Scans ClickHouse good-quality telemetry (WHERE quality >= 192) against
    PostgreSQL tag high_limit/low_limit and manages Fermentation_Batch and
    Temp_Excursion Event Frames with captured_metrics summary snapshots.
    """
    ch = get_ch_client()
    opened_events: List[str] = []
    updated_events: List[str] = []
    closed_events: List[str] = []

    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            apply_part11_context(cur, actor_id, change_reason)

            # 1. Ensure an active parent Fermentation_Batch Event Frame exists on Bioreactor_201 (asset_id=1)
            cur.execute(
                """
                SELECT event_id, start_time
                FROM event_frames
                WHERE asset_id = 1
                  AND event_template = 'Fermentation_Batch'
                  AND end_time IS NULL
                ORDER BY start_time DESC
                LIMIT 1;
                """
            )
            batch_row = cur.fetchone()

            batch_stats_q = ch.query(
                """
                SELECT
                    min(ts) AS min_ts,
                    round(avgIf(val, tag_id = 101), 4) AS temp_avg_c,
                    round(maxIf(val, tag_id = 101), 4) AS temp_max_c,
                    round(minIf(val, tag_id = 101), 4) AS temp_min_c,
                    round(avgIf(val, tag_id = 102), 4) AS ph_avg,
                    count() AS good_samples
                FROM pi_historian.sensor_data
                WHERE tag_id IN (101, 102)
                  AND quality >= 192
                  AND ts >= now() - INTERVAL 1 HOUR
                """
            ).named_results()
            batch_stats = next(iter(batch_stats_q), {})
            batch_metrics = {
                "temp_avg_c": float(batch_stats.get("temp_avg_c") or 37.0),
                "temp_max_c": float(batch_stats.get("temp_max_c") or 37.0),
                "temp_min_c": float(batch_stats.get("temp_min_c") or 37.0),
                "ph_avg": float(batch_stats.get("ph_avg") or 7.05),
                "good_samples": int(batch_stats.get("good_samples") or 0),
            }

            if batch_row is None:
                start_dt = batch_stats.get("min_ts") or dt.datetime.now(dt.timezone.utc)
                cur.execute(
                    """
                    INSERT INTO event_frames (
                        event_name, event_template, asset_id, start_time, severity, captured_metrics
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb
                    ) RETURNING event_id;
                    """,
                    (
                        "USP_Batch_2026_BR201_001",
                        "Fermentation_Batch",
                        1,
                        start_dt,
                        "INFO",
                        json.dumps(batch_metrics),
                    ),
                )
                created_batch = cur.fetchone()
                parent_batch_id = str(created_batch["event_id"]) if created_batch else None
                if parent_batch_id:
                    opened_events.append(parent_batch_id)
            else:
                parent_batch_id = str(batch_row["event_id"])
                cur.execute(
                    """
                    UPDATE event_frames
                    SET captured_metrics = %s::jsonb
                    WHERE event_id = %s;
                    """,
                    (json.dumps(batch_metrics), parent_batch_id),
                )
                updated_events.append(parent_batch_id)

            # 2. Evaluate tags with high_limit or low_limit against ClickHouse sensor_data
            cur.execute(
                """
                SELECT tag_id, tag_name, asset_id, eng_units, low_limit, high_limit
                FROM tags
                WHERE is_active = TRUE
                  AND (low_limit IS NOT NULL OR high_limit IS NOT NULL)
                ORDER BY tag_id;
                """
            )
            monitored_tags = cur.fetchall()

            for tag in monitored_tags:
                tag_id = int(tag["tag_id"])
                high_limit = tag["high_limit"]
                low_limit = tag["low_limit"]

                cond_parts: List[str] = []
                if high_limit is not None:
                    cond_parts.append(f"val > {float(high_limit)}")
                if low_limit is not None:
                    cond_parts.append(f"val < {float(low_limit)}")
                excursion_cond = " OR ".join(cond_parts)

                # Check recent excursion window and summary stats in ClickHouse (WHERE quality >= 192)
                summary_rows = list(
                    ch.query(
                        f"""
                        SELECT
                            count() AS total_samples,
                            countIf({excursion_cond}) AS excursion_samples,
                            minIf(ts, {excursion_cond}) AS first_excursion_ts,
                            max(ts) AS latest_ts,
                            argMax(val, ts) AS latest_val,
                            round(avg(val), 4) AS avg_val,
                            round(min(val), 4) AS min_val,
                            round(max(val), 4) AS max_val
                        FROM pi_historian.sensor_data
                        WHERE tag_id = {{tag_id:UInt32}}
                          AND quality >= 192
                          AND ts >= now() - INTERVAL 15 MINUTE
                        """,
                        parameters={"tag_id": tag_id},
                    ).named_results()
                )
                if not summary_rows or int(summary_rows[0]["total_samples"] or 0) == 0:
                    continue

                stat = summary_rows[0]
                excursion_samples = int(stat["excursion_samples"] or 0)
                latest_val = float(stat["latest_val"] or 0.0)
                currently_violating = (
                    (high_limit is not None and latest_val > float(high_limit))
                    or (low_limit is not None and latest_val < float(low_limit))
                )

                captured_snapshot = {
                    "tag_id": tag_id,
                    "tag_name": tag["tag_name"],
                    "eng_units": tag["eng_units"],
                    "avg_val": float(stat["avg_val"] or 0.0),
                    "min_val": float(stat["min_val"] or 0.0),
                    "max_val": float(stat["max_val"] or 0.0),
                    "latest_val": round(latest_val, 4),
                    "high_limit": float(high_limit) if high_limit is not None else None,
                    "low_limit": float(low_limit) if low_limit is not None else None,
                    "excursion_samples": excursion_samples,
                    "total_samples": int(stat["total_samples"] or 0),
                }

                event_tmpl = "Temp_Excursion" if tag_id == 101 else f"Limit_Excursion_{tag['tag_name']}"
                event_title = f"{tag['tag_name']}_High_Limit_Excursion"

                cur.execute(
                    """
                    SELECT event_id, start_time
                    FROM event_frames
                    WHERE asset_id = %s
                      AND event_template = %s
                      AND end_time IS NULL
                    ORDER BY start_time DESC
                    LIMIT 1;
                    """,
                    (tag["asset_id"], event_tmpl),
                )
                open_ef = cur.fetchone()

                if open_ef is None and (currently_violating or excursion_samples > 0):
                    # Check if we already have any event frame for this template; if none or currently violating, open one
                    cur.execute(
                        "SELECT count(*) AS cnt FROM event_frames WHERE event_template = %s;",
                        (event_tmpl,),
                    )
                    existing_cnt = int((cur.fetchone() or {}).get("cnt", 0))
                    if currently_violating or existing_cnt == 0:
                        ef_start = stat["first_excursion_ts"] or stat["latest_ts"] or dt.datetime.now(dt.timezone.utc)
                        ef_end = None if currently_violating else stat["latest_ts"]
                        cur.execute(
                            """
                            INSERT INTO event_frames (
                                parent_event_id, event_name, event_template, asset_id,
                                start_time, end_time, severity, captured_metrics
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                            ) RETURNING event_id;
                            """,
                            (
                                parent_batch_id if tag["asset_id"] == 1 else None,
                                event_title,
                                event_tmpl,
                                tag["asset_id"],
                                ef_start,
                                ef_end,
                                "CRITICAL" if tag_id == 101 else "WARNING",
                                json.dumps(captured_snapshot),
                            ),
                        )
                        new_ef = cur.fetchone()
                        if new_ef:
                            opened_events.append(str(new_ef["event_id"]))
                elif open_ef is not None:
                    ef_id = str(open_ef["event_id"])
                    if not currently_violating:
                        cur.execute(
                            """
                            UPDATE event_frames
                            SET end_time = %s,
                                captured_metrics = %s::jsonb
                            WHERE event_id = %s;
                            """,
                            (stat["latest_ts"], json.dumps(captured_snapshot), ef_id),
                        )
                        closed_events.append(ef_id)
                    else:
                        cur.execute(
                            """
                            UPDATE event_frames
                            SET captured_metrics = %s::jsonb
                            WHERE event_id = %s;
                            """,
                            (json.dumps(captured_snapshot), ef_id),
                        )
                        updated_events.append(ef_id)

        conn.commit()

    return {
        "status": "evaluated",
        "opened_event_ids": opened_events,
        "updated_event_ids": updated_events,
        "closed_event_ids": closed_events,
    }


async def _periodic_event_frame_worker() -> None:
    while True:
        try:
            await asyncio.to_thread(evaluate_event_frames_sync)
        except Exception as exc:
            logger.warning("Background Event Frame evaluation cycle warning: %s", exc)
        await asyncio.sleep(5.0)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_periodic_event_frame_worker())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="GxP Industrial Historian Control Plane & DataLink API",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# 1. Health Endpoint
# ---------------------------------------------------------------------------


@app.get("/api/v1/health")
def health_check() -> Dict[str, Any]:
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS pg_version, count(*) AS tag_count FROM tags;")
                pg_info = cur.fetchone() or {}

        ch = get_ch_client()
        ch_version = ch.command("SELECT version()")
        ch_rows = ch.command("SELECT count() FROM pi_historian.sensor_data")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dependency healthcheck failed: {exc}") from exc

    return {
        "status": "healthy",
        "postgres": {
            "connected": True,
            "database": PG_DB,
            "tag_count": int(pg_info.get("tag_count", 0)),
        },
        "clickhouse": {
            "connected": True,
            "database": CH_DB,
            "version": str(ch_version),
            "sensor_data_rows": int(ch_rows or 0),
        },
    }


# ---------------------------------------------------------------------------
# 2. Asset Hierarchy Browser (ltree) & Tag Provisioning (Part 11 Enforced)
# ---------------------------------------------------------------------------


@app.get("/api/v1/assets/tree")
def get_assets_tree(
    root_path: Optional[str] = Query(default=None, description="Optional ltree root path filter"),
) -> Dict[str, Any]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            if root_path:
                cur.execute(
                    """
                    SELECT
                        a.asset_id,
                        a.asset_name,
                        a.asset_path::text AS asset_path,
                        nlevel(a.asset_path) AS depth,
                        t.template_name,
                        a.metadata,
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'tag_id', tg.tag_id,
                                    'tag_name', tg.tag_name,
                                    'attribute_name', tg.attribute_name,
                                    'eng_units', tg.eng_units,
                                    'is_step_tag', tg.is_step_tag,
                                    'low_limit', tg.low_limit,
                                    'high_limit', tg.high_limit,
                                    'source_protocol', tg.source_protocol
                                ) ORDER BY tg.tag_id
                            ) FILTER (WHERE tg.tag_id IS NOT NULL),
                            '[]'::json
                        ) AS tags
                    FROM assets a
                    LEFT JOIN asset_templates t ON a.template_id = t.template_id
                    LEFT JOIN tags tg ON tg.asset_id = a.asset_id
                    WHERE a.asset_path <@ %s::ltree
                    GROUP BY a.asset_id, a.asset_name, a.asset_path, t.template_name, a.metadata
                    ORDER BY a.asset_path;
                    """,
                    (root_path,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        a.asset_id,
                        a.asset_name,
                        a.asset_path::text AS asset_path,
                        nlevel(a.asset_path) AS depth,
                        t.template_name,
                        a.metadata,
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'tag_id', tg.tag_id,
                                    'tag_name', tg.tag_name,
                                    'attribute_name', tg.attribute_name,
                                    'eng_units', tg.eng_units,
                                    'is_step_tag', tg.is_step_tag,
                                    'low_limit', tg.low_limit,
                                    'high_limit', tg.high_limit,
                                    'source_protocol', tg.source_protocol
                                ) ORDER BY tg.tag_id
                            ) FILTER (WHERE tg.tag_id IS NOT NULL),
                            '[]'::json
                        ) AS tags
                    FROM assets a
                    LEFT JOIN asset_templates t ON a.template_id = t.template_id
                    LEFT JOIN tags tg ON tg.asset_id = a.asset_id
                    GROUP BY a.asset_id, a.asset_name, a.asset_path, t.template_name, a.metadata
                    ORDER BY a.asset_path;
                    """
                )
            assets = cur.fetchall()

    return {"count": len(assets), "assets": assets}


@app.post("/api/v1/tags", status_code=201)
def create_tag(
    payload: TagCreateRequest,
    x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
    x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
) -> Dict[str, Any]:
    with get_pg_conn() as conn:
        try:
            with conn.cursor() as cur:
                apply_part11_context(cur, x_actor_id, x_change_reason)
                if payload.tag_id is not None:
                    cur.execute(
                        """
                        INSERT INTO tags (
                            tag_id, tag_name, asset_id, attribute_name, eng_units,
                            is_step_tag, exc_dev, low_limit, high_limit,
                            source_protocol, source_config, is_active
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                        )
                        RETURNING *;
                        """,
                        (
                            payload.tag_id,
                            payload.tag_name,
                            payload.asset_id,
                            payload.attribute_name,
                            payload.eng_units,
                            payload.is_step_tag,
                            payload.exc_dev,
                            payload.low_limit,
                            payload.high_limit,
                            payload.source_protocol,
                            json.dumps(payload.source_config),
                            payload.is_active,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO tags (
                            tag_name, asset_id, attribute_name, eng_units,
                            is_step_tag, exc_dev, low_limit, high_limit,
                            source_protocol, source_config, is_active
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                        )
                        RETURNING *;
                        """,
                        (
                            payload.tag_name,
                            payload.asset_id,
                            payload.attribute_name,
                            payload.eng_units,
                            payload.is_step_tag,
                            payload.exc_dev,
                            payload.low_limit,
                            payload.high_limit,
                            payload.source_protocol,
                            json.dumps(payload.source_config),
                            payload.is_active,
                        ),
                    )
                created = cur.fetchone()
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "created", "tag": created}


# ---------------------------------------------------------------------------
# 3. PI Vision PlotValues Replacement: ClickHouse LTTB Downsampling
# ---------------------------------------------------------------------------


@app.get("/api/v1/trends/plot-values")
def get_plot_values(
    tag_id: int = Query(..., description="Historian Tag ID"),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp"),
    intervals: int = Query(default=500, ge=2, le=10000, description="Target LTTB buckets"),
) -> Dict[str, Any]:
    ch = get_ch_client()

    where_clauses = ["tag_id = {tag_id:UInt32}", "quality >= 192"]
    params: Dict[str, Any] = {"tag_id": tag_id}

    if start_time:
        where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
        params["start_time"] = start_time
    if end_time:
        where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
        params["end_time"] = end_time

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
        toUInt32({tag_id}) AS tag_id,
        dictGet('pi_historian.pg_asset_tags', 'tag_name', toUInt64({tag_id})) AS tag_name,
        dictGet('pi_historian.pg_asset_tags', 'asset_name', toUInt64({tag_id})) AS asset_name,
        dictGet('pi_historian.pg_asset_tags', 'asset_path', toUInt64({tag_id})) AS asset_path,
        dictGet('pi_historian.pg_asset_tags', 'attribute_name', toUInt64({tag_id})) AS attribute_name,
        dictGet('pi_historian.pg_asset_tags', 'eng_units', toUInt64({tag_id})) AS eng_units,
        dictGet('pi_historian.pg_asset_tags', 'low_limit', toUInt64({tag_id})) AS low_limit,
        dictGet('pi_historian.pg_asset_tags', 'high_limit', toUInt64({tag_id})) AS high_limit,
        formatDateTime(pt.1, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS ts,
        round(pt.2, 4) AS val
    FROM (
        SELECT arrayJoin(largestTriangleThreeBuckets({int(intervals)})(ts, val)) AS pt
        FROM pi_historian.sensor_data
        WHERE {where_sql}
    )
    ORDER BY pt.1 ASC
    """

    rows = list(ch.query(query, parameters=params).named_results())

    meta_row = next(
        iter(
            ch.query(
                """
                SELECT
                    dictGet('pi_historian.pg_asset_tags', 'tag_name', toUInt64({tag_id:UInt64})) AS tag_name,
                    dictGet('pi_historian.pg_asset_tags', 'asset_name', toUInt64({tag_id:UInt64})) AS asset_name,
                    dictGet('pi_historian.pg_asset_tags', 'asset_path', toUInt64({tag_id:UInt64})) AS asset_path,
                    dictGet('pi_historian.pg_asset_tags', 'attribute_name', toUInt64({tag_id:UInt64})) AS attribute_name,
                    dictGet('pi_historian.pg_asset_tags', 'eng_units', toUInt64({tag_id:UInt64})) AS eng_units,
                    dictGet('pi_historian.pg_asset_tags', 'low_limit', toUInt64({tag_id:UInt64})) AS low_limit,
                    dictGet('pi_historian.pg_asset_tags', 'high_limit', toUInt64({tag_id:UInt64})) AS high_limit
                """,
                parameters={"tag_id": tag_id},
            ).named_results()
        ),
        {},
    )

    return {
        "tag_id": tag_id,
        "tag_name": meta_row.get("tag_name", ""),
        "asset_name": meta_row.get("asset_name", ""),
        "asset_path": meta_row.get("asset_path", ""),
        "attribute_name": meta_row.get("attribute_name", ""),
        "eng_units": meta_row.get("eng_units", ""),
        "low_limit": meta_row.get("low_limit"),
        "high_limit": meta_row.get("high_limit"),
        "downsampling_algorithm": "largestTriangleThreeBuckets",
        "requested_intervals": intervals,
        "point_count": len(rows),
        "points": [{"ts": r["ts"], "val": r["val"]} for r in rows],
    }


# ---------------------------------------------------------------------------
# 4. PI DataLink PISampDat Replacement: Linear vs. LOCF Step Interpolation
# ---------------------------------------------------------------------------


@app.get("/api/v1/datalink/sampled", response_model=None)
def get_datalink_sampled(
    tag_name: str = Query(..., description="Tag Name (e.g., BR201_TEMP_PV or BR201_AGIT_STATE)"),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp"),
    step_seconds: int = Query(default=5, ge=1, le=86400, description="Interpolation step interval in seconds"),
    format: str = Query(default="json", pattern="^(json|csv)$"),
) -> Union[Dict[str, Any], PlainTextResponse]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.tag_id,
                    t.tag_name,
                    t.attribute_name,
                    t.eng_units,
                    t.is_step_tag,
                    a.asset_name,
                    a.asset_path::text AS asset_path
                FROM tags t
                JOIN assets a ON t.asset_id = a.asset_id
                WHERE t.tag_name = %s;
                """,
                (tag_name,),
            )
            tag_meta = cur.fetchone()

    if not tag_meta:
        raise HTTPException(status_code=404, detail=f"Tag '{tag_name}' not found")

    tag_id = int(tag_meta["tag_id"])
    is_step_tag = bool(tag_meta["is_step_tag"])
    ch = get_ch_client()

    where_clauses = ["tag_id = {tag_id:UInt32}", "quality >= 192"]
    params: Dict[str, Any] = {"tag_id": tag_id}

    if start_time:
        where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
        params["start_time"] = start_time
    if end_time:
        where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
        params["end_time"] = end_time

    where_sql = " AND ".join(where_clauses)

    if is_step_tag:
        # Discrete / Step Tag: Last Observation Carried Forward (LOCF) via WITH FILL ... INTERPOLATE
        # Never produces fractional decimals (0, 1, 2 remain strict integers).
        interpolation_mode = "LOCF_STEP"
        sql = f"""
        SELECT
            formatDateTime(grid_ts, '%Y-%m-%dT%H:%i:%SZ', 'UTC') AS ts,
            toInt64(round(val)) AS val,
            str_val
        FROM (
            SELECT
                toStartOfInterval(ts, INTERVAL {int(step_seconds)} SECOND) AS grid_ts,
                argMax(val, ts) AS val,
                argMax(str_val, ts) AS str_val
            FROM pi_historian.sensor_data
            WHERE {where_sql}
            GROUP BY grid_ts
            ORDER BY grid_ts ASC
        )
        ORDER BY grid_ts ASC
        WITH FILL STEP toIntervalSecond({int(step_seconds)})
        INTERPOLATE (
            val AS val,
            str_val AS str_val
        )
        """
        raw_points = list(ch.query(sql, parameters=params).named_results())
        points = [
            {
                "ts": r["ts"],
                "val": int(r["val"]),
                "str_val": r.get("str_val", ""),
            }
            for r in raw_points
        ]
    else:
        # Continuous Analog Tag: Linear Interpolation via ClickHouse WITH FILL STEP ... INTERPOLATE
        interpolation_mode = "LINEAR"
        sql = f"""
        WITH
            grid_base AS (
                SELECT
                    toStartOfInterval(ts, INTERVAL {int(step_seconds)} SECOND) AS grid_ts,
                    avg(val) AS raw_val
                FROM pi_historian.sensor_data
                WHERE {where_sql}
                GROUP BY grid_ts
                ORDER BY grid_ts ASC
            ),
            with_slopes AS (
                SELECT
                    grid_ts,
                    raw_val AS val,
                    leadInFrame(raw_val, 1, raw_val) OVER (
                        ORDER BY grid_ts ASC ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING
                    ) AS next_val,
                    leadInFrame(grid_ts, 1, grid_ts) OVER (
                        ORDER BY grid_ts ASC ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING
                    ) AS next_ts,
                    if(
                        next_ts > grid_ts,
                        (next_val - raw_val) * {float(step_seconds)} / dateDiff('second', grid_ts, next_ts),
                        0.0
                    ) AS step_delta
                FROM grid_base
            )
        SELECT
            formatDateTime(grid_ts, '%Y-%m-%dT%H:%i:%SZ', 'UTC') AS ts,
            round(val, 4) AS val
        FROM with_slopes
        ORDER BY grid_ts ASC
        WITH FILL STEP toIntervalSecond({int(step_seconds)})
        INTERPOLATE (
            step_delta AS step_delta,
            val AS val + step_delta
        )
        """
        raw_points = list(ch.query(sql, parameters=params).named_results())
        points = [{"ts": r["ts"], "val": float(r["val"])} for r in raw_points]

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["tag_name", "asset_path", "eng_units", "interpolation_mode", "ts", "val"])
        for pt in points:
            writer.writerow(
                [
                    tag_meta["tag_name"],
                    tag_meta["asset_path"],
                    tag_meta["eng_units"],
                    interpolation_mode,
                    pt["ts"],
                    pt["val"],
                ]
            )
        return PlainTextResponse(content=buf.getvalue(), media_type="text/csv")

    return {
        "tag_id": tag_id,
        "tag_name": tag_meta["tag_name"],
        "asset_name": tag_meta["asset_name"],
        "asset_path": tag_meta["asset_path"],
        "attribute_name": tag_meta["attribute_name"],
        "eng_units": tag_meta["eng_units"],
        "is_step_tag": is_step_tag,
        "interpolation_mode": interpolation_mode,
        "step_seconds": step_seconds,
        "point_count": len(points),
        "points": points,
    }


# ---------------------------------------------------------------------------
# 5. ISA-88 Event Frame Engine & 21 CFR Part 11 Electronic Signatures
# ---------------------------------------------------------------------------


@app.get("/api/v1/event-frames")
def list_event_frames() -> Dict[str, Any]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ef.event_id::text AS event_id,
                    ef.parent_event_id::text AS parent_event_id,
                    ef.event_name,
                    ef.event_template,
                    ef.asset_id,
                    a.asset_name,
                    a.asset_path::text AS asset_path,
                    ef.start_time,
                    ef.end_time,
                    ef.severity,
                    ef.captured_metrics,
                    ef.signed_by,
                    ef.signature_meaning,
                    ef.signed_at,
                    ef.signature_hash
                FROM event_frames ef
                JOIN assets a ON ef.asset_id = a.asset_id
                ORDER BY ef.start_time DESC;
                """
            )
            rows = cur.fetchall()
    return {"count": len(rows), "event_frames": rows}


@app.post("/api/v1/event-frames/evaluate")
def trigger_event_frame_evaluation(
    x_actor_id: Optional[str] = Header(default="event_frame_engine", alias="X-Actor-Id"),
    x_change_reason: Optional[str] = Header(
        default="Automated ISA-88 Event Frame Limit Evaluation",
        alias="X-Change-Reason",
    ),
) -> Dict[str, Any]:
    return evaluate_event_frames_sync(
        actor_id=x_actor_id or "event_frame_engine",
        change_reason=x_change_reason or "Automated ISA-88 Event Frame Limit Evaluation",
    )


@app.post("/api/v1/event-frames/{event_id}/sign")
def sign_event_frame(
    event_id: uuid.UUID,
    payload: ElectronicSignatureRequest,
    x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
    x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
) -> Dict[str, Any]:
    actor = x_actor_id or payload.user_id
    reason = x_change_reason or payload.change_reason

    with get_pg_conn() as conn:
        try:
            with conn.cursor() as cur:
                # 1. Authenticate user credentials against users.password_hash (21 CFR Part 11 §11.200)
                cur.execute(
                    """
                    SELECT user_id, full_name, role
                    FROM users
                    WHERE user_id = %s
                      AND is_active = TRUE
                      AND crypt(%s, password_hash) = password_hash;
                    """,
                    (payload.user_id, payload.password),
                )
                auth_user = cur.fetchone()
                if not auth_user:
                    raise HTTPException(
                        status_code=401,
                        detail="21 CFR Part 11 Electronic Signature Authentication Failed: Invalid user_id or password",
                    )

                # 2. Verify target Event Frame exists
                cur.execute(
                    "SELECT event_id, event_name FROM event_frames WHERE event_id = %s;",
                    (str(event_id),),
                )
                ef_row = cur.fetchone()
                if not ef_row:
                    raise HTTPException(status_code=404, detail=f"Event Frame {event_id} not found")

                # 3. Compute HMAC-SHA256 electronic signature binding (§11.50, §11.70)
                signed_at_dt = dt.datetime.now(dt.timezone.utc)
                signed_at_iso = signed_at_dt.isoformat()
                canonical_signing_payload = (
                    f"{event_id}|{payload.user_id}|{payload.signature_meaning}|{signed_at_iso}"
                )
                signature_hash = hmac.new(
                    ESIG_SECRET_KEY.encode("utf-8"),
                    canonical_signing_payload.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()

                # 4. Set Part 11 context and update event_frames
                apply_part11_context(cur, actor, reason)
                cur.execute(
                    """
                    UPDATE event_frames
                    SET signed_by = %s,
                        signature_meaning = %s,
                        signed_at = %s,
                        signature_hash = %s
                    WHERE event_id = %s
                    RETURNING
                        event_id::text AS event_id,
                        event_name,
                        event_template,
                        signed_by,
                        signature_meaning,
                        signed_at,
                        signature_hash;
                    """,
                    (
                        payload.user_id,
                        payload.signature_meaning,
                        signed_at_dt,
                        signature_hash,
                        str(event_id),
                    ),
                )
                signed_record = cur.fetchone()
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "signed",
        "signer_full_name": auth_user["full_name"],
        "signer_role": auth_user["role"],
        "event_frame": signed_record,
    }


# ---------------------------------------------------------------------------
# 6. PI Integrator Replacement: Enriched Apache Parquet Lakehouse Export
# ---------------------------------------------------------------------------


@app.post("/api/v1/lakehouse/export-parquet")
def export_parquet(payload: ParquetExportRequest = ParquetExportRequest()) -> Dict[str, Any]:
    ch = get_ch_client()

    where_clauses = ["quality >= 192"]
    params: Dict[str, Any] = {}

    if payload.asset_path:
        where_clauses.append(
            "dictGet('pi_historian.pg_asset_tags', 'asset_path', toUInt64(tag_id)) = {asset_path:String}"
        )
        params["asset_path"] = payload.asset_path
    if payload.start_time:
        where_clauses.append("ts >= parseDateTimeBestEffort({start_time:String}, 'UTC')")
        params["start_time"] = payload.start_time
    if payload.end_time:
        where_clauses.append("ts <= parseDateTimeBestEffort({end_time:String}, 'UTC')")
        params["end_time"] = payload.end_time

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
        dictGet('pi_historian.pg_asset_tags', 'asset_path', toUInt64(tag_id)) AS asset_path,
        dictGet('pi_historian.pg_asset_tags', 'asset_name', toUInt64(tag_id)) AS asset_name,
        tag_id,
        dictGet('pi_historian.pg_asset_tags', 'tag_name', toUInt64(tag_id)) AS tag_name,
        dictGet('pi_historian.pg_asset_tags', 'attribute_name', toUInt64(tag_id)) AS attribute_name,
        dictGet('pi_historian.pg_asset_tags', 'eng_units', toUInt64(tag_id)) AS eng_units,
        ts,
        val,
        str_val,
        quality
    FROM pi_historian.sensor_data
    WHERE {where_sql}
    ORDER BY tag_id ASC, ts ASC
    """

    rows = list(ch.query(query, parameters=params).named_results())
    df = pd.DataFrame(rows)

    ts_stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EXPORT_DIR / f"{payload.filename_prefix}_{ts_stamp}.parquet"

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, out_path, compression="snappy")

    return {
        "status": "exported",
        "file_path": str(out_path),
        "row_count": len(df),
        "file_size_bytes": out_path.stat().st_size,
        "columns": list(df.columns),
    }


# ---------------------------------------------------------------------------
# 7. 21 CFR Part 11 Cryptographic Audit Trail Verification
# ---------------------------------------------------------------------------


@app.get("/api/v1/audit-trail/verify")
def verify_audit_trail() -> Dict[str, Any]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    audit_id,
                    recorded_at::text AS recorded_at_str,
                    actor_id,
                    change_reason,
                    target_table,
                    record_pk,
                    operation,
                    COALESCE(new_payload::text, '') AS new_payload_str,
                    prev_hash,
                    row_hash
                FROM part11_audit_log
                ORDER BY audit_id ASC;
                """
            )
            rows = cur.fetchall()

    expected_prev_hash = "GENESIS_0000000000000000"
    verified_hashes = 0
    chain_valid = True
    broken_at_audit_id: Optional[int] = None

    for row in rows:
        raw_concat = (
            f"{row['prev_hash']}"
            f"{row['recorded_at_str']}"
            f"{row['actor_id']}"
            f"{row['operation']}"
            f"{row['new_payload_str']}"
        )
        computed_hash = hashlib.sha256(raw_concat.encode("utf-8")).hexdigest()

        if row["prev_hash"] == expected_prev_hash and computed_hash == row["row_hash"]:
            verified_hashes += 1
        else:
            chain_valid = False
            if broken_at_audit_id is None:
                broken_at_audit_id = int(row["audit_id"])

        expected_prev_hash = row["row_hash"]

    return {
        "chain_valid": chain_valid,
        "total_records": len(rows),
        "verified_hashes": verified_hashes,
        "genesis_anchor": "GENESIS_0000000000000000",
        "head_row_hash": expected_prev_hash,
        "broken_at_audit_id": broken_at_audit_id,
    }


# ---------------------------------------------------------------------------
# 8. Pydantic AI Co-Pilot & Model Context Protocol (`gxphistorian-mcp`)
# ---------------------------------------------------------------------------

from gxp_ai_agent import (
    DeviationInvestigationBrief,
    GxPHistorianDeps,
    StagedTagProposalItem,
    configure_gxp_ai_observability,
    run_event_frame_investigation,
    run_part11_tag_onboarding_workflow,
)
from mcp_server import create_gxphistorian_mcp_server, get_mcp_manifest_summary

configure_gxp_ai_observability()


def build_gxp_ai_deps(
    actor_id: Optional[str] = None,
    change_reason: Optional[str] = None,
) -> GxPHistorianDeps:
    return GxPHistorianDeps(
        get_pg_conn=get_pg_conn,
        get_ch_client=get_ch_client,
        get_assets_tree_fn=lambda root: get_assets_tree(root_path=root),
        get_plot_values_fn=lambda tid, st, et, iv: get_plot_values(
            tag_id=tid,
            start_time=st,
            end_time=et,
            intervals=iv,
        ),
        get_datalink_sampled_fn=lambda tname, st, et, step: get_datalink_sampled(
            tag_name=tname,
            start_time=st,
            end_time=et,
            step_seconds=step,
            format="json",
        ),  # type: ignore[return-value]
        list_event_frames_fn=list_event_frames,
        verify_audit_trail_fn=verify_audit_trail,
        create_tag_fn=lambda payload_dict, act, rsn: create_tag(
            payload=TagCreateRequest(**payload_dict),
            x_actor_id=act,
            x_change_reason=rsn,
        ),
        actor_id=actor_id,
        change_reason=change_reason,
    )


gxphistorian_mcp_server = create_gxphistorian_mcp_server(deps_factory=build_gxp_ai_deps)


class TagOnboardingApprovalRequest(BaseModel):
    proposal: StagedTagProposalItem
    approved: bool = Field(
        default=False,
        description="False to stage and return DeferredToolRequests; True to approve and commit with Part 11 headers.",
    )


@app.get("/api/v1/ai/mcp/manifest")
def get_ai_mcp_manifest() -> Dict[str, Any]:
    """Return the `gxphistorian-mcp` tools, resources, and Pydantic AI capabilities catalog."""
    return get_mcp_manifest_summary()


@app.post(
    "/api/v1/ai/event-frames/{event_id}/investigate",
    response_model=DeviationInvestigationBrief,
)
def investigate_event_frame_with_ai(event_id: uuid.UUID) -> DeviationInvestigationBrief:
    """
    Run the Pydantic AI `gxp_deviation_investigator_agent` on an ISA-88 Event Frame to correlate
    sibling tags (`WHERE quality >= 192`), diagnose excluded bad-quality spikes (`quality < 192`),
    verify the PostgreSQL `part11_audit_log` SHA-256 chain, and produce an advisory CAPA brief.
    """
    deps = build_gxp_ai_deps()
    try:
        return run_event_frame_investigation(deps=deps, event_id=str(event_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/ai/copilot/propose-tag")
def propose_or_approve_tag_with_ai(
    body: TagOnboardingApprovalRequest,
    x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
    x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
) -> Dict[str, Any]:
    """
    Execute the Pydantic AI `gxp_copilot_agent` Human-in-the-Loop 21 CFR Part 11 tag onboarding flow:
      - `approved=False`: Validates tag limits via `args_validator` and pauses with `ApprovalRequired`
        (`DeferredToolRequests`).
      - `approved=True`: Requires `X-Actor-Id` and `X-Change-Reason`, resumes with `DeferredToolResults`,
        and commits the tag to PostgreSQL with SHA-256 WORM audit logging.
    """
    if body.approved:
        clean_actor = (x_actor_id or "").strip()
        clean_reason = (x_change_reason or "").strip()
        if not clean_actor or not clean_reason:
            raise HTTPException(
                status_code=400,
                detail="21 CFR Part 11 Violation: X-Actor-Id and X-Change-Reason headers are mandatory when approving a deferred tag creation.",
            )
    deps = build_gxp_ai_deps(actor_id=x_actor_id, change_reason=x_change_reason)
    return run_part11_tag_onboarding_workflow(
        deps=deps,
        proposal=body.proposal,
        approved=body.approved,
    )

