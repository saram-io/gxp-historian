---
title: REST API Reference (historian-api)
description: Complete REST API documentation for the GxPHistorian FastAPI Control Plane (asset tree, tag provisioning, LTTB trends, DataLink interpolation, ISA-88 Event Frames, Part 11 signatures, and Apache Parquet exports).
---

The GxPHistorian Control Plane (`historian-api`, implemented in `app/main.py`) exposes a unified GxP REST API on internal port `8000` (mapped to host port `8020` by default in `.env`).

Interactive OpenAPI / Swagger UI documentation is available at:
- **`http://localhost:8020/docs`**

---

## Endpoint Summary

| Method & Path | PI System Equivalent | Description | Part 11 Attribution Required? |
| :--- | :--- | :--- | :--- |
| `GET /api/v1/health` | PI SMT System Health | Checks PostgreSQL & ClickHouse connectivity, audit log count, and telemetry row count. | No |
| `GET /api/v1/assets/tree` | PI Asset Framework (PI AF) | Returns the ISA-95 `ltree` asset hierarchy and associated tags. | No |
| `POST /api/v1/tags` | PI Point Builder / AF Attribute | Provisions or updates a GxP tag with `X-Actor-Id` and `X-Change-Reason` attribution. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `GET /api/v1/trends/plot-values` | PI Vision `PlotValues` | High-speed `largestTriangleThreeBuckets` (LTTB) downsampled visual trend (`quality >= 192`). | No |
| `GET /api/v1/datalink/sampled` | PI DataLink `PISampDat` | Evenly spaced sampled data (`LINEAR` vs. `LOCF` step) in `json` or `csv` format. | No |
| `GET /api/v1/event-frames` | PI Event Frame Search | Lists active, closed, and signed ISA-88 Event Frames with captured KPI metrics. | No |
| `POST /api/v1/event-frames/evaluate` | PI Asset Analytics | Scans ClickHouse `quality >= 192` telemetry against tag limits to open/update Event Frames. | Optional (defaults to `event_frame_engine`) |
| `POST /api/v1/event-frames/{event_id}/sign` | Part 11 E-Signature | Verifies dual-challenge credentials (`§11.200`) and applies an `HMAC-SHA256` signature. | **Yes** (`user_id`, `password`, `signature_meaning`) |
| `POST /api/v1/lakehouse/export-parquet` | PI Integrator for BA | Exports Snappy-compressed Apache Parquet files enriched with ISA-95 metadata. | No |
| `GET /api/v1/audit-trail/verify` | Part 11 Audit Verifier | Recomputes and verifies every SHA-256 hash link in `part11_audit_log` from genesis. | No |
| `GET /api/v1/ai/mcp/manifest` | PI Web API / AI Gateway | Returns the `gxphistorian-mcp` server manifest (6 deterministic tools & 3 `gxphistorian://` resources) plus Pydantic AI agent metadata. | No |
| `POST /api/v1/ai/event-frames/{event_id}/investigate` | Batch Excursion Co-Pilot | Runs `gxp_deviation_investigator_agent` to generate a structured `DeviationInvestigationBrief` over `quality >= 192` telemetry (advisory only; never calls `/sign`). | No (Read-only advisory) |
| `POST /api/v1/ai/copilot/propose-tag` | Tag Builder Co-Pilot | Stages a validated tag provisioning proposal and pauses behind `ApprovalRequired` (`DeferredToolRequests`) until explicit human Part 11 approval. | **Yes** (Requires human `approved=true`, `actor_id`, `change_reason`) |
| `GET /api/v1/datalink/current` | PI DataLink `PICurrVal` | Latest snapshot reading (`WHERE quality >= 192`) with optional canonical UOM conversion and Digital State translation. | No |
| `GET /api/v1/datalink/archive-value` | PI DataLink `PIArcVal` | Exact timestamp lookup supporting `INTERPOLATED`, `PREVIOUS` (LOCF), `NEXT`, `EXACT`, and `AUTO` modes. | No |
| `GET /api/v1/datalink/recorded` | PI DataLink `PICompDat` | Raw compressed archive events in `[start_time, end_time]` with optional `INSIDE`/`OUTSIDE` bounds filtering. | No |
| `GET /api/v1/datalink/calculated` | PI DataLink `PIAdvCalcDat` | Interval summaries (`total`, `average`, `minimum`, `maximum`, `range`, `stddev`, `count`) with `TIME_WEIGHTED` trapezoidal integration vs. `EVENT_WEIGHTED`. | No |
| `GET /api/v1/datalink/time-filter` | PI DataLink `PITimeFilter` | Evaluates boolean expressions (`>= 37.5`, `== 1`) and returns `seconds_true` & `percent_true`. | No |
| `POST /api/v1/streamsets/end` | PI Web API `StreamSets/GetEnd` | Bulk latest snapshot query across an entire ISA-95 `asset_path` subtree or `tag_names` list. | No |
| `POST /api/v1/streamsets/interpolated` | PI Web API `StreamSets/GetInterpolated` | Bulk synchronized multi-tag interpolation grid (`LINEAR` + `LOCF`) in a single HTTP request. | No |
| `GET /api/v1/analytics/mkt` | PI Analysis Service (ICH Q1A MKT) | Computes Arrhenius Mean Kinetic Temperature ($\text{MKT}$, $\Delta H = 83.144\text{ kJ/mol}$). | No |
| `GET /api/v1/analytics/f0-lethality` | PI Analysis Service (USP `<1229>` $F_0$) | Computes trapezoidal cumulative steam sterilization lethality $F_0$ ($T_{\text{ref}}=121.11\,^\circ\text{C}$, $z=10\,^\circ\text{C}$). | No |
| `GET /api/v1/analytics/sqc` | PI SQC / Western Electric SPC | Evaluates 4 Western Electric SPC rules (`3σ`, `2-of-3 2σ`, `4-of-5 1σ`, `8-consecutive same side`) and $C_p$/$C_{pk}$. | No |
| `POST /api/v1/batches/compare` | PI BatchView Golden Batch Overlay | Aligns multiple batch Event Frames on relative elapsed hours (`T+0.0h`) and computes `mean ± 2 SD` reference envelope. | No |
| `GET /api/v1/af/uom` & `POST /api/v1/af/uom/convert` | PI AF UOM Database | Lists canonical engineering unit classes and converts values across `Temperature`, `Pressure`, `Flow`, `Conductivity`, `Mass`, and `Volume`. | No |
| `GET /api/v1/af/digital-state-sets` | PI Digital State Sets | Returns discrete state enumerations (`ISA88_Phase_State`, `Valve_Discrete_State`, `Cleanroom_Door_Interlock`). | No |
| `POST /api/v1/assets/instantiate-template` | PI AF Template Auto-Instantiation | Instantiates an asset in `assets` and auto-creates all standardized tags from `asset_templates.default_attributes`. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `GET` / `POST /api/v1/manual-logger/entries` | PI Manual Logger | Records 21 CFR Part 11 attributed manual/offline lab entries in PostgreSQL and dual-writes to ClickHouse `sensor_data`. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `POST /api/v1/compression/swinging-door-evaluate` | PI Server Stage 2 `CompDev` | Evaluates Stage 2 Swinging Door slope-envelope compression (`CompDev`, `CompMax`, `CompMin`) over a sample stream. | No |
| `POST /api/v1/event-frames/backfill` | PI Analysis Backfill / Recalculation | Scans historical telemetry with `TrueFor` debounce (`true_for_seconds`) to backfill excursion Event Frames. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `GET /api/v1/event-frames/{event_id}/signatures` | Part 11 Multi-Stage Signatures | Returns the ordered chain of multi-stage electronic signatures (`Operator` $\rightarrow$ `Supervisor` $\rightarrow$ `QA`). | No |
| `GET /api/v1/notifications/channels` | PI Notifications Delivery Channels | Lists supported multi-channel delivery architectures (`EMAIL`, `SMS`, `MOBILE_PUSH`, `WEBHOOK`) and payload schemas. | No |
| `GET` / `POST /api/v1/notifications/rules` | PI AF Notification Rules | Lists or creates multi-channel notification rules with `%Parameter%` templates, `non_repetition_minutes`, `resend_interval_minutes`, and `escalation_team`. | **Yes** (`X-Actor-Id`, `X-Change-Reason` on `POST`) |
| `POST /api/v1/notifications/preview` | PI System Explorer Message Preview | Renders a live preview across Rich HTML Email, 160-char GSM-7 SMS, Mobile Push (`APNs`/`FCM`/`PagerDuty`), and Teams Adaptive Cards. | No |
| `POST /api/v1/notifications/evaluate` | PI Notifications Service | Evaluates open/closed Event Frames, dispatches `TRIGGER`, `ESCALATION`, and `RECOVERY_CLOSE` alerts, and honors `non_repetition_minutes`. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `POST /api/v1/notifications/acknowledge/{event_id}` | PI Vision / Email Event Acknowledgment | Records a 21 CFR Part 11 attributed operator acknowledgment and halts further `ESCALATION` dispatches. | **Yes** (`X-Actor-Id`, `X-Change-Reason`) |
| `POST /api/v1/notifications/sms-webhook` | TopView / Twilio Two-Way SMS ACK | Parses inbound `"ACK <EventShortId> [notes]"` SMS replies from operator mobile numbers and halts escalations with Part 11 attribution. | Automatic (`sms_operator:<from>`) |
| `GET /api/v1/notifications/deliveries` | PI Notification Delivery History | Lists WORM-audited dispatches filterable by `delivery_channel` (`EMAIL`, `SMS`, `MOBILE_PUSH`, `WEBHOOK`) and `notification_phase`. | No |

