---
title: "Document 03 — Functional & Design Specification (FDS)"
description: "Document 03 — Functional and Design Specification (FDS) across the 4-Pillar Historian Architecture."
---
**Document ID:** `FDS-GXPHISTORIAN-2026-003` | **Effective Date (UTC):** `2026-10-18T21:33:54Z`

---

## 1. 4-Pillar System Architecture

1. **Pillar 1 — Multi-Protocol Edge Collector (`edge-collector`):**
   - Built on `telegraf:1.32-alpine` with `buffer_strategy = "disk"` at `/var/lib/telegraf/buffer` (`metric_buffer_limit = 1000000`).
   - Exposes `[[inputs.http_listener_v2]]` on `:8080/ingest` for Windows localhost COM OPC DA forwarders (`opcda_windows_forwarder.py`) and async `bacpypes3` BACnet/IP workers (`bacnet_cov_worker.py`).
   - Executes `multi_protocol_simulator.py` via `[[inputs.execd]]` implementing Stage 1 Exception/Deadband filtering (`ExcDev` and `ExcMax`) and Stage 2 Swinging Door Trending (`CompDev` and `CompMax`).
2. **Pillar 2 — Immutable Telemetry Archive (`clickhouse-archive`):**
   - `clickhouse/clickhouse-server:24.8-alpine` database `pi_historian`.
   - Table `pi_historian.sensor_data` (`ENGINE = MergeTree() PARTITION BY toYYYYMM(ts) ORDER BY (tag_id, ts)`):
     - `tag_id UInt32 CODEC(Delta, ZSTD(1))`
     - `ts DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1))`
     - `val Float64 CODEC(Gorilla, ZSTD(1))`
     - `str_val LowCardinality(String) DEFAULT '' CODEC(ZSTD(1))`
     - `quality UInt8 DEFAULT 192 CODEC(T64, ZSTD(1))`
     - `status_code UInt16 DEFAULT 0 CODEC(T64, ZSTD(1))`
   - Real-time 1-minute rollup table `pi_historian.sensor_rollup_1m` (`AggregatingMergeTree()`) populated by `mv_sensor_rollup_1m` (`WHERE quality >= 192`).
   - In-memory dictionary `pi_historian.pg_asset_tags` (`LAYOUT(FLAT()) LIFETIME(MIN 5 MAX 15)`) and external table `pi_historian.pg_event_frames`.
3. **Pillar 3 — PostgreSQL 16 Part 11 Control Plane, FastAPI, AVEVA PI Parity Engine & Pydantic AI / MCP (`postgres-control` + `historian-api`):**
   - PostgreSQL 16 extensions: `ltree`, `btree_gist`, `pgcrypto`.
   - Tables: `asset_templates`, `assets` (GiST index on `asset_path`), `tags`, `event_frames`, `event_frame_templates`, `event_frame_signatures`, `digital_state_sets`, `manual_logger_entries`, `notification_rules`, `notification_deliveries`, `users`, and `part11_audit_log`.
   - Trigger `fn_enforce_part11_audit()` enforces `current_setting('app.actor_id', true)` and `current_setting('app.change_reason', true)` and computes `row_hash = encode(digest(prev_hash || recorded_at::text || actor_id || operation || coalesce(new_payload::text, ''), 'sha256'), 'hex')`.
   - Trigger `fn_prevent_audit_tampering()` blocks `UPDATE`, `DELETE`, and `TRUNCATE` on `part11_audit_log`.
   - AVEVA PI System Parity Engine (`pi_parity_engine.py`) provides full PI DataLink (`PICurrVal`, `PIArcVal`, `PICompDat`, `PIAdvCalcDat`, `PITimeFilter`), PI Web API `StreamSets`, GxP calculations (`MKT`, `F0`, `SQC`), Golden Batch overlay, AF Template auto-instantiation, UOM conversion, PI Manual Logger, `TrueFor` Event Frame backfill, multi-stage e-signatures, and PI Notifications.
   - Pydantic AI Co-Pilot (`gxp_ai_agent.py`) & `gxphistorian-mcp` (`mcp_server.py`) provide read-only deterministic tools, progressive disclosure capabilities (`part11-forensics`, `brownfield-onboarding`), and human-in-the-loop `ApprovalRequired` (`DeferredToolRequests`) Part 11 change control.
4. **Pillar 4 — Operator HMI & Excel DataLink (`grafana-vision` + `excel-datalink-client`):**
   - Grafana OSS 11.2.0 pre-provisioned with `clickhouse_core` and `postgres_control` datasources and the asset-relative dashboard `GxPHistorian Vision — GxP Bioreactor & Cleanroom HMI`.
   - Excel DataLink UDF module (`gxphistorian_datalink_udf.py`) with 8 worksheet functions and native Power Query CSV endpoint (`/api/v1/datalink/sampled?format=csv`).

