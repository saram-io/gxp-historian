---
title: "Document 04 — FDA CSA Functional Risk Assessment (FRA)"
description: "Document 04 — FDA Computer Software Assurance (CSA) Functional Risk Assessment (FRA)."
---
**Document ID:** `FRA-GXPHISTORIAN-2026-004` | **Generated (UTC):** `2026-10-18T20:35:53Z` | **Methodology:** ISPE GAMP 5 & FDA Computer Software Assurance (CSA)

## 1. Functional Risk Assessment Matrix

| URS ID | Failure Mode / GxP Hazard | FMEA Score | CSA Risk Class | Required Testing Rigor | Technical Control & Verification Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **URS-001** | Unauthorized network access using default vendor credentials | `S=3, O=1, D=1` | **Medium** | Automated IQ Verification | Non-default secrets in .env verified by IQ test_iq_01 |
| **URS-002** | Missing database extensions or corrupted control plane schema | `S=3, O=1, D=1` | **Medium** | Automated IQ Verification | Automated DDL init script + IQ schema inspection test_iq_02 |
| **URS-003** | Uncompressed storage exhaustion or lossy float precision loss | `S=2, O=1, D=1` | **Low** | Automated IQ Verification | Lossless Gorilla/DoubleDelta codecs verified via system.columns in test_iq_03 |
| **URS-004** | Stale or unmapped ISA-95 asset path in analytical queries | `S=3, O=2, D=1` | **Medium** | Automated IQ Verification | ClickHouse FLAT dictionary with 5-15s refresh verified in test_iq_04 |
| **URS-005** | Telemetry loss during temporary ClickHouse or network outage | `S=4, O=2, D=1` | **High** | Scripted OQ / IQ Verification | Telegraf disk WAL buffer (/var/lib/telegraf/buffer) + ExcDev/ExcMax verified in test_iq_05 |
| **URS-006** | Unattributed modification of GxP tag limits or Event Frames | `S=5, O=2, D=1` | **High** | Scripted OQ (Negative & Positive Testing) | PL/pgSQL fn_enforce_part11_audit() blocks mutations lacking actor_id/change_reason (test_oq_01) |
| **URS-007** | Malicious DBA or superuser deletion/alteration of audit trail | `S=5, O=1, D=1` | **High** | Scripted OQ (Adversarial Tamper Challenge) | BEFORE UPDATE/DELETE/TRUNCATE WORM trigger fn_prevent_audit_tampering() (test_oq_02) |
| **URS-008** | Spoofed or unauthorized electronic signature on Batch Event Frame | `S=5, O=2, D=1` | **High** | Scripted OQ (Negative Security Testing) | pgcrypto bcrypt password verification returns HTTP 401 on invalid password (test_oq_03) |
| **URS-009** | Detached or repudiated electronic signature on batch release | `S=5, O=1, D=1` | **High** | Scripted OQ | HMAC-SHA256 signature binding over (event_id, user_id, meaning, signed_at) (test_oq_04) |
| **URS-010** | Undetected offline tampering of historical audit trail rows | `S=5, O=1, D=1` | **High** | Scripted OQ | Continuous SHA-256 hash chain from GENESIS_0000000000000000 verified via API (test_oq_05) |
| **URS-011** | Protocol silo dropping OPC DA, BACnet/IP, S7, or OPC UA tags | `S=3, O=2, D=1` | **Medium** | Automated OQ Verification | Unified multi-protocol collector verified across tags 101, 102, 103, 301, 401 (test_oq_06) |
| **URS-012** | Broken sensor spike (quality=0, val=9999.0) corrupting batch CQA averages | `S=5, O=3, D=1` | **High** | Scripted OQ (Fault Injection Challenge) | Mandatory WHERE quality >= 192 filter in mv_sensor_rollup_1m verified by fault injection (test_oq_07) |
| **URS-013** | Linear interpolation creating invalid fractional states (1.5) on discrete valve/agitator tags | `S=4, O=2, D=1` | **High** | Scripted OQ (Mathematical Boundary Verification) | Metadata-driven LOCF step vs. LINEAR interpolation in /api/v1/datalink/sampled (test_oq_08) |
| **URS-014** | Visual trend downsampling hiding brief critical thermal excursion spikes | `S=4, O=2, D=1` | **Medium** | Scripted OQ | ClickHouse largestTriangleThreeBuckets(LTTB) preserves exact local peaks (test_oq_09) |
| **URS-015** | Corrupted or incomplete batch telemetry export to enterprise data lakehouse | `S=4, O=1, D=1` | **High** | Scripted OQ | PyArrow Snappy Parquet export verified for 100% row/column fidelity (test_oq_10) |
| **URS-016** | AI agent hallucinating time-series statistics or ignoring OPC quality < 192 | `S=4, O=2, D=1` | **High** | Scripted OQ (Deterministic FunctionModel & TestModel Qualification) | All telemetry math executed deterministically in ClickHouse via Pydantic AI tools & gxphistorian-mcp (test_oq_11) |
| **URS-017** | Autonomous AI agent mutating GxP tag catalog without human Part 11 attribution | `S=5, O=2, D=1` | **High** | Scripted OQ (Negative & Positive Human-in-the-Loop Gate Testing) | Pydantic AI ApprovalRequired (DeferredToolRequests) + mandatory X-Actor-Id/X-Change-Reason gate (test_oq_12) |
| **URS-018** | Event-weighted averaging distorting non-uniformly sampled process totals or durations | `S=4, O=2, D=1` | **High** | Scripted OQ (Mathematical Integration & Boundary Verification) | Trapezoidal & LOCF time-weighted integration in /api/v1/datalink/calculated & time-filter (test_oq_13) |
| **URS-019** | Inaccurate stability MKT or autoclave F0 lethality calculation leading to invalid batch release | `S=5, O=2, D=1` | **High** | Scripted OQ (Pharmacopeial Formula & SPC Verification) | ClickHouse ICH Q1A MKT, USP <1229> F0, Western Electric SQC & Golden Batch overlay (test_oq_14) |
| **URS-020** | Unverified manual lab entry or unit conversion error corrupting GxP batch records | `S=5, O=2, D=1` | **High** | Scripted OQ (Positive & Negative Dual-Verification Testing) | Part 11 Manual Logger dual-verification, canonical UOM dimension checks & AF template instantiation (test_oq_15) |
| **URS-021** | Single-sample sensor noise triggering nuisance excursion alarms or overwriting prior e-signatures | `S=4, O=2, D=1` | **High** | Scripted OQ | Stage 2 Swinging Door compression, TrueFor debounce backfill, multi-stage signatures & PI Notifications (test_oq_16) |

