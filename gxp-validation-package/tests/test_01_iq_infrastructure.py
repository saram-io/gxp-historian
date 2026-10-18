"""
Installation Qualification (IQ) Automated Test Suite (URS-001 through URS-005).

Verifies:
  - Container availability, health checks, and non-default GxP credentials
  - PostgreSQL 16 extensions (ltree, btree_gist, pgcrypto) and schema tables
  - ClickHouse lossless time-series codecs (Delta, DoubleDelta, Gorilla, T64, ZSTD)
  - ISA-95 ltree asset hierarchy and ClickHouse pg_asset_tags dictionary sync
  - Edge Collector disk WAL configuration and Stage 1 Exception/Deadband filter logic
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any, Dict

import httpx
import psycopg

from conftest import (
    CH_PASSWORD,
    GRAFANA_BASE_URL,
    GRAFANA_PASSWORD,
    MCP_BASE_URL,
    MOCK_SERVER_BASE_URL,
    PG_PASSWORD,
    REPO_ROOT,
    EvidenceTracker,
)


def test_iq_01_services_and_non_default_credentials(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-001: Verify container health and absence of insecure default credentials."""
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    health = resp.json()
    assert health["status"] == "healthy"
    assert health["postgres"]["connected"] is True
    assert health["clickhouse"]["connected"] is True

    # Verify standalone Pydantic AI & MCP Server (`gxphistorian-mcp`) container readiness
    mcp_resp = httpx.get(f"{MCP_BASE_URL}/health", timeout=10.0)
    assert mcp_resp.status_code == 200
    mcp_health = mcp_resp.json()
    assert mcp_health["status"] == "healthy"
    assert mcp_health["service"] == "gxphistorian-mcp"
    assert mcp_health["postgres"]["connected"] is True
    assert mcp_health["clickhouse"]["connected"] is True

    # Verify Multi-Protocol Biopharma Instrument Mock Server (`instrument-mock-server`) readiness
    mock_resp = httpx.get(f"{MOCK_SERVER_BASE_URL}/health", timeout=10.0)
    assert mock_resp.status_code == 200
    mock_health = mock_resp.json()
    assert mock_health["status"] == "healthy"
    assert mock_health["service"] == "instrument-mock-server"
    assert len(mock_health["active_listeners"]) == 6

    # Verify Grafana Vision readiness, live datasource health (ClickHouse + PostgreSQL), and HMI dashboard panels
    gf_resp = httpx.get(
        f"{GRAFANA_BASE_URL}/api/search",
        auth=("admin", GRAFANA_PASSWORD),
        timeout=10.0,
    )
    assert gf_resp.status_code == 200
    dashboards = gf_resp.json()
    hmi_titles = [d.get("title", "") for d in dashboards]
    assert any("GxPHistorian Vision" in t for t in hmi_titles)

    ch_ds_health = httpx.get(
        f"{GRAFANA_BASE_URL}/api/datasources/uid/clickhouse_core/health",
        auth=("admin", GRAFANA_PASSWORD),
        timeout=10.0,
    )
    assert ch_ds_health.status_code == 200
    assert ch_ds_health.json()["status"] == "OK"

    pg_ds_health = httpx.get(
        f"{GRAFANA_BASE_URL}/api/datasources/uid/postgres_control/health",
        auth=("admin", GRAFANA_PASSWORD),
        timeout=10.0,
    )
    assert pg_ds_health.status_code == 200
    assert pg_ds_health.json()["status"] == "OK"

    dash_resp = httpx.get(
        f"{GRAFANA_BASE_URL}/api/dashboards/uid/gxphistorian-gxp-bioreactor-hmi",
        auth=("admin", GRAFANA_PASSWORD),
        timeout=10.0,
    )
    assert dash_resp.status_code == 200
    dash_model = dash_resp.json()["dashboard"]
    assert len(dash_model["panels"]) == 4
    anno_names = [a.get("name", "") for a in dash_model.get("annotations", {}).get("list", [])]
    assert "ISA-88 Event Frames & Excursions" in anno_names

    # Verify non-default passwords are enforced
    insecure_defaults = {"postgres", "password", "admin", "default", "", "clickhouse"}
    assert PG_PASSWORD not in insecure_defaults
    assert CH_PASSWORD not in insecure_defaults
    assert GRAFANA_PASSWORD not in insecure_defaults

    evidence.record(
        assertion_summary=(
            "Verified PostgreSQL, ClickHouse, FastAPI, gxphistorian-mcp, instrument-mock-server, and Grafana "
            "(live ClickHouse/PostgreSQL datasources + 4-panel HMI dashboard) health with non-default GxP secrets."
        ),
        input_payload={
            "endpoints": [
                "/api/v1/health",
                f"{MCP_BASE_URL}/health",
                f"{MOCK_SERVER_BASE_URL}/health",
                f"{GRAFANA_BASE_URL}/api/datasources/uid/clickhouse_core/health",
                f"{GRAFANA_BASE_URL}/api/datasources/uid/postgres_control/health",
                f"{GRAFANA_BASE_URL}/api/dashboards/uid/gxphistorian-gxp-bioreactor-hmi",
            ]
        },
        output_payload={
            "api_health": health,
            "mcp_health": mcp_health,
            "mock_server_health": mock_health,
            "grafana_dashboards": hmi_titles,
            "grafana_datasources_ok": {"clickhouse_core": ch_ds_health.json(), "postgres_control": pg_ds_health.json()},
            "grafana_panel_count": len(dash_model["panels"]),
        },
    )


