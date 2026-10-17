---
title: Quickstart & Deployment
description: Deploy the 5-service OpenHistorian GxP stack via Docker Compose, inspect seeded ISA-95 assets and Part 11 users, and verify system health.
---

## Prerequisites

- **Docker Engine 24+** and **Docker Compose v2**
- **Python 3.11+** *(optional, for running the local `pytest` IQ/OQ qualification suite and GMP binder generator)*

---

## Step 1: Configure Environment & Launch the Stack

Copy the GxP environment template and start all 5 orchestrated services:

```bash
cp .env.example .env
docker compose up -d --build
```

Verify that all 5 containers (`postgres-control`, `clickhouse-archive`, `edge-collector`, `historian-api`, `grafana-vision`) are running and healthy:

```bash
docker compose ps
curl -s http://localhost:8020/api/v1/health | jq .
```

### Expected Health Response

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

## Step 2: Inspect Seeded GxP Assets, Tags & Part 11 Users

On initial startup, `init-postgres/01_control_plane_part11.sql` seeds the ISA-95 asset hierarchy, multi-protocol bioprocess tags, and 21 CFR Part 11 user accounts inside an attributed bootstrap transaction (`SET LOCAL app.actor_id = 'system_bootstrap'`).

### Seeded ISA-95 Assets (`assets`)

| Asset ID | Asset Name | ISA-95 `ltree` Asset Path | Template |
| :--- | :--- | :--- | :--- |
| `1` | `Bioreactor_201` | `BioCorp.Fremont.USP.Bioreactor_201` | `Bioreactor_USP_Template` |
| `2` | `Cleanroom_Suite_104` | `BioCorp.Fremont.Facilities.Cleanroom_Suite_104` | `Cleanroom_EMS_Template` |
| `3` | `Chrom_Skid_01` | `BioCorp.Fremont.DSP.Chrom_Skid_01` | `Chromatography_DSP_Template` |

### Seeded Multi-Protocol GxP Tags (`tags`)

| Tag ID | Tag Name | ISA-95 `ltree` Asset Path | Attribute | Units | Step Tag (`LOCF`) | Deadband (`exc_dev`) | Limits (`Low` / `High`) | Source Protocol |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `101` | `BR201_TEMP_PV` | `BioCorp.Fremont.USP.Bioreactor_201` | `Vessel_Temp_PV` | `degC` | `false` (`LINEAR`) | `0.05` | `35.0` / `38.0` | `OPC_UA` |
| `102` | `BR201_PH_PV` | `BioCorp.Fremont.USP.Bioreactor_201` | `Vessel_pH_PV` | `pH` | `false` (`LINEAR`) | `0.02` | `6.8` / `7.4` | `OPC_UA` |
| `103` | `BR201_AGIT_STATE` | `BioCorp.Fremont.USP.Bioreactor_201` | `Agitator_State` | `state` | `true` (`LOCF`) | `0.0` | `0.0` / `2.0` | `SIEMENS_S7` |
| `301` | `CR104_DIFF_PRESS` | `BioCorp.Fremont.Facilities.Cleanroom_Suite_104` | `Room_Diff_Pressure_PV` | `Pa` | `false` (`LINEAR`) | `0.5` | `12.5` / `50.0` | `BACNET_IP` |
| `401` | `CHROM01_UV280_PV` | `BioCorp.Fremont.DSP.Chrom_Skid_01` | `UV280_Absorbance_PV` | `mAU` | `false` (`LINEAR`) | `0.1` | `0.0` / `1000.0` | `OPC_DA` |

### Seeded 21 CFR Part 11 Accounts (`users`)

> [!NOTE]
> `init-postgres/01_control_plane_part11.sql` seeds bcrypt password hashes via `pgcrypto`, and `app/main.py` ensures qualification aliases are synchronized at startup.

| User ID | Full Name | Role | Qualification Password |
| :--- | :--- | :--- | :--- |
| `operator_01` | Sarah Jenkins (Lead USP Operator) | `OPERATOR` / `Process_Operator` | `Operator_Pass_2026!` (or `Operator_2026!`) |
| `qa_approver_01` | Dr. Marcus Vance (QA Qualified Person) | `QA_APPROVER` / `Quality_Assurance` | `QA_Approve_2026!` (or `QA_Approver_2026!`) |

---

## Step 3: Access Interactive Interfaces

1. **Swagger / OpenAPI Interactive REST Docs:**
   - Open `http://localhost:8020/docs` in your browser.
2. **Grafana Vision Operator HMI:**
   - Open `http://localhost:3020/d/openhistorian-gxp-bioreactor-hmi`
   - Login with **`admin`** / **`GxP_Grafana_2026!`**
3. **Verify 21 CFR Part 11 Audit Hash Chain:**
   ```bash
   curl -s http://localhost:8020/api/v1/audit-trail/verify | jq .
   ```
4. **Run the 15-Test Automated IQ/OQ Qualification Suite:**
   ```bash
   .venv/bin/pytest -v
   ```
