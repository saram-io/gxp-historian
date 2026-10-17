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

Verifies `user_id` and `password` against `pgcrypto` bcrypt hashes in PostgreSQL `users` (`§11.200`), computes an `HMAC-SHA256` signature over `(event_id, user_id, signature_meaning, signed_at)`, updates `event_frames`, and logs the change in `part11_audit_log`.

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