def test_iq_02_postgres_extensions_and_schema(
    pg_conn: psycopg.Connection[Dict[str, Any]],
    evidence: EvidenceTracker,
) -> None:
    """URS-002: Verify PostgreSQL extensions (ltree, btree_gist, pgcrypto), all 10 Part 11 tables, and triggers."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT extname
            FROM pg_extension
            WHERE extname IN ('ltree', 'btree_gist', 'pgcrypto')
            ORDER BY extname;
            """
        )
        installed_exts = [r["extname"] for r in cur.fetchall()]
        assert installed_exts == ["btree_gist", "ltree", "pgcrypto"]

        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """
        )
        tables = [r["table_name"] for r in cur.fetchall()]
        expected_gxp_audited_tables = {
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
        expected_all_tables = expected_gxp_audited_tables | {"part11_audit_log", "users"}
        assert expected_all_tables.issubset(set(tables))

        # Verify all 10 GxP state/config tables have fn_enforce_part11_audit trigger attached
        cur.execute(
            """
            SELECT DISTINCT event_object_table AS table_name
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
              AND action_statement LIKE '%fn_enforce_part11_audit%'
            ORDER BY table_name;
            """
        )
        audited_trigger_tables = [r["table_name"] for r in cur.fetchall()]
        assert expected_gxp_audited_tables.issubset(set(audited_trigger_tables))

        cur.execute("SELECT user_id, role, is_active FROM users ORDER BY user_id;")
        users = cur.fetchall()
        user_ids = [u["user_id"] for u in users]
        assert "operator_01" in user_ids
        assert "qa_approver_01" in user_ids

    evidence.record(
        assertion_summary="Verified PostgreSQL 16 extensions (btree_gist, ltree, pgcrypto), all 12 GxP tables (including all 10 Part 11 trigger-enforced tables), and seeded Part 11 users.",
        input_payload={"expected_extensions": ["btree_gist", "ltree", "pgcrypto"], "expected_audited_tables_count": 10},
        output_payload={"installed_extensions": installed_exts, "tables": tables, "audited_trigger_tables": audited_trigger_tables, "users": users},
    )


def test_iq_03_clickhouse_compression_codecs(
    ch_client: Any,
    evidence: EvidenceTracker,
) -> None:
    """URS-003: Verify ClickHouse sensor_data lossless compression codecs (Delta, DoubleDelta, Gorilla, T64) and rollup objects."""
    rows = list(
        ch_client.query(
            """
            SELECT name, type, compression_codec
            FROM system.columns
            WHERE database = 'pi_historian'
              AND table = 'sensor_data'
            ORDER BY position
            """
        ).named_results()
    )
    codec_map = {r["name"]: r["compression_codec"] for r in rows}

    assert "Delta" in codec_map["tag_id"] and "ZSTD(1)" in codec_map["tag_id"]
    assert "DoubleDelta" in codec_map["ts"] and "ZSTD(1)" in codec_map["ts"]
    assert "Gorilla" in codec_map["val"] and "ZSTD(1)" in codec_map["val"]
    assert "T64" in codec_map["quality"] and "ZSTD(1)" in codec_map["quality"]
    assert "T64" in codec_map["status_code"] and "ZSTD(1)" in codec_map["status_code"]

    ch_tables = list(
        ch_client.query(
            """
            SELECT name, engine
            FROM system.tables
            WHERE database = 'pi_historian'
            ORDER BY name
            """
        ).named_results()
    )
    engine_map = {r["name"]: r["engine"] for r in ch_tables}
    assert engine_map.get("sensor_data") == "MergeTree"
    assert engine_map.get("sensor_rollup_1m") == "AggregatingMergeTree"
    assert engine_map.get("mv_sensor_rollup_1m") == "MaterializedView"

    evidence.record(
        assertion_summary="Verified ClickHouse pi_historian.sensor_data column codecs (Delta, DoubleDelta, Gorilla, T64 + ZSTD(1)) and AggregatingMergeTree 1m rollup engines.",
        input_payload={"database": "pi_historian", "table": "sensor_data"},
        output_payload={"column_codecs": codec_map, "table_engines": engine_map},
    )


def test_iq_04_clickhouse_postgres_dictionary_sync(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-004: Verify ISA-95 ltree asset hierarchy resolution via ClickHouse pg_asset_tags dictionary and REST API."""
    dict_rows = list(
        ch_client.query(
            """
            SELECT tag_id, tag_name, asset_path, eng_units, is_step_tag
            FROM pi_historian.pg_asset_tags
            WHERE tag_id IN (101, 102, 103, 301, 401)
            ORDER BY tag_id
            """
        ).named_results()
    )
    assert len(dict_rows) == 5
    by_id = {int(r["tag_id"]): r for r in dict_rows}
    assert by_id[101]["tag_name"] == "BR201_TEMP_PV"
    assert by_id[101]["asset_path"] == "BioCorp.Fremont.USP.Bioreactor_201"
    assert by_id[103]["is_step_tag"] == 1
    assert by_id[301]["asset_path"] == "BioCorp.Fremont.Facilities.Cleanroom_ISO7"
    assert by_id[401]["tag_name"] == "CHROM_UV280_PV"

    # Also verify REST API ltree asset hierarchy browsing & subtree filtering
    tree_resp = api_client.get("/api/v1/assets/tree")
    assert tree_resp.status_code == 200
    assert tree_resp.json()["count"] >= 3

    usp_sub = api_client.get("/api/v1/assets/tree", params={"root_path": "BioCorp.Fremont.USP"})
    assert usp_sub.status_code == 200
    usp_paths = [a["asset_path"] for a in usp_sub.json()["assets"]]
    assert "BioCorp.Fremont.USP.Bioreactor_201" in usp_paths
    assert all(p.startswith("BioCorp.Fremont.USP") for p in usp_paths)

    evidence.record(
        assertion_summary="Verified all 5 seeded GxP tags and ISA-95 ltree paths resolve in ClickHouse pg_asset_tags dictionary and /api/v1/assets/tree.",
        input_payload={"expected_tag_ids": [101, 102, 103, 301, 401], "subtree_filter": "BioCorp.Fremont.USP"},
        output_payload={"dictionary_rows": dict_rows, "usp_subtree_assets": usp_paths},
    )