---

## 1. System Health (`GET /api/v1/health`)

```bash
curl -s http://localhost:8020/api/v1/health | jq .
```

```json
{
  "status": "healthy",
  "postgres_control_plane": "connected",
  "clickhouse_archive": "connected",
  "part11_audit_records": 220,
  "sensor_data_rows": 1450
}
```

---

## 2. Browse ISA-95 Asset Hierarchy (`GET /api/v1/assets/tree`)

Queries PostgreSQL `assets` (using `ltree` subtree filtering when `root_path` is provided) and returns each asset with its configured tags.

### Query Parameters
- `root_path` *(optional)*: Filter subtree using PostgreSQL `ltree` `<@` operator (e.g., `BioCorp.Fremont.USP`).

```bash
curl -s "http://localhost:8020/api/v1/assets/tree?root_path=BioCorp.Fremont.USP" | jq .
```

---

## 3. Provision a New Tag (`POST /api/v1/tags`)

Creates or updates a tag in PostgreSQL `tags`. Requires 21 CFR Part 11 attribution headers (`X-Actor-Id` and `X-Change-Reason`). Omitting either header returns **`HTTP 400 Bad Request`**.

```bash
curl -s -X POST http://localhost:8020/api/v1/tags \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: operator_01" \
  -H "X-Change-Reason: Provision Dissolved Oxygen sensor for Bioreactor 201" \
  -d '{
    "tag_id": 104,
    "tag_name": "BR201_DO_PV",
    "asset_id": 1,
    "attribute_name": "Dissolved_Oxygen_PV",
    "eng_units": "%Sat",
    "is_step_tag": false,
    "exc_dev": 0.1,
    "low_limit": 20.0,
    "high_limit": 100.0,
    "source_protocol": "OPC_UA"
  }' | jq .
```

