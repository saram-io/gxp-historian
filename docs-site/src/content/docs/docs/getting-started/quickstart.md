---
title: Quickstart & Deployment
description: Deploy the 6-service GxPHistorian GxP stack (including the Pydantic AI Co-Pilot & gxphistorian-mcp Server) via Docker Compose, inspect seeded ISA-95 assets and Part 11 users, and verify system health.
---

## Prerequisites

- **Docker Engine 24+** and **Docker Compose v2**
- **Python 3.11+** *(optional, for running the local `pytest` IQ/OQ qualification suite and GMP binder generator)*

---

## Step 1: Configure Environment & Launch the Stack

Clone the [GxPHistorian GitHub repository](https://github.com/saram-io/gxp-historian), copy the GxP environment template, and start all 6 orchestrated services:

```bash
git clone https://github.com/saram-io/gxp-historian.git
cd gxp-historian
cp .env.example .env
docker compose up -d --build
```

Verify that all 7 containers (`postgres-control`, `clickhouse-archive`, `instrument-mock-server`, `edge-collector`, `historian-api`, `gxphistorian-mcp`, `grafana-vision`) are running and healthy:

```bash
docker compose ps
curl -s http://localhost:8020/api/v1/health | jq .
curl -s http://localhost:8030/health | jq .
curl -s http://localhost:8095/health | jq .
curl -s -X POST http://localhost:8095/control/self-test | jq .
```

### Expected Health Response (`historian-api` & `gxphistorian-mcp`)

```json
{
  "status": "healthy",
  "service": "gxphistorian-mcp",
  "protocol": "Model Context Protocol (MCP) + Pydantic AI",
  "mcp_endpoint": "/mcp",
  "ai_model": "google:gemini-3-flash-preview",
  "live_llm_enabled": false,
  "postgres": {
    "connected": true
  },
  "clickhouse": {
    "connected": true
  },
  "pydantic_ai_agents": [
    "gxp_deviation_investigator_agent",
    "gxp_copilot_agent"
  ],
  "mcp_tools_count": 6,
  "mcp_resources_count": 3
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
2. **Pydantic AI Co-Pilot & `gxphistorian-mcp` Server (`:8030`):**
   - Streamable HTTP MCP endpoint: `http://localhost:8030/mcp`
   - Manifest & OpenAPI Docs: `http://localhost:8030/mcp/manifest` and `http://localhost:8030/docs`
3. **Multi-Protocol Biopharma Instrument Mock Server (`instrument-mock-server` on `:8095`, `:4840`, `:5020`, `:47808/udp`, `:1102`, `:4001`):**
   - Open `http://localhost:8095/docs` for the interactive protocol control plane, or run the 6-protocol wire self-test and push live samples to `edge-collector`:
     ```bash
     curl -s -X POST http://localhost:8095/control/self-test \
       -H "Content-Type: application/json" \
       -d '{"push_to_edge_collector": true}' | jq .
     ```
   - See the full [Mock Instrument Server & Protocol Testing Guide](/docs/connectors/mock-instrument-testing/) for raw socket testing (`OPC UA`, `Modbus ABCD/CDAB`, `BACnet/IP`, `Siemens S7 DB10`, `Moxa RS-232 MT-SICS`, and `OPC DA / PI UFL`) and fault/excursion injection (`/control/override`).
4. **Grafana Vision Operator HMI:**
   - Open `http://localhost:3020/d/gxphistorian-gxp-bioreactor-hmi`
   - Login with **`admin`** / **`GxP_Grafana_2026!`**
5. **Verify 21 CFR Part 11 Audit Hash Chain:**
   ```bash
   curl -s http://localhost:8020/api/v1/audit-trail/verify | jq .
   ```
6. **Run the 21-Test Automated IQ/OQ Qualification Suite:**
   ```bash
   .venv/bin/pytest -v
   ```

