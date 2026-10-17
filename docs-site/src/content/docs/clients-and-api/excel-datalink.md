---
title: Excel DataLink Client (Power Query & UDFs)
description: Replace proprietary OSIsoft PI DataLink in Microsoft Excel using Zero-Install Power Query CSV streams or xlwings Worksheet User-Defined Functions.
---

The `excel-datalink-client/` directory provides two GxP-compliant pathways for Process Engineers, MSAT Scientists, and Quality Assurance personnel to pull time-series telemetry, interpolated batch samples, and signed ISA-88 Event Frame summaries directly into **Microsoft Excel** without proprietary OSIsoft PI DataLink client licenses.

---

## Option 1: Zero-Install Native Excel Power Query (`Get Data -> From Web`)

No Excel add-ins, macros, or Python installation are required on the user's Windows or macOS workstation.

### Step-by-Step Instructions

1. Open **Microsoft Excel** and navigate to **Data** $\rightarrow$ **Get Data** $\rightarrow$ **From Other Sources** $\rightarrow$ **From Web**.
2. Enter the GxPHistorian DataLink CSV endpoint URL:
   - **Continuous Analog Tag (`is_step_tag = false`, Linear Interpolation):**
     ```text
     http://localhost:8020/api/v1/datalink/sampled?tag_name=BR201_TEMP_PV&step_seconds=60&format=csv
     ```
   - **Discrete Step Tag (`is_step_tag = true`, Last Observation Carried Forward / LOCF):**
     ```text
     http://localhost:8020/api/v1/datalink/sampled?tag_name=BR201_AGIT_STATE&step_seconds=60&format=csv
     ```
3. Click **Load** to populate an auto-refreshing Excel table filtered strictly on Good OPC quality (`quality >= 192`).

### Returned CSV Columns

```csv
ts,tag_id,tag_name,asset_path,val,eng_units,interpolation_mode,quality_filter
2026-10-17T12:00:00Z,101,BR201_TEMP_PV,BioCorp.Fremont.USP.Bioreactor_201,37.02,degC,LINEAR,quality>=192
2026-10-17T12:01:00Z,101,BR201_TEMP_PV,BioCorp.Fremont.USP.Bioreactor_201,37.15,degC,LINEAR,quality>=192
```

---

## Option 2: `xlwings` Worksheet User-Defined Functions (UDFs)

`excel-datalink-client/gxphistorian_datalink_udf.py` provides drop-in worksheet formulas that mirror legacy PI DataLink functions (`=PISampDat`, `=PIPlotValues`, and Event Frame tables).

### Workstation Setup

```bash
pip install xlwings httpx
xlwings addin install
```

### Available Excel Formulas

| GxPHistorian Excel Formula | Legacy PI DataLink Equivalent | Behavior & Regulatory Controls |
| :--- | :--- | :--- |
| `=GXPHISTORIAN_SAMPLED(tag_name, start_time, end_time, step_seconds)` | `=PISampDat(...)` | Inspects `is_step_tag` in PostgreSQL: applies time-weighted `LINEAR` interpolation when `FALSE` and `LOCF` integer step interpolation when `TRUE`. Always enforces `quality >= 192`. |
| `=GXPHISTORIAN_PLOT_VALUES(tag_name, start_time, end_time, intervals)` | `=PIPlotValues(...)` | Calls ClickHouse `largestTriangleThreeBuckets(intervals)(ts, val)` (`WHERE quality >= 192`) enriched with `pg_asset_tags` dictionary metadata. |
| `=GXPHISTORIAN_EVENT_SUMMARY(event_name_filter)` | PI Event Frame Table | Returns the Event Frame window, `captured_metrics` JSONB snapshot (`peak_val`, `avg_val`, `min_val`), and 21 CFR Part 11 signature block (`signed_by`, `signature_meaning`, `signature_hash`). |

### Example Worksheet Formulas

```text
=GXPHISTORIAN_SAMPLED("BR201_TEMP_PV", "2026-10-17T12:00:00Z", "2026-10-17T13:00:00Z", 60)

=GXPHISTORIAN_PLOT_VALUES("CHROM01_UV280_PV", "2026-10-17T12:00:00Z", "2026-10-17T13:00:00Z", 500)

=GXPHISTORIAN_EVENT_SUMMARY("BR201_TEMP_PV")
```

---

## Option 3: Command-Line CSV Export Verification

`gxphistorian_datalink_udf.py` can also be executed directly from the terminal for batch reporting or automated qualification checks:

```bash
.venv/bin/python3 excel-datalink-client/gxphistorian_datalink_udf.py \
  --api-url http://localhost:8020 \
  --tag BR201_TEMP_PV \
  --step-seconds 60
```