---

## 4. LTTB Downsampled Visual Trend (`GET /api/v1/trends/plot-values`)

Executes ClickHouse's native `largestTriangleThreeBuckets(intervals)(ts, val)` over good-quality telemetry (`WHERE quality >= 192`) and enriches the response from the in-memory `pi_historian.pg_asset_tags` dictionary. Preserves transient UV280 peaks and thermal spikes (`URS-014` / `OQ-09`).

### Query Parameters
- `tag_id` *(int)* or `tag_name` *(string)*
- `start_time` *(ISO-8601 UTC string, optional)*
- `end_time` *(ISO-8601 UTC string, optional)*
- `intervals` *(int, default `200`, range `10`–`5000`)*

```bash
curl -s "http://localhost:8020/api/v1/trends/plot-values?tag_id=101&start_time=2026-10-17T00:00:00Z&end_time=2026-10-18T00:00:00Z&intervals=200" | jq .
```

---

## 5. PI DataLink Sampled Interpolation (`GET /api/v1/datalink/sampled`)

Replaces `=PISampDat()`. Automatically inspects `is_step_tag` in PostgreSQL:
- **`is_step_tag = false` (`LINEAR`):** Performs time-weighted linear interpolation between bounding good-quality readings (`WHERE quality >= 192`).
- **`is_step_tag = true` (`LOCF`):** Performs Last Observation Carried Forward step interpolation so discrete states (`0`, `1`, `2`) never synthesize fractional values.

