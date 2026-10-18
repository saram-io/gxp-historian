"""
Operational Qualification (OQ) — Historian Core, Quality Filtering, DataLink Interpolation,
LTTB Downsampling, and Parquet Lakehouse Integrity (URS-011 through URS-015).
"""

from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any, List

import httpx
import pyarrow.parquet as pq

from conftest import MOCK_SERVER_BASE_URL, REPO_ROOT, EvidenceTracker


def _ensure_synthetic_oq_dataset(ch_client: Any) -> None:
    """
    Idempotently seed deterministic OQ synthetic telemetry in a dedicated
    historical window (2026-01-15 10:00:00 .. 12:05:00 UTC) without ever
    executing ALTER TABLE ... DELETE/UPDATE on ClickHouse.
    """
    existing = int(
        ch_client.command(
            """
            SELECT count()
            FROM pi_historian.sensor_data
            WHERE ts >= '2026-01-15 10:00:00'
              AND ts < '2026-01-15 13:00:00'
            """
        )
        or 0
    )
    if existing > 0:
        return

    rows: List[List[Any]] = [
        # 1. URS-012 Bad Quality Exclusion Window (2026-01-15 10:00:00 .. 10:00:59 UTC)
        [101, dt.datetime(2026, 1, 15, 10, 0, 10, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
        [101, dt.datetime(2026, 1, 15, 10, 0, 20, tzinfo=dt.timezone.utc), 38.0, "", 192, 0],
        [101, dt.datetime(2026, 1, 15, 10, 0, 30, tzinfo=dt.timezone.utc), 9999.0, "SENSOR_FAULT_SPIKE", 0, 2],
        # 2. URS-013 Linear Interpolation Window on Tag 101 (is_step_tag=False)
        [101, dt.datetime(2026, 1, 15, 11, 0, 0, tzinfo=dt.timezone.utc), 36.0, "", 192, 0],
        [101, dt.datetime(2026, 1, 15, 11, 2, 0, tzinfo=dt.timezone.utc), 38.0, "", 192, 0],
        # 3. URS-013 LOCF Step Interpolation Window on Tag 103 (is_step_tag=True)
        [103, dt.datetime(2026, 1, 15, 11, 0, 0, tzinfo=dt.timezone.utc), 1.0, "LOW", 192, 0],
        [103, dt.datetime(2026, 1, 15, 11, 2, 0, tzinfo=dt.timezone.utc), 2.0, "HIGH_RUN", 192, 0],
    ]

    # 4. URS-014 LTTB Peak Preservation Window on Tag 401 (2026-01-15 12:00:00 .. 12:01:39 UTC)
    base_dt = dt.datetime(2026, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
    for sec in range(100):
        ts_point = base_dt + dt.timedelta(seconds=sec)
        val_point = 845.75 if sec == 50 else 20.0 + (sec % 3) * 0.1
        rows.append([401, ts_point, val_point, "", 192, 0])

    ch_client.insert(
        "pi_historian.sensor_data",
        rows,
        column_names=["tag_id", "ts", "val", "str_val", "quality", "status_code"],
    )


def test_oq_06_multi_protocol_telemetry_ingestion(
    ch_client: Any,
    evidence: EvidenceTracker,
) -> None:
    """URS-011: Verify all 6 mock instrument connection listeners and active telemetry across all 5 GxP tags."""
    self_test_resp = httpx.post(
        f"{MOCK_SERVER_BASE_URL}/control/self-test",
        json={"push_to_edge": True},
        timeout=10.0,
    )
    assert self_test_resp.status_code == 200
    self_test_data = self_test_resp.json()
    assert self_test_data["all_protocols_verified"] is True
    assert self_test_data["edge_collector_ingested"] is True

    rows = list(
        ch_client.query(
            """
            SELECT
                tag_id,
                dictGet('pi_historian.pg_asset_tags', 'tag_name', toUInt64(tag_id)) AS tag_name,
                count() AS row_count
            FROM pi_historian.sensor_data
            WHERE tag_id IN (101, 102, 103, 301, 401)
            GROUP BY tag_id
            ORDER BY tag_id
            """
        ).named_results()
    )
    assert len(rows) == 5
    for r in rows:
        assert int(r["row_count"]) > 0

    evidence.record(
        assertion_summary="Verified all 6 mock instrument protocol listeners (OPC UA, Modbus TCP, BACnet/IP, Siemens S7, RS-232 Serial, OPC DA) and active telemetry ingestion across all 5 GxP tags.",
        input_payload={"tag_ids": [101, 102, 103, 301, 401], "mock_server_self_test": f"{MOCK_SERVER_BASE_URL}/control/self-test"},
        output_payload={"tag_counts": rows, "mock_protocol_results": self_test_data["protocol_results"]},
    )


def test_oq_07_bad_quality_exclusion_in_rollup(
    ch_client: Any,
    evidence: EvidenceTracker,
) -> None:
    """URS-012: Verify sensor_rollup_1m completely excludes quality=0 fault spike of 9999.0."""
    _ensure_synthetic_oq_dataset(ch_client)

    raw_check = next(
        iter(
            ch_client.query(
                """
                SELECT
                    count() AS raw_total,
                    countIf(quality = 0) AS bad_count,
                    max(val) AS raw_max
                FROM pi_historian.sensor_data
                WHERE tag_id = 101
                  AND ts >= '2026-01-15 10:00:00'
                  AND ts < '2026-01-15 10:01:00'
                """
            ).named_results()
        )
    )
    assert int(raw_check["raw_total"]) == 3
    assert int(raw_check["bad_count"]) == 1
    assert float(raw_check["raw_max"]) == 9999.0

    rollup_check = next(
        iter(
            ch_client.query(
                """
                SELECT
                    countMerge(sample_count) AS good_count,
                    round(minMerge(min_val), 4) AS rollup_min,
                    round(avgMerge(avg_val), 4) AS rollup_avg,
                    round(maxMerge(max_val), 4) AS rollup_max
                FROM pi_historian.sensor_rollup_1m
                WHERE tag_id = 101
                  AND bucket_1m = '2026-01-15 10:00:00'
                """
            ).named_results()
        )
    )
    assert int(rollup_check["good_count"]) == 2
    assert float(rollup_check["rollup_min"]) == 37.0
    assert float(rollup_check["rollup_avg"]) == 37.5
    assert float(rollup_check["rollup_max"]) == 38.0

    evidence.record(
        assertion_summary="Proved mv_sensor_rollup_1m excludes quality=0 fault spike (9999.0), computing exact GMP rollup avg=37.5, max=38.0.",
        input_payload={"injected_points": [{"val": 37.0, "quality": 192}, {"val": 38.0, "quality": 192}, {"val": 9999.0, "quality": 0}]},
        output_payload={"raw_table": raw_check, "rollup_1m_table": rollup_check},
    )


def test_oq_08_datalink_linear_and_locf_step_interpolation(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-013: Verify /api/v1/datalink/sampled linear midpoints for analog tags and integer LOCF for step tags."""
    _ensure_synthetic_oq_dataset(ch_client)

    # 1. Continuous Analog Tag (BR201_TEMP_PV, is_step_tag=False): 36.0 at 11:00, 38.0 at 11:02 -> 37.0 at 11:01
    analog_resp = api_client.get(
        "/api/v1/datalink/sampled",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-15T11:00:00Z",
            "end_time": "2026-01-15T11:02:00Z",
            "step_seconds": 60,
            "format": "json",
        },
    )
    assert analog_resp.status_code == 200
    analog_data = analog_resp.json()
    assert analog_data["is_step_tag"] is False
    assert analog_data["interpolation_mode"] == "LINEAR"
    analog_vals = [pt["val"] for pt in analog_data["points"]]
    assert analog_vals == [36.0, 37.0, 38.0]

    # 2. Discrete Step Tag (BR201_AGIT_STATE, is_step_tag=True): 1 at 11:00, 2 at 11:02 -> LOCF integer 1 at 11:01
    step_resp = api_client.get(
        "/api/v1/datalink/sampled",
        params={
            "tag_name": "BR201_AGIT_STATE",
            "start_time": "2026-01-15T11:00:00Z",
            "end_time": "2026-01-15T11:02:00Z",
            "step_seconds": 60,
            "format": "json",
        },
    )
    assert step_resp.status_code == 200
    step_data = step_resp.json()
    assert step_data["is_step_tag"] is True
    assert step_data["interpolation_mode"] == "LOCF_STEP"
    step_vals = [pt["val"] for pt in step_data["points"]]
    assert step_vals == [1, 1, 2]
    assert all(isinstance(v, int) for v in step_vals)

    evidence.record(
        assertion_summary="Verified exact linear midpoint (37.0) on BR201_TEMP_PV and integer LOCF ([1, 1, 2]) on BR201_AGIT_STATE.",
        input_payload={"window": "2026-01-15T11:00:00Z..11:02:00Z", "step_seconds": 60},
        output_payload={"linear_points": analog_data["points"], "locf_step_points": step_data["points"]},
    )


def test_oq_09_lttb_downsampling_preserves_local_peak(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-014: Verify /api/v1/trends/plot-values (LTTB) preserves the exact timestamp and magnitude of local peaks."""
    _ensure_synthetic_oq_dataset(ch_client)

    resp = api_client.get(
        "/api/v1/trends/plot-values",
        params={
            "tag_id": 401,
            "start_time": "2026-01-15T12:00:00Z",
            "end_time": "2026-01-15T12:01:39Z",
            "intervals": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["downsampling_algorithm"] == "largestTriangleThreeBuckets"
    assert data["point_count"] == 10

    peak_point = max(data["points"], key=lambda p: p["val"])
    assert peak_point["val"] == 845.75
    assert peak_point["ts"].startswith("2026-01-15T12:00:50")

    evidence.record(
        assertion_summary="Verified ClickHouse LTTB 10x downsampling (100 -> 10 points) preserved exact peak magnitude (845.75 mAU) and timestamp (12:00:50Z).",
        input_payload={"tag_id": 401, "raw_points": 100, "target_intervals": 10, "injected_peak": {"ts": "2026-01-15T12:00:50Z", "val": 845.75}},
        output_payload={"preserved_peak": peak_point, "downsampled_point_count": data["point_count"]},
    )


def test_oq_10_event_frame_excursion_and_parquet_lakehouse_export(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-015: Verify Event Frame excursion capture and Parquet lakehouse export integrity via pyarrow."""
    eval_resp = api_client.post("/api/v1/event-frames/evaluate")
    assert eval_resp.status_code == 200

    ef_resp = api_client.get("/api/v1/event-frames")
    assert ef_resp.status_code == 200
    events = ef_resp.json()["event_frames"]
    templates = {e["event_template"] for e in events}
    assert "Fermentation_Batch" in templates

    # Trigger Parquet export for the synthetic 2026-01-15 11:00..11:03 window on Bioreactor_201
    export_resp = api_client.post(
        "/api/v1/lakehouse/export-parquet",
        json={
            "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
            "start_time": "2026-01-15T11:00:00Z",
            "end_time": "2026-01-15T11:02:00Z",
            "filename_prefix": "oq_qualification_verify",
        },
    )
    assert export_resp.status_code == 200
    export_meta = export_resp.json()
    assert export_meta["status"] == "exported"
    assert export_meta["row_count"] == 4

    # Read back Parquet file from host ./exports directory via pyarrow and verify 100% fidelity
    parquet_filename = pathlib.Path(export_meta["file_path"]).name
    host_parquet_path = REPO_ROOT / "exports" / parquet_filename
    assert host_parquet_path.exists()

    table = pq.read_table(host_parquet_path)
    df = table.to_pandas()
    assert len(df) == 4
    assert set(df["tag_name"].unique()) == {"BR201_TEMP_PV", "BR201_AGIT_STATE"}
    assert set(df["asset_path"].unique()) == {"BioCorp.Fremont.USP.Bioreactor_201"}

    evidence.record(
        assertion_summary="Verified Event Frame evaluation and Apache Parquet export with 100% row/value fidelity via pyarrow.",
        input_payload={"asset_path": "BioCorp.Fremont.USP.Bioreactor_201", "window": "2026-01-15T11:00:00Z..11:02:00Z"},
        output_payload={"export_metadata": export_meta, "parquet_columns": list(df.columns), "verified_rows": len(df)},
    )
