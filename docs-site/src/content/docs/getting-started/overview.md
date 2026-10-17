---
title: Overview & OSIsoft PI System Parity
description: Executive overview of OpenHistorian GxP Industrial Historian, OSIsoft / AVEVA PI System Parity Matrix, Container Port Matrix, and Repository Layout.
---

**OpenHistorian GxP Industrial Historian** is a production-ready, **21 CFR Part 11**, **EU GMP Annex 11**, and **ISPE GAMP 5 (Second Edition)** qualified open-source replacement for the proprietary **OSIsoft / AVEVA PI System**, engineered specifically for pharmaceutical, biotechnology, and regulated industrial manufacturing environments.

It combines:
- **ClickHouse 24.8 LTS** — Lossless `DoubleDelta` + `Gorilla` time-series telemetry archive, real-time 1-minute `AggregatingMergeTree` rollups, and native `largestTriangleThreeBuckets` (LTTB) visual downsampling.
- **PostgreSQL 16** — `ltree` ISA-95 Asset Framework, Tag Catalog, ISA-88 Event Frames, and a cryptographic SHA-256 Write-Once-Read-Many (WORM) 21 CFR Part 11 audit trail.
- **InfluxData Telegraf 1.32 + Python Multi-Protocol Edge Workers** — Stage 1 Exception/Deadband filtering (`ExcDev` & `ExcMax`) and disk-backed store-and-forward Write-Ahead Log (WAL).
- **FastAPI Control Plane (`historian-api`)** — Unified GxP REST API, Event Frame state machine, `§11.200` dual-challenge electronic signatures, Excel DataLink server, and PyArrow Parquet exporter.
- **Grafana OSS 11.2 (`grafana-vision`) & Excel DataLink Client** — Asset-relative Operator HMI with Event Frame annotations plus drop-in Excel `xlwings` UDFs and zero-macro Power Query CSV streams.

---

## 1. OSIsoft / AVEVA PI System Parity Matrix

| Legacy OSIsoft / AVEVA PI Component | OpenHistorian GxP Historian Equivalent | Key Technical Capabilities |
| :--- | :--- | :--- |
| **PI Data Archive** (Swinging Door / Archive Subsystem) | **ClickHouse 24.8 LTS (`pi_historian.sensor_data`)** | `MergeTree` partitioned by month (`toYYYYMM(ts)`) with lossless `Delta`, `DoubleDelta`, `Gorilla`, and `T64` codecs layered with `ZSTD(1)` + real-time 1-minute `AggregatingMergeTree` rollups (`sensor_rollup_1m`). |
| **PI Asset Framework (PI AF)** | **PostgreSQL 16 `ltree` + ClickHouse `FLAT` Dictionary** | ISA-95 hierarchical asset paths (`Enterprise.Site.Area.Unit`) indexed via PostgreSQL `GiST` and synchronized into ClickHouse RAM (`pi_historian.pg_asset_tags`) with 5–15s refresh lifetime. |
| **PI Event Frames (EF)** | **PostgreSQL `event_frames` + FastAPI State Machine** | Automated ISA-88 batch & excursion detection (`BR201_TEMP_PV > 38.0°C`), ClickHouse `quality >= 192` KPI capture (`peak_val`, `avg_val`, `min_val`, `sample_count`), and 21 CFR Part 11 electronic signatures. |
| **PI Interface Node & PI Buffer Subsystem** | **Telegraf 1.32 Disk WAL + Python Edge Workers** | Stage 1 Exception/Deadband filtering (`ExcDev` & `ExcMax`) in memory + disk-backed Write-Ahead Log (`/var/lib/telegraf/buffer`, 1M metric capacity) for zero-data-loss store-and-forward across OPC UA, BACnet/IP, Siemens S7, Modbus, and Windows OPC DA. |
| **PI Vision** (`PlotValues` Trends & EF Overlays) | **Grafana OSS 11.2 + ClickHouse `largestTriangleThreeBuckets`** | Asset-relative dashboard (`${asset_path}`) with native ClickHouse LTTB visual peak preservation, 1-minute rollup bands, Event Frame shaded region annotations, and live Part 11 audit trail inspection. |
| **PI DataLink** (Excel `PISampDat`, `PIAdvCalcDat`) | **FastAPI `/api/v1/datalink/sampled` + `xlwings` UDF / Power Query** | Drop-in `=OPENHISTORIAN_SAMPLED()`, `=OPENHISTORIAN_PLOT_VALUES()`, and `=OPENHISTORIAN_EVENT_SUMMARY()` Excel functions plus zero-macro Power Query CSV streams respecting continuous (`LINEAR`) vs. discrete (`LOCF` step) tag metadata. |
| **PI Integrator for Business Analytics** | **FastAPI + PyArrow Zero-ETL Lakehouse Exporter** | One-call (`POST /api/v1/lakehouse/export-parquet`) Snappy-compressed Apache Parquet export enriched with ISA-95 asset hierarchy and engineering units. |