### Query Parameters
- `tag_name` *(string)* or `tag_id` *(int)*
- `start_time` *(ISO-8601 UTC string, optional)*
- `end_time` *(ISO-8601 UTC string, optional)*
- `step_seconds` *(int, default `60`)*
- `format` (`json` or `csv`, default `json`)

```bash
# Continuous analog tag (Linear interpolation) in CSV format for Excel Power Query
curl -s "http://localhost:8020/api/v1/datalink/sampled?tag_name=BR201_TEMP_PV&start_time=2026-10-17T12:00:00Z&end_time=2026-10-17T12:10:00Z&step_seconds=60&format=csv"

# Discrete step tag (LOCF step interpolation) in JSON format
curl -s "http://localhost:8020/api/v1/datalink/sampled?tag_name=BR201_AGIT_STATE&start_time=2026-10-17T12:00:00Z&end_time=2026-10-17T12:10:00Z&step_seconds=60&format=json" | jq .
```

---

## 6. Evaluate & Sign ISA-88 Event Frames (`/api/v1/event-frames/*`)

### Trigger Limit Excursion Evaluation (`POST /api/v1/event-frames/evaluate`)

```bash
curl -s -X POST "http://localhost:8020/api/v1/event-frames/evaluate?lookback_minutes=15" | jq .
```

### Execute 21 CFR Part 11 Electronic Signature (`POST /api/v1/event-frames/{event_id}/sign`)

Verifies `user_id` and `password` against `pgcrypto` bcrypt hashes in PostgreSQL `users` (`§11.200`), computes an `HMAC-SHA256` signature over `(event_id, user_id, signature_meaning, signed_at)`, updates `event_frames`, appends to `event_frame_signatures` for multi-stage sequential approvals, and logs the change in `part11_audit_log`.

```bash
curl -s -X POST "http://localhost:8020/api/v1/event-frames/<EVENT_UUID>/sign" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: qa_approver_01" \
  -H "X-Change-Reason: Formal QA review and disposition of thermal excursion" \
  -d '{
    "user_id": "qa_approver_01",
    "password": "QA_Approve_2026!",
    "signature_meaning": "Excursion Investigation Reviewed",
    "change_reason": "Formal QA review and disposition of thermal excursion"
  }' | jq .
```

---

## 7. Verify Cryptographic SHA-256 Audit Chain (`GET /api/v1/audit-trail/verify`)

```bash
curl -s http://localhost:8020/api/v1/audit-trail/verify | jq .
```

```json
{
  "chain_valid": true,
  "verified_records": 220,
  "genesis_anchor": "GENESIS_0000000000000000",
  "head_hash": "9a7f3c8e2b...",
  "broken_links": []
}
```

---

## 8. Zero-ETL Apache Parquet Lakehouse Export (`POST /api/v1/lakehouse/export-parquet`)

Exports good-quality (`quality >= 192`) telemetry enriched with `tag_name`, `asset_path`, and `eng_units` to a Snappy-compressed `.parquet` file in `/app/exports` (`./exports/` on the host).

```bash
curl -s -X POST http://localhost:8020/api/v1/lakehouse/export-parquet \
  -H "Content-Type: application/json" \
  -d '{
    "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
    "start_time": "2026-10-17T00:00:00Z",
    "end_time": "2026-10-18T00:00:00Z"
  }' | jq .
```

---

## 9. Pydantic AI GxP Co-Pilot & `gxphistorian-mcp` Server (`/api/v1/ai/*`)

For complete architectural details, Capabilities on Demand (`defer_loading=True`), and `FastMCP` client configuration, see **[Pydantic AI Co-Pilot & MCP Server](/docs/clients-and-api/pydantic-ai-and-mcp/)**.

