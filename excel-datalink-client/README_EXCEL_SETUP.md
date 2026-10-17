# GxPHistorian DataLink for Microsoft Excel (PI DataLink Replacement)

This directory provides two GxP-compliant ways for Process Engineers and MSAT Scientists to pull time-series telemetry, interpolated batch samples, and signed ISA-88 Event Frame summaries into Microsoft Excel without proprietary OSIsoft PI DataLink client licenses.

---

## Option 1: Zero-Install Native Excel Power Query (`Get Data -> From Web`)

No Excel add-ins or Python installation are required on the user's workstation.

1. Open **Microsoft Excel** and navigate to **Data** -> **Get Data** -> **From Other Sources** -> **From Web**.
2. Enter the Historian DataLink CSV endpoint URL:
   - Continuous Analog Tag (Linear Interpolation via ClickHouse `WITH FILL ... INTERPOLATE`):
     ```text
     http://localhost:8000/api/v1/datalink/sampled?tag_name=BR201_TEMP_PV&step_seconds=60&format=csv
     ```
   - Discrete Step Tag (Last Observation Carried Forward / LOCF integer states):
     ```text
     http://localhost:8000/api/v1/datalink/sampled?tag_name=BR201_AGIT_STATE&step_seconds=60&format=csv
     ```
   *(Note: If accessing via the host-mapped Docker port, use `http://localhost:8020/api/v1/datalink/sampled?tag_name=BR201_TEMP_PV&step_seconds=60&format=csv`.)*
3. Click **Load** to populate an auto-refreshing Excel table filtered strictly on good OPC quality (`quality >= 192`).

---

## Option 2: `xlwings` Worksheet User-Defined Functions (UDFs)

[`gxphistorian_datalink_udf.py`](file:///home/d3lee/my-repos/clickhouse-historian/excel-datalink-client/gxphistorian_datalink_udf.py) provides drop-in worksheet formulas replacing legacy PI DataLink functions:

### Setup
```bash
pip install xlwings httpx
xlwings addin install
```

### Available Excel Formulas

1. **Sampled Data (`=PISampDat` Replacement)**
   ```excel
   =GXPHISTORIAN_SAMPLED("BR201_TEMP_PV", "2026-10-17T12:00:00Z", "2026-10-17T13:00:00Z", 60)
   ```
   - Automatically inspects `is_step_tag` in the PostgreSQL Control Plane:
     - `is_step_tag = FALSE`: Performs linear interpolation across the requested interval step.
     - `is_step_tag = TRUE`: Performs Last Observation Carried Forward (LOCF) so discrete equipment states (`0`, `1`, `2`) never produce fractional decimals.

2. **Visual Downsampled Plot Values (`=PIPlotValues` Replacement)**
   ```excel
   =GXPHISTORIAN_PLOT_VALUES("CHROM_UV280_PV", "2026-10-17T12:00:00Z", "2026-10-17T13:00:00Z", 500)
   ```
   - Calls ClickHouse's native `largestTriangleThreeBuckets(500)(ts, val)` (`WHERE quality >= 192`) enriched with `pg_asset_tags` dictionary metadata.

3. **ISA-88 Event Frame & Part 11 Signature Summary**
   ```excel
   =GXPHISTORIAN_EVENT_SUMMARY("BR201_TEMP_PV_High_Limit_Excursion")
   ```
   - Returns the Event Frame window, `captured_metrics` JSONB snapshot (`avg_val`, `min_val`, `max_val`), and 21 CFR Part 11 electronic signature block (`signed_by`, `signature_meaning`, `signature_hash`).
