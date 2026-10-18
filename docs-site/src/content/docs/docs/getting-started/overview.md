---
title: Overview & OSIsoft PI System Parity
description: Executive overview of GxPHistorian GxP Industrial Historian, OSIsoft / AVEVA PI System Parity Matrix, Container Port Matrix, and Repository Layout.
---

**GxPHistorian GxP Industrial Historian** is a production-ready, **21 CFR Part 11**, **EU GMP Annex 11**, and **ISPE GAMP 5 (Second Edition)** qualified open-source replacement for the proprietary **OSIsoft / AVEVA PI System**, engineered specifically for pharmaceutical, biotechnology, and regulated industrial manufacturing environments.

It combines:
- **ClickHouse 24.8 LTS** — Lossless `DoubleDelta` + `Gorilla` time-series telemetry archive, real-time 1-minute `AggregatingMergeTree` rollups, and native `largestTriangleThreeBuckets` (LTTB) visual downsampling.
- **PostgreSQL 16** — `ltree` ISA-95 Asset Framework, Tag Catalog, ISA-88 Event Frames, and a cryptographic SHA-256 Write-Once-Read-Many (WORM) 21 CFR Part 11 audit trail.
- **InfluxData Telegraf 1.32 + Python Multi-Protocol Edge Workers** — Stage 1 Exception/Deadband filtering (`ExcDev` & `ExcMax`) and disk-backed store-and-forward Write-Ahead Log (WAL).
- **FastAPI Control Plane (`historian-api`)** — Unified GxP REST API, Event Frame state machine, `§11.200` dual-challenge electronic signatures, Excel DataLink server, and PyArrow Parquet exporter.
- **Grafana OSS 11.2 (`grafana-vision`) & Excel DataLink Client** — Asset-relative Operator HMI with Event Frame annotations plus drop-in Excel `xlwings` UDFs and zero-macro Power Query CSV streams.

---

## 1. OSIsoft / AVEVA PI System Parity Matrix