```bash
# Inspect gxphistorian-mcp manifest
curl -s http://localhost:8020/api/v1/ai/mcp/manifest | jq .

# Generate advisory ISA-88 Excursion Investigation Brief (quality >= 192; never calls /sign)
curl -s -X POST "http://localhost:8020/api/v1/ai/event-frames/<EVENT_UUID>/investigate" \
  -H "Content-Type: application/json" \
  -d '{"use_deterministic_fallback": false}' | jq .

# Stage Part 11 Tag Proposal (returns HTTP 202 Accepted DeferredToolRequests until approved=true)
curl -s -X POST http://localhost:8020/api/v1/ai/copilot/propose-tag \
  -H "Content-Type: application/json" \
  -d '{
    "tag_id": 105,
    "tag_name": "BR201_PRESS_PV",
    "asset_id": 1,
    "attribute_name": "Headspace_Pressure_PV",
    "eng_units": "bar",
    "is_step_tag": false,
    "exc_dev": 0.02,
    "low_limit": 0.0,
    "high_limit": 2.5,
    "source_protocol": "OPC_UA",
    "approved": false
  }' | jq .
```

---

## 10. Full PI DataLink & PI Web API StreamSets Parity (`URS-018` / `OQ-13`)

Implemented in `app/pi_parity_engine.py`, these endpoints provide 1-to-1 parity with the complete OSIsoft / AVEVA PI DataLink function library and PI Web API `StreamSets`:

```bash
# 1. PICurrVal — Current Snapshot Value with on-the-fly UOM conversion (degC -> degF)
curl -s "http://localhost:8020/api/v1/datalink/current?tag_name=BR201_TEMP_PV&target_uom=degF" | jq .

# 2. PIArcVal — Single-timestamp Archive Value (AUTO, INTERPOLATED, PREVIOUS/LOCF, NEXT, EXACT)
curl -s "http://localhost:8020/api/v1/datalink/archive-value?tag_name=BR201_TEMP_PV&timestamp=2026-01-16T10:02:30Z&mode=INTERPOLATED" | jq .

# 3. PICompDat — Compressed/Recorded Archive Events with optional INSIDE/OUTSIDE bounds filter
curl -s "http://localhost:8020/api/v1/datalink/recorded?tag_name=BR201_TEMP_PV&start_time=2026-01-16T10:00:00Z&end_time=2026-01-16T10:15:00Z&filter_mode=INSIDE" | jq .

# 4. PIAdvCalcDat — Time-Weighted vs. Event-Weighted Calculated Summaries
curl -s "http://localhost:8020/api/v1/datalink/calculated?tag_name=BR201_TEMP_PV&start_time=2026-01-16T10:00:00Z&end_time=2026-01-16T10:10:00Z&interval_seconds=600&calculation_basis=TIME_WEIGHTED" | jq .

# 5. PITimeFilter — Time-True Duration & Percentage in State
curl -s "http://localhost:8020/api/v1/datalink/time-filter?tag_name=BR201_TEMP_PV&start_time=2026-01-16T10:00:00Z&end_time=2026-01-16T10:10:00Z&operator=%3E%3D&threshold=37.5" | jq .

# 6. PI Web API StreamSets — Bulk Multi-Tag Snapshot & Synchronized Interpolation
curl -s -X POST http://localhost:8020/api/v1/streamsets/end \
  -H "Content-Type: application/json" \
  -d '{"asset_path": "BioCorp.Fremont.USP.Bioreactor_201"}' | jq .

curl -s -X POST http://localhost:8020/api/v1/streamsets/interpolated \
  -H "Content-Type: application/json" \
  -d '{
    "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
    "start_time": "2026-01-16T10:00:00Z",
    "end_time": "2026-01-16T10:10:00Z",
    "step_seconds": 120
  }' | jq .
```

---

## 11. GxP Calculation Engine & Golden Batch Overlay (`URS-019` / `OQ-14`)

Provides native biopharma thermal/sterilization calculations (`MKT`, $F_0$), Western Electric Statistical Process Control (`SQC`), and relative elapsed-hour (`T+0.0h`) Golden Batch trajectory alignment (`WHERE quality >= 192`):