def test_iq_05_edge_collector_wal_and_deadband(
    tmp_path: pathlib.Path,
    evidence: EvidenceTracker,
) -> None:
    """URS-005: Verify Telegraf disk WAL config, Stage 1 Exception/Deadband filter, BACnet Status_Flags mapper, and OPC DA local spooler."""
    conf_path = REPO_ROOT / "edge-collector" / "telegraf-clickhouse.conf"
    conf_text = conf_path.read_text(encoding="utf-8")
    assert 'buffer_strategy = "disk"' in conf_text
    assert 'buffer_directory = "/var/lib/telegraf/buffer"' in conf_text
    assert 'metric_buffer_limit = 1000000' in conf_text

    # 1. Dynamically load and verify ExceptionDeadbandFilter from multi_protocol_simulator.py
    sim_path = pathlib.Path(REPO_ROOT / "edge-collector" / "scripts" / "multi_protocol_simulator.py")
    spec = importlib.util.spec_from_file_location("multi_protocol_simulator", sim_path)
    assert spec is not None and spec.loader is not None
    sim_mod = importlib.util.module_from_spec(spec)
    sys.modules["multi_protocol_simulator"] = sim_mod
    spec.loader.exec_module(sim_mod)

    cfg = {101: sim_mod.TagFilterConfig(101, "BR201_TEMP_PV", "OPC_UA", exc_dev=0.05, exc_max=10.0)}
    filt = sim_mod.ExceptionDeadbandFilter(cfg)

    # Initial point must emit
    assert filt.should_emit(101, ts=1000.0, val=37.00, quality=192, status_code=0) is True
    # Sub-deadband jitter (<0.05) within ExcMax (<10s) must be suppressed
    assert filt.should_emit(101, ts=1001.0, val=37.02, quality=192, status_code=0) is False
    # Deviation >= ExcDev (0.06 >= 0.05) must emit immediately
    assert filt.should_emit(101, ts=1002.0, val=37.06, quality=192, status_code=0) is True
    # Quality transition (192 -> 0) must emit immediately regardless of value
    assert filt.should_emit(101, ts=1003.0, val=37.06, quality=0, status_code=2) is True

    # 2. Verify BACnet/IP Status_Flags -> OPC Quality mapper from bacnet_cov_worker.py
    bac_path = pathlib.Path(REPO_ROOT / "edge-collector" / "scripts" / "bacnet_cov_worker.py")
    bac_spec = importlib.util.spec_from_file_location("bacnet_cov_worker", bac_path)
    assert bac_spec is not None and bac_spec.loader is not None
    bac_mod = importlib.util.module_from_spec(bac_spec)
    sys.modules["bacnet_cov_worker"] = bac_mod
    bac_spec.loader.exec_module(bac_mod)

    assert bac_mod.status_flags_to_quality([0, 0, 0, 0]) == (192, 0)
    assert bac_mod.status_flags_to_quality([1, 0, 0, 0]) == (192, 4)  # in_alarm
    assert bac_mod.status_flags_to_quality([0, 0, 1, 0]) == (64, 3)   # overridden -> Uncertain
    assert bac_mod.status_flags_to_quality([0, 1, 0, 0]) == (0, 1)    # fault -> Bad

    # 3. Verify Windows OPC DA quality mapper and LocalSpoolBuffer from opcda_windows_forwarder.py
    opcda_path = pathlib.Path(REPO_ROOT / "edge-collector" / "scripts" / "opcda_windows_forwarder.py")
    opcda_spec = importlib.util.spec_from_file_location("opcda_windows_forwarder", opcda_path)
    assert opcda_spec is not None and opcda_spec.loader is not None
    opcda_mod = importlib.util.module_from_spec(opcda_spec)
    sys.modules["opcda_windows_forwarder"] = opcda_mod
    opcda_spec.loader.exec_module(opcda_mod)

    assert opcda_mod.map_opcda_quality("Good") == 192
    assert opcda_mod.map_opcda_quality("Uncertain:LastUsableValue") == 64
    assert opcda_mod.map_opcda_quality("Bad:DeviceFailure") == 0

    spool_file = tmp_path / "opcda_test_spool.jsonl"
    spool = opcda_mod.LocalSpoolBuffer(spool_file)
    spool.append_batch([opcda_mod.TelemetryPoint(tag_id=401, ts=1700000000000, val=245.5, quality=192)])
    assert spool_file.exists()
    drained = spool.drain_batches()
    assert len(drained) == 1
    assert drained[0]["tag_id"] == 401
    assert not spool_file.exists()

    evidence.record(
        assertion_summary="Verified disk-backed WAL buffer configuration, Stage 1 ExceptionDeadbandFilter, BACnet Status_Flags quality mapper, and OPC DA local JSONL store-and-forward spooler.",
        input_payload={"exc_dev": 0.05, "exc_max": 10.0, "buffer_strategy": "disk"},
        output_payload={
            "initial_emit": True,
            "sub_deadband_suppressed": True,
            "exc_dev_triggered": True,
            "quality_change_triggered": True,
            "bacnet_status_flags_verified": True,
            "opcda_disk_spool_verified": True,
        },
    )

