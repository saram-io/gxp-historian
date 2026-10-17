# .antigravity/rules.md — GxPHistorian GxP Industrial Historian Guardrails

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

4. **Brand & Identifier Invariant (`GxPHistorian`):**
   - Always use the exact casing **`GxPHistorian`** (capital `G`, lowercase `x`, capital `P`, capital `H`) in titles and prose. Never use deprecated names (`OpenPI`, `OpenHistorian`) or miscased variants (`GxpHistorian`).
   - Use lowercase `gxphistorian` for filenames, Grafana dashboard UIDs (`gxphistorian-gxp-bioreactor-hmi`), and Cloudflare Workers names (`gxphistorian-docs`).
   - Use uppercase `GXPHISTORIAN` for Excel DataLink UDFs (`=GXPHISTORIAN_SAMPLED`, `=GXPHISTORIAN_PLOT_VALUES`, `=GXPHISTORIAN_EVENT_SUMMARY`) and GMP Validation Binder document IDs (`VMP-GXPHISTORIAN-2026-001` through `VSR-GXPHISTORIAN-2026-008`).

5. **Validation Binder & Documentation Site Synchronization Gate:**
   - Whenever modifying `docs/*.md`, `provisioning/grafana/dashboards/`, or `gxp-validation-package/`, always run the full synchronization pipeline before completing the task:
     1. When adding new `docs/*.md` files, `docs/images/<subdir>/*.svg` diagrams, or `docs/images/photos/*.jpg` product photos, register them in `docs-site/scripts/sync-docs.mjs` (`DOC_MAPPINGS`, `LINK_REWRITES`, and static asset copy), `docs-site/astro.config.mjs` (sidebar), and `README.md`.
     2. If Grafana dashboards changed, restart Grafana (`docker compose restart grafana-vision`) and run `.venv/bin/pytest -v` to update `gxp-validation-package/evidence/oq_execution_results.json`.
     3. Regenerate the 8-document GMP binder and HTML artifact: `.venv/bin/python3 gxp-validation-package/generate_gmp_binder.py`.
     4. Sync and build the Astro Starlight documentation site: `pnpm --dir docs-site build` (which runs `node scripts/sync-docs.mjs && astro build`).
     5. When deploying the documentation site to Cloudflare Workers (`https://gxphistorian-docs.cloud-expert1666.workers.dev`), run `npx wrangler deploy` inside `docs-site/`.
   - Never mark a phase complete until all terminal verification commands succeed with zero errors.

6. **Instrument & Connector Documentation Standards (`docs/` & `docs-site/`):**
   - Every biopharma instrument tutorial and hardware/software connector guide MUST include:
     1. **Photorealistic Product Photo Galleries (`docs/images/photos/*.jpg`) & Visual SVG Wiring Diagrams (`docs/images/{instruments,connectors}/*.svg`):** Show both photorealistic hardware/instrument photography and vector schematic diagrams with rear-panel port callouts, pinouts (`RJ45`, `M12 D/X/A-Coded`, `DB9`, `RS-232`, `RS-485`, `4–20 mA`), and protocol packet/register anatomy.
     2. **Non-Technical Step-by-Step Setup Walkthroughs:** Detail exact cables/gateways to buy, physical ports to plug into (highlighting internal PLC I/O ports never to unplug), touchscreen/software menu click-paths, and 1-line network test commands.
     3. **Direct Official Vendor Product URLs:** Link every mentioned instrument, DCS/SCADA platform, and industrial gateway to its canonical manufacturer URL (never use search redirect URLs).