```bash
# 1. ICH Q1A Mean Kinetic Temperature (MKT, ΔH = 83.144 kJ/mol)
curl -s "http://localhost:8020/api/v1/analytics/mkt?tag_name=BR201_TEMP_PV&start_time=2026-01-16T14:00:00Z&end_time=2026-01-16T14:09:00Z&activation_energy_kj_mol=83.144" | jq .

# 2. USP <1229> Steam Sterilization Lethality (F0 trapezoidal integration, Tref = 121.11°C, z = 10°C)
curl -s "http://localhost:8020/api/v1/analytics/f0-lethality?tag_name=BR201_TEMP_PV&start_time=2026-01-16T15:00:00Z&end_time=2026-01-16T15:15:00Z&target_f0_minutes=12.0" | jq .

# 3. Western Electric SQC SPC Rules (3σ, 2-of-3 2σ, 4-of-5 1σ, 8-consecutive same side) & Cp/Cpk
curl -s "http://localhost:8020/api/v1/analytics/sqc?tag_name=CHR401_UV280_ABS&start_time=2026-01-16T16:00:00Z&end_time=2026-01-16T16:19:00Z&target_mean=100.0&target_sigma=2.0" | jq .

# 4. PI BatchView Golden Batch Overlay (Relative elapsed-hour T+0.0h alignment & mean ± 2 SD envelope)
curl -s -X POST http://localhost:8020/api/v1/batches/compare \
  -H "Content-Type: application/json" \
  -d '{
    "event_ids": [1, 2],
    "tag_name": "BR201_TEMP_PV",
    "step_seconds": 300,
    "golden_event_id": 1
  }' | jq .
```

---

## 12. PI AF Template Auto-Instantiation, UOM & Manual Logger (`URS-020` / `OQ-15`)

```bash
# 1. Inspect Canonical UOM Registry & Convert Engineering Units
curl -s http://localhost:8020/api/v1/af/uom | jq .
curl -s -X POST http://localhost:8020/api/v1/af/uom/convert \
  -H "Content-Type: application/json" \
  -d '{"value": 100.0, "from_uom": "degC", "to_uom": "degF"}' | jq .

# 2. Inspect PI Digital State Sets
curl -s http://localhost:8020/api/v1/af/digital-state-sets | jq .

# 3. Auto-Instantiate an ISA-95 Asset & Standardized Tags from an AF Template
curl -s -X POST http://localhost:8020/api/v1/assets/instantiate-template \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: automation_eng_rlee" \
  -H "X-Change-Reason: Auto-instantiate Bioreactor 202 from GMP_Bioreactor_v1 template" \
  -d '{
    "template_name": "GMP_Bioreactor_v1",
    "asset_name": "Bioreactor 202",
    "asset_path": "BioCorp.Fremont.USP.Bioreactor_202",
    "parent_path": "BioCorp.Fremont.USP",
    "tag_prefix": "BR202",
    "base_tag_id": 2201,
    "source_protocol": "OPC_UA"
  }' | jq .

# 4. Record a 21 CFR Part 11 Manual Logger Entry (dual-written to PostgreSQL & ClickHouse sensor_data)
curl -s -X POST http://localhost:8020/api/v1/manual-logger/entries \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: operator_jdoe" \
  -H "X-Change-Reason: Offline benchtop pH verification grab sample" \
  -d '{
    "tag_name": "BR201_PH_PV",
    "sample_ts": "2026-01-16T18:00:00Z",
    "val": 7.12,
    "operator_notes": "Mettler SevenExcellence benchtop check",
    "verified_by": "qa_approver_msmith"
  }' | jq .
```

---

## 13. Stage 2 Swinging Door, `TrueFor` Backfill, Multi-Stage Signatures & PI Notifications (`URS-021` / `OQ-16`)

