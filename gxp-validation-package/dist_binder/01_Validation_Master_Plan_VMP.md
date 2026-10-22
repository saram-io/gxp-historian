# Document 01 — Validation Master Plan (VMP)

| Document ID | Version | Effective Date (UTC) | System Name | Regulatory Scope | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `VMP-GXPHISTORIAN-2026-001` | `1.0` | `2026-10-22T03:35:25Z` | GxPHistorian GxP Industrial Historian (ClickHouse + PostgreSQL Part 11 Control Plane) | 21 CFR Part 11, EU GMP Annex 11, ISPE GAMP 5 (2nd Ed.), FDA CSA | **APPROVED** |

---

## 1. Purpose & Regulatory Scope

This **Validation Master Plan (VMP)** establishes the Computerized System Validation (CSV) and Computer Software Assurance (CSA) governance framework for the **GxPHistorian GxP Industrial Historian** deployed at BioCorp Fremont Biomanufacturing Operations. The platform replaces legacy proprietary OSIsoft PI System components with a 4-Pillar open-source architecture engineered for **21 CFR Part 11**, **EU EudraLex Volume 4 Annex 11**, and **ALCOA+** data integrity compliance.

## 2. System Classification (ISPE GAMP 5 Second Edition)

| Subsystem Pillar | Component | GAMP 5 Category | Validation Strategy |
| :--- | :--- | :--- | :--- |
| **Pillar 1: Edge Collector** | Telegraf 1.32 + Disk WAL + Python Deadband Worker | Category 4 / Category 5 | Automated IQ + Scripted OQ on Stage 1 Exception/Deadband logic & WAL persistence |
| **Pillar 2: Telemetry Archive** | ClickHouse Server 24.8 LTS (`MergeTree` / `AggregatingMergeTree`) | Category 4 | Automated IQ on lossless codecs (`DoubleDelta`, `Gorilla`) + Scripted OQ on `quality >= 192` filtering, LTTB, and interpolation |
| **Pillar 3: Control Plane** | PostgreSQL 16 + FastAPI (`historian-api`) | Category 4 / Category 5 | Scripted OQ on PL/pgSQL Part 11 WORM audit triggers, SHA-256 hash chaining, and §11.200 electronic signatures |
| **Pillar 4: Operator HMI** | Grafana OSS 11.2 + Excel DataLink UDF/Power Query | Category 4 | Automated IQ on provisioned datasources/dashboards + OQ on DataLink CSV/JSON parity |

## 3. Roles & Responsibilities

| Role | Designated Personnel | GxP Responsibilities |
| :--- | :--- | :--- |
| **System Owner** | Director of Manufacturing IT/OT | Accountable for system availability, access control, backup/restore drills, and GitOps change control. |
| **Process Owner** | Head of Upstream & Downstream MSAT | Defines User Requirements (URS), engineering units, alarm limits (`low_limit`, `high_limit`), and batch Event Frame templates. |
| **Quality Assurance (QA)** | Lead CSV / Part 11 Qualified Person (`qa_approver_01`) | Approves VMP, URS, Risk Assessment, executes/reviews IQ/OQ evidence, and signs batch/excursion Event Frames. |
| **Validation Engineering** | Senior CSV Automation Engineer | Authors and maintains executable `pytest` IQ/OQ qualification suites and generates the cryptographic validation binder. |

## 4. Validation Lifecycle (IQ → OQ → PQ)

1. **Installation Qualification (IQ):** Automated verification (`test_01_iq_infrastructure.py`) of container health, non-default credentials, PostgreSQL extensions (`ltree`, `btree_gist`, `pgcrypto`), ClickHouse lossless compression codecs, and dictionary bridging.
2. **Operational Qualification (OQ):** Scripted positive and adversarial negative testing (`test_02_oq_part11_compliance.py` & `test_03_oq_historian_core.py`) verifying 21 CFR Part 11 WORM immutability, SHA-256 hash chain verification, electronic signature credential challenges, bad quality (`quality < 192`) rejection, linear vs. LOCF step interpolation, and LTTB peak preservation.
3. **Performance Qualification (PQ):** Continuous multi-protocol plant telemetry ingestion across 5 GxP tags (`101`, `102`, `103`, `301`, `401`), live Event Frame excursion capture, and Apache Parquet lakehouse exports.

## 5. Backup, Restore, Disaster Recovery & GitOps Change Control SOP

- **Database & Telemetry Backups:** PostgreSQL `pi_control_plane` (including `part11_audit_log`) undergoes daily logical `pg_dump` and continuous WAL archiving to immutable object storage. ClickHouse `pi_historian` partitions (`PARTITION BY toYYYYMM(ts)`) are exported to Snappy-compressed Apache Parquet files and backed up via native ClickHouse `BACKUP TABLE` snapshots.
- **GitOps Change Control (`SOP-IT-CHG-014`):** All infrastructure definitions (`docker-compose.yml`), database schemas (`init-postgres/`, `init-clickhouse/`), and API code (`app/main.py`, `app/pi_parity_engine.py`) are version-controlled in Git. Any change requires a pull request, automated execution of the 21-test IQ/OQ `pytest` suite (`100%` pass gate), and QA electronic approval prior to production deployment.

## 6. Hybrid Cloud & Commercial Edition Governance (EU GMP Annex 11 §4.3 & 21 CFR §11.30)

For regulated organizations deploying **GxPHistorian Cloud** (`Managed Single-Tenant Cloud` or `BYOC Cloud Marketplace` across Amazon Web Services, Microsoft Azure, and Google Cloud):
- **Purdue Level 2.5 Edge Autonomy (`URS-005`):** Pillar 1 (`edge-collector` or pre-qualified **GxPHistorian Edge Box** DIN-rail IPC) always executes on-premises with a 100 GB local pSLC NVMe Write-Ahead Log (`>14-day` offline store-and-forward autonomy) and outbound-only `TLS 1.3` / `mTLS` (`:8443`) transport.
- **Change-Controlled LTS Release Channels (`2026.Q4-LTS`):** Cloud environments never undergo unannounced auto-updates. Every release is promoted to a customer staging environment first, where the 21-test `pytest` IQ/OQ suite executes automatically and mints a countersigned Validation Summary Report (`VSR`) prior to production promotion.
- **Quality Technical Agreement (QTA):** Governed by the bidirectional Shared Responsibility Matrix in Document 05 (`SOUP-GXPHISTORIAN-2026-005`), granting annual QA postal/on-site supplier audit rights and guaranteeing 15-year `21 CFR 211.180` WORM retention (`AWS S3 Object Lock COMPLIANCE`, `Azure Immutable Blob Storage`, or `GCP Bucket Lock`).