---

## 2. Container & Port Matrix

| Container Name | Role | Internal Port | Default Host Port (`.env`) | Technology Stack |
| :--- | :--- | :--- | :--- | :--- |
| `postgres-control` | Pillar 3: Relational Control Plane & Part 11 WORM Audit Log | `5432` | `5435` (`PG_PORT`) | PostgreSQL 16 (`ltree`, `btree_gist`, `pgcrypto`) |
| `clickhouse-archive` | Pillar 2: Immutable Time-Series Archive & Rollup Engine | `8123` / `9000` | `8125` / `9005` | ClickHouse Server 24.8 LTS (`Apache-2.0`) |
| `edge-collector` | Pillar 1: Multi-Protocol Collector & Store-and-Forward WAL | `8080` | `8080` (`EDGE_INGEST_PORT`) | Telegraf 1.32 Alpine + Python 3.12 |
| `historian-api` | Pillar 3: GxP REST API, Event Frame Engine & DataLink Server | `8000` | `8020` (`API_PORT`) | FastAPI, Psycopg 3, ClickHouse Connect, PyArrow |
| `grafana-vision` | Pillar 4: Pre-Provisioned Operator HMI | `3000` | `3020` (`GRAFANA_PORT`) | Grafana OSS 11.2 + ClickHouse Datasource Plugin |

---

## 3. Repository Structure

```text
clickhouse-historian/
├── .antigravity/
│   └── rules.md                                      # Architectural & 21 CFR Part 11 guardrails
├── .env / .env.example                               # Non-default GxP credentials & host port mappings
├── docker-compose.yml                                # 5-service orchestrated stack with healthchecks
├── pytest.ini                                        # Pytest configuration for IQ/OQ qualification
├── init-postgres/
│   └── 01_control_plane_part11.sql                   # PostgreSQL 16 ltree, pgcrypto, WORM audit & seed data
├── init-clickhouse/
│   └── 01_telemetry_core.sql                         # MergeTree codecs, 1m rollups, PG dictionary & bridges
├── edge-collector/
│   ├── Dockerfile                                    # Telegraf 1.32 Alpine + Python 3.12 edge collector image
│   ├── telegraf-clickhouse.conf                      # Disk WAL buffer, HTTP ingest (:8080), execd & CH output
│   └── scripts/
│       ├── multi_protocol_simulator.py               # Deterministic plant simulator + Stage 1 Deadband filter
│       ├── opcda_windows_forwarder.py                # Windows localhost COM OPC DA -> HTTP JSON bridge
│       └── bacnet_cov_worker.py                      # Async BACnet/IP COV / ReadPropertyMultiple worker
├── app/
│   ├── Dockerfile                                    # FastAPI control plane container definition
│   ├── requirements.txt                              # FastAPI, Psycopg 3, ClickHouse Connect, PyArrow
│   └── main.py                                       # Unified REST API, Event Frame Engine, DataLink & Part 11
├── provisioning/grafana/
│   ├── datasources/datasources.yml                   # Auto-provisioned ClickHouse & PostgreSQL datasources
│   └── dashboards/
│       ├── dashboards.yml                            # Dashboard provider configuration
│       └── openhistorian_bioreactor_hmi.json         # Asset-relative Bioreactor & Cleanroom HMI dashboard
├── docs/                                             # 8 Biopharma & Legacy Equipment Integration Guides
├── docs-site/                                        # Astro Starlight Documentation Portal
├── excel-datalink-client/
│   ├── openhistorian_datalink_udf.py                 # xlwings UDFs (=OPENHISTORIAN_SAMPLED, etc.)
│   └── README_EXCEL_SETUP.md                         # Power Query (zero-macro) & xlwings setup guide
└── gxp-validation-package/
    ├── generate_gmp_binder.py                        # Automated 8-Document GMP Validation Binder generator
    ├── specs/urs_risk_catalog.yaml                   # 15 URS items mapped to FRS, GAMP Cat, CSA Risk & pytest
    ├── tests/                                        # Executable IQ/OQ pytest qualification suite (15 tests)
    ├── evidence/oq_execution_results.json            # Timestamped pytest execution evidence log
    └── dist_binder/                                  # Generated 8 Markdown deliverables + HTML/PDF binder
```