| Legacy OSIsoft / AVEVA PI Component | GxPHistorian GxP Historian Equivalent | Key Technical Capabilities |
| :--- | :--- | :--- |
| **PI Data Archive** (Swinging Door / Archive Subsystem) | **ClickHouse 24.8 LTS (`pi_historian.sensor_data`) + Stage 2 Swinging Door (`CompDev`/`CompMax`)** | `MergeTree` partitioned by month (`toYYYYMM(ts)`) with lossless `Delta`, `DoubleDelta`, `Gorilla`, and `T64` codecs layered with `ZSTD(1)`, optional Stage 2 Swinging Door compression (`CompDev`, `CompMax`, `CompMin`), and real-time 1-minute `AggregatingMergeTree` rollups (`sensor_rollup_1m`). |
| **PI Asset Framework (PI AF)** | **PostgreSQL 16 `ltree` + ClickHouse `FLAT` Dictionary + Template Auto-Instantiation** | ISA-95 hierarchical asset paths (`Enterprise.Site.Area.Unit`) indexed via PostgreSQL `GiST`, one-call AF Template auto-instantiation (`POST /api/v1/assets/instantiate-template`), canonical UOM conversion, Digital State Sets (`digital_state_sets`), and ClickHouse RAM dictionary sync (`pi_historian.pg_asset_tags`). |
| **PI Event Frames (EF) & PI Notifications** | **PostgreSQL `event_frames` + `TrueFor` Backfill + Multi-Stage Signatures + Notification Engine** | Automated ISA-88 batch & excursion detection, historical backfill with `TrueFor` debounce (`POST /api/v1/event-frames/backfill`), hierarchical parent/child batch phases (`parent_event_id`), multi-stage 21 CFR Part 11 electronic signatures (`Operator` $\rightarrow$ `Supervisor` $\rightarrow$ `QA`), and webhook/email notification rules (`POST /api/v1/notifications/evaluate`). |
| **PI Interface Node & PI Buffer Subsystem** | **Telegraf 1.32 Disk WAL + Python Edge Workers** | Stage 1 Exception/Deadband filtering (`ExcDev` & `ExcMax`) + optional Stage 2 Swinging Door (`CompDev` & `CompMax`) in memory + disk-backed Write-Ahead Log (`/var/lib/telegraf/buffer`, 1M metric capacity) for zero-data-loss store-and-forward across OPC UA, BACnet/IP, Siemens S7, Modbus, and Windows OPC DA. |
| **PI Vision & PI BatchView** (`PlotValues` Trends, EF Overlays & Golden Batch) | **Grafana OSS 11.2 + ClickHouse `largestTriangleThreeBuckets` + `/api/v1/batches/compare`** | Asset-relative dashboard (`${asset_path}`) with native ClickHouse LTTB visual peak preservation, 1-minute rollup bands, Event Frame shaded region annotations, relative batch elapsed-hour (`T+0.0h`) Golden Batch alignment (`mean ± 2 SD` reference envelope), and live Part 11 audit trail inspection. |
| **PI DataLink & PI Web API StreamSets** (`PICurrVal`, `PIArcVal`, `PICompDat`, `PISampDat`, `PIAdvCalcDat`, `PITimeFilter`) | **FastAPI `/api/v1/datalink/*` + `/api/v1/streamsets/*` + 8 `xlwings` Excel UDFs / Power Query** | Complete 8-function Excel DataLink suite (`=GXPHISTORIAN_SAMPLED()`, `=GXPHISTORIAN_PLOT_VALUES()`, `=GXPHISTORIAN_EVENT_SUMMARY()`, `=GXPHISTORIAN_CURRENT_VALUE()`, `=GXPHISTORIAN_ARCHIVE_VALUE()`, `=GXPHISTORIAN_COMPRESSED_DATA()`, `=GXPHISTORIAN_CALCULATED_DATA()`, `=GXPHISTORIAN_TIME_FILTER()`) plus bulk multi-tag StreamSets (`/api/v1/streamsets/end`, `/api/v1/streamsets/interpolated`). |
| **PI Analysis Service & SQC** (Asset Analytics & Statistical Process Control) | **GxP Calculation Engine (`/api/v1/analytics/{mkt,f0-lethality,sqc}`)** | Built-in ICH Q1A Mean Kinetic Temperature ($\text{MKT}$, $\Delta H = 83.144\text{ kJ/mol}$), USP `<1229>` Steam Sterilization Lethality ($F_0$ trapezoidal integration), and Western Electric SQC SPC rules (`3σ`, `2-of-3 2σ`, `4-of-5 1σ`, `8-consecutive same side`, $C_p$, $C_{pk}$). |
| **PI Manual Logger** | **21 CFR Part 11 Manual Data Entry (`/api/v1/manual-logger/entries`)** | Validated offline/at-line lab and cleanroom logbook entry with optional dual-person verification (`verified_by`), WORM audit trail attribution, and automatic dual-write into ClickHouse `pi_historian.sensor_data` (`quality = 192`). |
| **PI Integrator for Business Analytics** | **FastAPI + PyArrow Zero-ETL Lakehouse Exporter** | One-call (`POST /api/v1/lakehouse/export-parquet`) Snappy-compressed Apache Parquet export enriched with ISA-95 asset hierarchy and engineering units. |
| **AVEVA Industrial AI Assistant / PI Web API** | **Pydantic AI Co-Pilot (`app/gxp_ai_agent.py`) & `gxphistorian-mcp` (`app/mcp_server.py`)** | Typed ISA-88 Batch Excursion Investigator (`output_type=DeviationInvestigationBrief`, `WHERE quality >= 192`), Part 11 human-in-the-loop `ApprovalRequired` tag provisioning, Capabilities on Demand (`defer_loading=True`), and 6-tool `FastMCP` server. |

---

## 2. Container & Port Matrix

| Container Name | Role | Internal Port | Default Host Port (`.env`) | Technology Stack |
| :--- | :--- | :--- | :--- | :--- |
| `postgres-control` | Pillar 3: Relational Control Plane & Part 11 WORM Audit Log | `5432` | `5435` (`PG_PORT`) | PostgreSQL 16 (`ltree`, `btree_gist`, `pgcrypto`) |
| `clickhouse-archive` | Pillar 2: Immutable Time-Series Archive & Rollup Engine | `8123` / `9000` | `8125` / `9005` | ClickHouse Server 24.8 LTS (`Apache-2.0`) |
| `instrument-mock-server` | Pillar 1: Multi-Protocol Biopharma Instrument Mock Server | `8095`, `4840`, `5020`, `47808/udp`, `1102`, `4001` | `8095`, `4840`, `5020`, `47808/udp`, `1102`, `4001` | Python 3.12 Asyncio (OPC UA, Modbus TCP, BACnet/IP, S7comm, RS-232 `MT-SICS`, OPC DA & UFL) |
| `edge-collector` | Pillar 1: Multi-Protocol Collector & Store-and-Forward WAL | `8080` | `8080` (`EDGE_INGEST_PORT`) | Telegraf 1.32 Alpine + Python 3.12 |
| `historian-api` | Pillar 3: GxP REST API, Event Frame Engine & DataLink Server | `8000` | `8020` (`API_PORT`) | FastAPI, Psycopg 3, ClickHouse Connect, PyArrow |
| `gxphistorian-mcp` | Pillar 3: Pydantic AI Co-Pilot & FastMCP Streamable HTTP Server | `8030` | `8030` (`MCP_PORT`) | Pydantic AI 2.0, FastMCP, Pydantic Logfire |
| `grafana-vision` | Pillar 4: Pre-Provisioned Operator HMI | `3000` | `3020` (`GRAFANA_PORT`) | Grafana OSS 11.2 + ClickHouse Datasource Plugin |

