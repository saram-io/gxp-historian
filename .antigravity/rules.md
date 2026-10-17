# .antigravity/rules.md — GxP Open-Source Industrial Historian Guardrails

1. **4-Pillar Architecture Invariant:**
   - **Pillar 1 (`edge-collector`):** Telegraf + Python `execd` workers normalize all protocols (OPC UA, BACnet/IP, Modbus, Siemens S7, and Windows OPC DA HTTP batches) into `(tag_id, ts, val, quality, status_code)` with disk-backed store-and-forward buffering.
   - **Pillar 2 (`clickhouse-archive`):** ClickHouse Server (`Apache-2.0`) is the immutable time-series, real-time rollup (`AggregatingMergeTree`), visual downsampling (`largestTriangleThreeBuckets`), and S3/Parquet lakehouse engine. NEVER execute `ALTER TABLE ... UPDATE/DELETE` on ClickHouse telemetry tables.
   - **Pillar 3 (`postgres-control` + `historian-api`):** Vanilla PostgreSQL 16 holds all mutable state: ISA-95 Asset Hierarchy (`ltree`), Tag Catalog (`tags`), ISA-88 Event Frames (`event_frames`), and the 21 CFR Part 11 Audit Trail (`part11_audit_log`). ClickHouse bridges to PostgreSQL via an in-memory `DICTIONARY` and `PostgreSQL` table engine. FastAPI serves the unified REST API, Event Frame state machine, and Excel DataLink endpoints.
   - **Pillar 4 (`grafana-vision`):** Grafana OSS renders asset-relative dashboards and Event Frame annotations.

2. **Signal Quality & Interpolation Discipline:**
   - OPC Quality codes are mandatory: `192` = Good, `64` = Uncertain, `0` = Bad.
   - Every analytical rollup, Event Frame summary, and Excel DataLink interpolation query MUST filter `WHERE quality >= 192`.
   - Respect tag interpolation mode (`is_step_tag = true` -> Last Observation Carried Forward / step interpolation; `is_step_tag = false` -> Linear interpolation).

3. **21 CFR Part 11 & ALCOA+ Technical Controls:**
   - All mutations (`INSERT`, `UPDATE`, `DELETE`) on `asset_templates`, `assets`, `tags`, and `event_frames` in PostgreSQL MUST require session settings `app.actor_id` and `app.change_reason`. Missing context must raise a PostgreSQL exception.
   - `part11_audit_log` must compute a cryptographic `SHA-256` hash chain (`row_hash = encode(digest(prev_hash || recorded_at || actor_id || operation || coalesce(new_payload::text, ''), 'sha256'), 'hex')`) and enforce a `BEFORE UPDATE OR DELETE OR TRUNCATE` trigger that raises an exception unconditionally (even against superusers).

4. **Verification Gate:**
   - Never mark a phase complete until you have executed the specified terminal verification commands and confirmed zero errors.