```bash
# 1. Evaluate Stage 2 Swinging Door Compression (CompDev, CompMax, CompMin)
curl -s -X POST http://localhost:8020/api/v1/compression/swinging-door-evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "comp_dev": 0.1,
    "comp_max_seconds": 600,
    "comp_min_seconds": 0,
    "samples": [
      {"ts": "2026-01-16T19:00:00Z", "val": 37.0, "quality": 192},
      {"ts": "2026-01-16T19:01:00Z", "val": 37.02, "quality": 192},
      {"ts": "2026-01-16T19:02:00Z", "val": 38.4, "quality": 192},
      {"ts": "2026-01-16T19:03:00Z", "val": 37.1, "quality": 192}
    ]
  }' | jq .

# 2. Historical Event Frame Backfill with TrueFor Debounce Filtering
curl -s -X POST http://localhost:8020/api/v1/event-frames/backfill \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: qa_approver_msmith" \
  -H "X-Change-Reason: Historical backfill of thermal excursions with 120s TrueFor debounce" \
  -d '{
    "tag_name": "BR201_TEMP_PV",
    "start_time": "2026-01-16T20:00:00Z",
    "end_time": "2026-01-16T20:15:00Z",
    "true_for_seconds": 120
  }' | jq .

# 3. Inspect Multi-Stage Electronic Signatures on an Event Frame
curl -s "http://localhost:8020/api/v1/event-frames/1/signatures" | jq .

# 4. Preview Multi-Channel PI Notification Payloads (HTML Email, 160-char SMS, Mobile Push APNs/FCM/PagerDuty)
curl -s -X POST http://localhost:8020/api/v1/notifications/preview \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Excursion_HIGH_BR201_TEMP_PV",
    "severity": "CRITICAL",
    "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
    "tag_name": "BR201_TEMP_PV",
    "peak_val": 39.42,
    "eng_units": "degC"
  }' | jq .

# 5. Evaluate PI Notification Rules (Trigger, Multi-Tier Escalation Teams & Send-on-Close)
curl -s -X POST http://localhost:8020/api/v1/notifications/evaluate \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: notification_engine" \
  -H "X-Change-Reason: Evaluate active GxP excursion rules across EMAIL, SMS, MOBILE_PUSH, and WEBHOOK" \
  -d '{"simulate_elapsed_minutes": 20.0, "respect_non_repetition": true, "dispatch_recovery_on_close": true}' | jq .

# 6. Acknowledge an Event Frame via REST or Two-Way SMS ("ACK <EventID>") to Halt Escalation
curl -s -X POST http://localhost:8020/api/v1/notifications/acknowledge/1 \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: operator_01" \
  -H "X-Change-Reason: Acknowledged BR201 high temperature excursion from mobile device" \
  -d '{"acknowledged_by": "operator_01", "channel": "MOBILE_PUSH", "notes": "Inspecting jacket valve"}' | jq .

curl -s -X POST http://localhost:8020/api/v1/notifications/sms-webhook \
  -H "Content-Type: application/json" \
  -d '{"From": "+14155550101", "Body": "ACK 1 Jacket cooling valve reset"}' | jq .

# 7. Inspect Audit-Logged Deliveries (Filterable by EMAIL, SMS, MOBILE_PUSH, WEBHOOK)
curl -s "http://localhost:8020/api/v1/notifications/deliveries?channel=SMS" | jq .

# 8. Retrieve Validated Hybrid Cloud Deployment Blueprints & Commercial Editions (AWS, Azure & Google Cloud)
curl -s "http://localhost:8020/api/v1/cloud/hybrid-blueprints?provider=aws&pattern=pattern_b_cloud_core" | jq .

# 9. Enroll a Purdue Level 2.5 Edge Collector Appliance & Verify URS-005 (>14-Day WAL Autonomy)
curl -s -X POST "http://localhost:8020/api/v1/cloud/edge-agents/heartbeat" \
  -H "Content-Type: application/json" \
  -H "X-Actor-Id: operator_01" \
  -H "X-Change-Reason: Enroll Purdue L2.5 DIN-Rail Edge Box for USP Suite 201" \
  -d '{
    "agent_id": "edge-fremont-usp-01",
    "site_path": "BioCorp.Fremont.USP.Bioreactor_201",
    "hardware_model": "Advantech UNO-2484G (512GB pSLC NVMe)",
    "deployment_pattern": "pattern_b_cloud_core",
    "cloud_provider": "aws",
    "wal_buffer_used_gb": 1.25,
    "wal_buffer_capacity_gb": 100.0,
    "active_tag_count": 25000,
    "mtls_cert_days_remaining": 84,
    "wan_link_status": "CONNECTED_MTLS_8443"
  }' | jq .

curl -s "http://localhost:8020/api/v1/cloud/edge-agents" | jq .

# 10. Calculate 10-Year Hot NVMe + 15-Year WORM Cloud Sizing & AVEVA PI TCO Savings
curl -s "http://localhost:8020/api/v1/cloud/tco-calculator?active_tags=25000&named_users=50&site_count=1&cloud_provider=aws" | jq .
```

For a comprehensive deep-dive into AVEVA PI System alerting architecture and `GxPHistorian` multi-channel setup, see **[PI Notifications: Email, SMS & Mobile Alerting](/docs/clients-and-api/pi-notifications-alerting/)** and **[Hybrid Cloud Deployment (AWS, Azure & GCP)](/docs/architecture/hybrid-cloud-deployment/)**.



