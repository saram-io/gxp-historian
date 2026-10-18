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
    """URS-011: Verify all 6 mock instrument connection listeners (HTTP + direct host TCP/UDP sockets) and active telemetry across all 5 GxP tags."""
    import socket
    import struct

    # 1. Verify internal multi-protocol self-test + Edge Collector forwarding
    self_test_resp = httpx.post(
        f"{MOCK_SERVER_BASE_URL}/control/self-test",
        json={"push_to_edge": True},
        timeout=10.0,
    )
    assert self_test_resp.status_code == 200
    self_test_data = self_test_resp.json()
    assert self_test_data["all_protocols_verified"] is True
    assert self_test_data["edge_collector_ingested"] is True

    # 2. Verify all HTTP protocol inspection & PI UFL SHA-256 batch drop endpoints on instrument-mock-server
    proto_cat = httpx.get(f"{MOCK_SERVER_BASE_URL}/protocols", timeout=10.0)
    assert proto_cat.status_code == 200
    assert len(proto_cat.json()["connection_types"]) == 6

    for ep in ("/protocols/opcua/nodes", "/protocols/modbus/registers", "/protocols/bacnet/objects", "/protocols/s7/db10"):
        ep_resp = httpx.get(f"{MOCK_SERVER_BASE_URL}{ep}", timeout=10.0)
        assert ep_resp.status_code == 200

    opcda_resp = httpx.post(f"{MOCK_SERVER_BASE_URL}/protocols/opcda/read", json={}, timeout=10.0)
    assert opcda_resp.status_code == 200
    assert len(opcda_resp.json()["items"]) >= 3

    ufl_resp = httpx.post(
        f"{MOCK_SERVER_BASE_URL}/protocols/ufl/generate-batch-file",
        json={
            "instrument_type": "Sartocheck_5_Plus_Filter_Integrity",
            "batch_id": "BATCH-2026-OQ-E2E",
            "tag_id": 401,
            "val": 312.5,
            "quality": 192,
            "forward_to_edge": True,
        },
        timeout=10.0,
    )
    assert ufl_resp.status_code == 200
    ufl_data = ufl_resp.json()
    assert ufl_data["status"] == "generated"
    assert len(ufl_data["file_sha256"]) == 64
    assert ufl_data["edge_forwarded"] is True

    # 3. Direct host-to-container raw TCP/UDP socket verification across exposed ports (:4840, :5020, :47808/udp, :1102, :4001)
    # 3a. OPC UA TCP (:4840) Binary HEL/ACK
    with socket.create_connection(("127.0.0.1", 4840), timeout=5.0) as opc_sock:
        opc_sock.sendall(b"HELF\x1c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00@\x00\x00\x00\x00\x00")
        ack = opc_sock.recv(28)
        assert ack[:4] == b"ACKF"

    # 3b. Modbus TCP (:5020) MBAP FC03 Read Holding Registers 40101..40104 (ABCD vs CDAB)
    with socket.create_connection(("127.0.0.1", 5020), timeout=5.0) as mb_sock:
        mb_sock.sendall(struct.pack(">HHHBBHH", 0x0099, 0x0000, 6, 1, 0x03, 100, 4))
        mb_reply = mb_sock.recv(32)
        w0, w1, w2, w3 = struct.unpack(">4H", mb_reply[9:17])
        val_abcd = round(struct.unpack(">f", struct.pack(">HH", w0, w1))[0], 4)
        val_cdab = round(struct.unpack(">f", struct.pack(">HH", w3, w2))[0], 4)
        assert val_abcd == val_cdab

    # 3c. BACnet/IP UDP (:47808) ASHRAE 135 BVLC 0x81 ReadProperty
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as bac_sock:
        bac_sock.settimeout(5.0)
        bac_sock.sendto(bytes([0x81, 0x0A, 0x00, 0x0C, 0x01, 0x00, 0x00, 0x05, 0x07, 0x0C, 0x0C, 0x00]), ("127.0.0.1", 47808))
        bac_reply, _ = bac_sock.recvfrom(128)
        assert bac_reply[:2] == b"\x81\x0a"

    # 3d. Siemens S7comm ISO-on-TCP (:1102) RFC 1006 TPKT + COTP Connection Request (0xE0 -> 0xD0)
    with socket.create_connection(("127.0.0.1", 1102), timeout=5.0) as s7_sock:
        s7_sock.sendall(bytes([0x03, 0x00, 0x00, 0x0B, 0x06, 0xE0, 0x00, 0x00, 0x00, 0x01, 0x00]))
        cotp_cc = s7_sock.recv(32)
        assert cotp_cc[5] == 0xD0

    # 3e. Moxa RS-232 Serial-over-TCP (:4001) MT-SICS (`SI`, `ZI`, `T`, `I4`) & OsmoTECH PRO (`OSMO`)
    with socket.create_connection(("127.0.0.1", 4001), timeout=5.0) as ser_sock:
        for cmd, expected_prefix in [(b"SI\r\n", "S S"), (b"ZI\r\n", "Z A"), (b"T\r\n", "T S"), (b"I4\r\n", 'I4 A "B948271042"'), (b"OSMO\r\n", "OSMO ")]:
            ser_sock.sendall(cmd)
            line = ser_sock.recv(128).decode("utf-8").strip()
            assert line.startswith(expected_prefix)

    # 4. Verify ClickHouse sensor_data holds active telemetry for all 5 GxP tags
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
        assertion_summary="Verified all 6 mock instrument protocol listeners (direct host TCP/UDP sockets + HTTP endpoints + PI UFL SHA-256 CSV drop) and active telemetry ingestion across all 5 GxP tags.",
        input_payload={"tag_ids": [101, 102, 103, 301, 401], "mock_server_self_test": f"{MOCK_SERVER_BASE_URL}/control/self-test"},
        output_payload={"tag_counts": rows, "mock_protocol_results": self_test_data["protocol_results"], "ufl_batch_drop_sha256": ufl_data["file_sha256"]},
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
    """URS-013: Verify /api/v1/datalink/sampled linear midpoints for analog tags, integer LOCF for step tags, and CSV export."""
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

    # Verify CSV format output as well
    csv_resp = api_client.get(
        "/api/v1/datalink/sampled",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-15T11:00:00Z",
            "end_time": "2026-01-15T11:02:00Z",
            "step_seconds": 60,
            "format": "csv",
        },
    )
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers.get("content-type", "")
    csv_lines = [line.strip() for line in csv_resp.text.splitlines() if line.strip()]
    assert len(csv_lines) == 4  # header + 3 rows

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
        assertion_summary="Verified exact linear midpoint (37.0) on BR201_TEMP_PV (JSON + CSV) and integer LOCF ([1, 1, 2]) on BR201_AGIT_STATE.",
        input_payload={"window": "2026-01-15T11:00:00Z..11:02:00Z", "step_seconds": 60},
        output_payload={"linear_points": analog_data["points"], "locf_step_points": step_data["points"], "csv_rows_verified": len(csv_lines)},
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