---

## 3. Repository Structure

```text
clickhouse-historian/
├── .antigravity/
│   └── rules.md                                      # Architectural & 21 CFR Part 11 guardrails
├── .env / .env.example                               # Non-default GxP credentials & host port mappings
├── docker-compose.yml                                # 7-service orchestrated stack with healthchecks
├── pytest.ini                                        # Pytest configuration for IQ/OQ qualification
├── init-postgres/
│   └── 01_control_plane_part11.sql                   # PostgreSQL 16 ltree, pgcrypto, WORM audit & seed data
├── init-clickhouse/
│   └── 01_telemetry_core.sql                         # MergeTree codecs, 1m rollups, PG dictionary & bridges
├── instrument-mock-server/
│   ├── Dockerfile                                    # Multi-protocol biopharma instrument mock server image
│   └── mock_instruments.py                           # Live OPC UA (:4840), Modbus (:5020), BACnet (:47808), S7 (:1102), RS-232 (:4001) & HTTP (:8095)
├── edge-collector/
│   ├── Dockerfile                                    # Telegraf 1.32 Alpine + Python 3.12 edge collector image
│   ├── telegraf-clickhouse.conf                      # Disk WAL buffer, HTTP ingest (:8080), execd & CH output
│   └── scripts/
│       ├── multi_protocol_simulator.py               # Deterministic plant simulator + Stage 1 Deadband & Stage 2 Swinging Door
│       ├── opcda_windows_forwarder.py                # Windows localhost COM OPC DA -> HTTP JSON bridge
│       └── bacnet_cov_worker.py                      # Async BACnet/IP COV / ReadPropertyMultiple worker
├── app/
│   ├── Dockerfile                                    # FastAPI control plane container definition
│   ├── requirements.txt                              # FastAPI, Psycopg 3, ClickHouse Connect, PyArrow, Pydantic AI, FastMCP
│   ├── main.py                                       # Unified REST API, Event Frame Engine, DataLink & Part 11
│   ├── pi_parity_engine.py                           # AVEVA PI System Parity Engine (DataLink, StreamSets, MKT/F0/SQC, BatchView, AF, Manual Logger, Notifications)
│   ├── gxp_ai_agent.py                               # Pydantic AI Excursion Investigator & Part 11 Co-Pilot Agents
│   └── mcp_server.py                                 # FastMCP (gxphistorian-mcp) read-only GxP historian server
├── provisioning/grafana/
│   ├── datasources/datasources.yml                   # Auto-provisioned ClickHouse & PostgreSQL datasources
│   └── dashboards/
│       ├── dashboards.yml                            # Dashboard provider configuration
│       └── gxphistorian_bioreactor_hmi.json          # Asset-relative Bioreactor & Cleanroom HMI dashboard
├── docs/                                             # Biopharma Equipment, Connector & Pydantic AI Guides
├── docs-site/                                        # Astro Starlight Documentation Portal
├── excel-datalink-client/
│   ├── gxphistorian_datalink_udf.py                  # 8 xlwings UDFs (=GXPHISTORIAN_SAMPLED, =GXPHISTORIAN_CALCULATED_DATA, etc.)
│   └── README_EXCEL_SETUP.md                         # Power Query (zero-macro) & xlwings setup guide
└── gxp-validation-package/
    ├── generate_gmp_binder.py                        # Automated 8-Document GMP Validation Binder generator
    ├── specs/urs_risk_catalog.yaml                   # 21 URS items mapped to FRS, GAMP Cat, CSA Risk & pytest
    ├── tests/                                        # Executable IQ/OQ pytest qualification suite (21 tests)
    ├── evidence/oq_execution_results.json            # Timestamped pytest execution evidence log
    └── dist_binder/                                  # Generated 8 Markdown deliverables + HTML/PDF binder
```
