---
title: GAMP 5 & CSA Qualification Overview
description: Execute the 15-test automated IQ/OQ pytest qualification suite and generate the 8-Document Commercial GMP Validation Binder.
---

GxPHistorian includes an executable **ISPE GAMP 5 (Second Edition)** and **FDA Computer Software Assurance (CSA)** qualification package in `gxp-validation-package/`. Every User Requirement (`URS-001` through `URS-015`) is mapped bidirectionally to Functional Specifications (`FRS`), CSA Risk Assessments (`FRA`), and automated `pytest` IQ/OQ verification tests.

---

## Print-Ready Single-File GMP Validation Binder

In addition to browsing the 8 individual Markdown documents in the sidebar, you can open or print the complete standalone HTML/PDF Validation Binder (including live container `@sha256` digests, executed `pytest` evidence, and database audit samples):

- **[Open Complete GMP Validation Binder (`COMPLETE_GMP_VALIDATION_BINDER.html`)](/binder/COMPLETE_GMP_VALIDATION_BINDER.html)**

---

## 1. Run the 15-Test Automated IQ/OQ Pytest Suite

```bash
python3 -m venv .venv
.venv/bin/pip install -r app/requirements.txt pytest pyyaml
.venv/bin/pytest -v
```

Executing `pytest` runs all 15 qualification tests across three test modules and automatically records timestamped execution evidence to `gxp-validation-package/evidence/oq_execution_results.json`:

| Test Suite File | Qualification Phase | Test IDs | Verified Regulatory & Technical Controls |
| :--- | :--- | :--- | :--- |
| `test_01_iq_infrastructure.py` | **Installation Qualification (IQ)** | `IQ-01` .. `IQ-05` | Non-default credentials, PostgreSQL `ltree`/`pgcrypto`/WORM triggers, ClickHouse `DoubleDelta`/`Gorilla`/`ZSTD` codecs & `sensor_rollup_1m`, `pg_asset_tags` dictionary sync, and Telegraf Disk WAL configuration. |
| `test_02_oq_part11_compliance.py` | **Operational Qualification (OQ) — Part 11** | `OQ-01` .. `OQ-05` | Rejection of unattributed DML (`app.actor_id` / `app.change_reason`), WORM immutability blocking `UPDATE`/`DELETE` on `part11_audit_log`, `§11.200` invalid password rejection (`HTTP 401`), valid `HMAC-SHA256` electronic signature binding, and end-to-end SHA-256 hash chain verification. |
| `test_03_oq_historian_core.py` | **Operational Qualification (OQ) — Historian Core** | `OQ-06` .. `OQ-10` | Multi-protocol ingestion (`OPC_UA`, `SIEMENS_S7`, `BACNET_IP`, `OPC_DA`), bad quality (`quality = 0`, `-999.0`) exclusion from 1m rollups & DataLink, `LINEAR` vs. `LOCF` step interpolation accuracy, LTTB peak preservation & Event Frame evaluation, and Snappy Apache Parquet export verification. |

---

## 2. Generate the 8-Document Commercial GMP Validation Binder

```bash
.venv/bin/python3 gxp-validation-package/generate_gmp_binder.py
```

`generate_gmp_binder.py` combines:
1. `gxp-validation-package/specs/urs_risk_catalog.yaml` (15 URS items mapped to FRS, GAMP Category, and CSA Risk)
2. `gxp-validation-package/evidence/oq_execution_results.json` (timestamped `pytest` results and assertion narratives)
3. Live container image `@sha256` digests queried via `docker inspect`
4. Live database evidence queried from `part11_audit_log` and `event_frames`

It outputs all 8 regulatory deliverables into `gxp-validation-package/dist_binder/` (and synced into this documentation portal):

1. **[01 — Validation Master Plan (VMP)](/gxp-validation/01-vmp/)** (`VMP-GXPHISTORIAN-2026-001`)
2. **[02 — User Requirements Specification (URS)](/gxp-validation/02-urs/)** (`URS-001` through `URS-015`)
3. **[03 — Functional & Design Specification (FDS)](/gxp-validation/03-fds/)** (4-Pillar Architecture & Schema Spec)
4. **[04 — CSA Functional Risk Assessment (FRA)](/gxp-validation/04-fra/)** (Patient Safety, Product Quality & Data Integrity Risk Matrix)
5. **[05 — SOUP / OSS Vendor Qualification Dossier](/gxp-validation/05-soup-dossier/)** (ClickHouse, PostgreSQL, Telegraf, FastAPI, Grafana `@sha256` digests)
6. **[06 — Executed IQ/OQ Protocol & Evidence Report](/gxp-validation/06-iq-oq-evidence/)** (15/15 Executed Test Results & Live Cryptographic Audit Samples)
7. **[07 — Requirements Traceability Matrix (RTM)](/gxp-validation/07-rtm/)** (Bidirectional URS $\leftrightarrow$ FRS $\leftrightarrow$ Risk $\leftrightarrow$ Test ID Matrix)
8. **[08 — Validation Summary Report (VSR)](/gxp-validation/08-vsr/)** (QA Release Certificate for Production GMP Use)
