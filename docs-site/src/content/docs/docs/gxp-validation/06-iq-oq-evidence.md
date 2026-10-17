---
title: "Document 06 — Executed IQ/OQ Protocol & Cryptographic Evidence Report"
description: "Document 06 — Executed IQ/OQ Protocol & Cryptographic Evidence Report (15 Automated Tests)."
---
**Document ID:** `EPR-GXPHISTORIAN-2026-006` | **Session Start (UTC):** `2026-10-17T16:56:05.552025+00:00` | **Session End (UTC):** `2026-10-17T16:56:06.553943+00:00` | **Verdict:** **PASS (15/15 Passed, 100.0%)**

## 1. Executed Automated IQ/OQ Test Results (`oq_execution_results.json`)

| Test ID | Pytest Node ID | Start (UTC) | Duration (s) | Executed Assertions & Evidence Summary | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_01_services_and_non_default_credentials` | `2026-10-17T16:56:05.678076+00:00` | `0.0465` | Verified PostgreSQL, ClickHouse, FastAPI, and Grafana health with non-default GxP secrets. | **PASS** |
| **TC-02** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_02_postgres_extensions_and_schema` | `2026-10-17T16:56:05.738157+00:00` | `0.0083` | Verified PostgreSQL 16 extensions (btree_gist, ltree, pgcrypto), 6 GxP tables, and seeded Part 11 users. | **PASS** |
| **TC-03** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_03_clickhouse_compression_codecs` | `2026-10-17T16:56:05.758157+00:00` | `0.0026` | Verified ClickHouse pi_historian.sensor_data column codecs (Delta, DoubleDelta, Gorilla, T64 + ZSTD(1)). | **PASS** |
| **TC-04** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_04_clickhouse_postgres_dictionary_sync` | `2026-10-17T16:56:05.770665+00:00` | `0.0047` | Verified all 5 seeded GxP tags and ISA-95 ltree paths resolve in ClickHouse pg_asset_tags dictionary. | **PASS** |
| **TC-05** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_05_edge_collector_wal_and_deadband` | `2026-10-17T16:56:05.776492+00:00` | `0.0016` | Verified disk-backed WAL buffer configuration and Stage 1 ExceptionDeadbandFilter suppression/emission rules. | **PASS** |
| **TC-06** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_01_reject_mutations_without_actor_or_reason` | `2026-10-17T16:56:05.793119+00:00` | `0.0137` | Confirmed both PostgreSQL PL/pgSQL trigger and FastAPI reject unattributed mutations. | **PASS** |
| **TC-07** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_02_worm_audit_log_immutability` | `2026-10-17T16:56:05.815415+00:00` | `0.0041` | Verified UPDATE, DELETE, and TRUNCATE on part11_audit_log unconditionally raise 21 CFR Part 11 WORM Violation. | **PASS** |
| **TC-08** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_03_electronic_signature_rejects_invalid_credentials` | `2026-10-17T16:56:05.829366+00:00` | `0.0917` | Verified POST /api/v1/event-frames/{id}/sign rejects invalid password with HTTP 401. | **PASS** |
| **TC-09** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_04_electronic_signature_approval_and_hmac` | `2026-10-17T16:56:05.929471+00:00` | `0.1433` | Verified dual-challenge electronic signature execution, HMAC-SHA256 binding, and audit trail logging. | **PASS** |
| **TC-10** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_05_cryptographic_hash_chain_verification` | `2026-10-17T16:56:06.081631+00:00` | `0.047` | Verified 100% of part11_audit_log records form an unbroken SHA-256 hash chain from GENESIS_0000000000000000. | **PASS** |
| **TC-11** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_06_multi_protocol_telemetry_ingestion` | `2026-10-17T16:56:06.138171+00:00` | `0.0054` | Verified active telemetry ingestion across all 5 multi-protocol tags (101, 102, 103, 301, 401). | **PASS** |
| **TC-12** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_07_bad_quality_exclusion_in_rollup` | `2026-10-17T16:56:06.151063+00:00` | `0.0192` | Proved mv_sensor_rollup_1m excludes quality=0 fault spike (9999.0), computing exact GMP rollup avg=37.5, max=38.0. | **PASS** |
| **TC-13** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_08_datalink_linear_and_locf_step_interpolation` | `2026-10-17T16:56:06.182916+00:00` | `0.0574` | Verified exact linear midpoint (37.0) on BR201_TEMP_PV and integer LOCF ([1, 1, 2]) on BR201_AGIT_STATE. | **PASS** |
| **TC-14** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_09_lttb_downsampling_preserves_local_peak` | `2026-10-17T16:56:06.256685+00:00` | `0.0225` | Verified ClickHouse LTTB 10x downsampling (100 -> 10 points) preserved exact peak magnitude (845.75 mAU) and timestamp (12:00:50Z). | **PASS** |
| **TC-15** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_10_event_frame_excursion_and_parquet_lakehouse_export` | `2026-10-17T16:56:06.285597+00:00` | `0.2675` | Verified Event Frame evaluation and Apache Parquet export with 100% row/value fidelity via pyarrow. | **PASS** |

## 2. Live 21 CFR Part 11 Cryptographic Audit Trail Evidence (`part11_audit_log`)

| Audit ID | Recorded At (UTC) | Actor ID | Change Reason | Target Table | Record PK | Op | `prev_hash` Prefix | `row_hash` Prefix |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1` | `2026-10-17 12:19:48.970102+00` | `system_bootstrap` | Initial GxP Qualification Seed | `asset_templates` | `1` | `INSERT` | `GENESIS_000000000000...` | `0980573d8a9a41b46f29...` |
| `2` | `2026-10-17 12:19:48.971843+00` | `system_bootstrap` | Initial GxP Qualification Seed | `asset_templates` | `2` | `INSERT` | `0980573d8a9a41b46f29...` | `0d36bf6886f6f8a95f53...` |
| `3` | `2026-10-17 12:19:48.973299+00` | `system_bootstrap` | Initial GxP Qualification Seed | `assets` | `1` | `INSERT` | `0d36bf6886f6f8a95f53...` | `1e50a1c48c7a31faf35e...` |
| `4` | `2026-10-17 12:19:48.973792+00` | `system_bootstrap` | Initial GxP Qualification Seed | `assets` | `2` | `INSERT` | `1e50a1c48c7a31faf35e...` | `4d8f96f4dc5b6270fb5d...` |
| `5` | `2026-10-17 12:19:48.974952+00` | `system_bootstrap` | Initial GxP Qualification Seed | `tags` | `101` | `INSERT` | `4d8f96f4dc5b6270fb5d...` | `01418e53ac7eea428007...` |
| `6` | `2026-10-17 12:19:48.975413+00` | `system_bootstrap` | Initial GxP Qualification Seed | `tags` | `102` | `INSERT` | `01418e53ac7eea428007...` | `31473f02919047f446ad...` |
| `7` | `2026-10-17 12:19:48.975542+00` | `system_bootstrap` | Initial GxP Qualification Seed | `tags` | `103` | `INSERT` | `31473f02919047f446ad...` | `fa878c93ab51508a0788...` |
| `8` | `2026-10-17 12:19:48.975672+00` | `system_bootstrap` | Initial GxP Qualification Seed | `tags` | `301` | `INSERT` | `fa878c93ab51508a0788...` | `8604eddc066bba1342f4...` |
| `9` | `2026-10-17 12:19:48.975793+00` | `system_bootstrap` | Initial GxP Qualification Seed | `tags` | `401` | `INSERT` | `8604eddc066bba1342f4...` | `4ef258b9cff9b1d15a01...` |
| `10` | `2026-10-17 12:32:12.972505+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `8217b8ad-b909-4b03-8922-aab83751609f` | `INSERT` | `4ef258b9cff9b1d15a01...` | `acf2a3d241e85bb1f95a...` |
| `11` | `2026-10-17 12:32:12.982852+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `d74b43a4-3dab-4181-8c51-8c906f92f451` | `INSERT` | `acf2a3d241e85bb1f95a...` | `bc05d6786059961bfe1c...` |
| `12` | `2026-10-17 12:32:18.018756+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `8217b8ad-b909-4b03-8922-aab83751609f` | `UPDATE` | `bc05d6786059961bfe1c...` | `48bf097edae6380c088c...` |
| `13` | `2026-10-17 12:32:18.05622+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `ca9fcee4-ed1b-4326-9857-ecc8dfd3fabf` | `INSERT` | `48bf097edae6380c088c...` | `3888ca2b4406050e5b12...` |
| `14` | `2026-10-17 12:32:23.09222+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `8217b8ad-b909-4b03-8922-aab83751609f` | `UPDATE` | `3888ca2b4406050e5b12...` | `3ac605d224d849b21779...` |
| `15` | `2026-10-17 12:32:23.100325+00` | `event_frame_engine` | Automated ISA-88 Event Frame Limit Evaluation | `event_frames` | `ca9fcee4-ed1b-4326-9857-ecc8dfd3fabf` | `UPDATE` | `3ac605d224d849b21779...` | `2b553f3b8800131fd39d...` |

## 3. Live Signed ISA-88 Event Frames (`event_frames`)

| Event ID | Event Name | Template | Severity | Start Time | Signed By | Signature Meaning | HMAC-SHA256 Signature Hash |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `0fe19399-8c0c-4379-bb55-583871f7d448` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 16:40:19.789+00` | `qa_approver_01` | Batch Release Approval | `705d6b4d11ed782087a688a1...` |
| `12006ce1-5502-461a-9cb4-3ec7efcc5e46` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 13:20:17.952+00` | `qa_approver_01` | Batch Release Approval | `eb4025c9ecc02a2b7118cd50...` |
| `f5aff8cb-2d04-4fc8-b854-ff8c63943e88` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 12:26:14.459+00` | `qa_approver_01` | Batch Release Approval | `ce044436f26c50818761708b...` |
| `d74b43a4-3dab-4181-8c51-8c906f92f451` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 12:26:14.459+00` | `qa_approver_01` | Excursion Investigation Reviewed | `0ab77f66b7de5503633a3213...` |
| `8217b8ad-b909-4b03-8922-aab83751609f` | **USP_Batch_2026_BR201_001** | `Fermentation_Batch` | `INFO` | `2026-10-17 12:25:32.453+00` | `UNSIGNED` | - | `-...` |
| `225227d5-c56d-448b-ba77-ef48b64b1296` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 19:51:21.513+00` | `UNSIGNED` | - | `-...` |
| `314814c1-e142-41e2-bcfd-51b11f019446` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 19:50:20.504+00` | `UNSIGNED` | - | `-...` |
| `64a92ec2-c66e-4064-a0a0-d2eaf51cac42` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 19:49:19.495+00` | `UNSIGNED` | - | `-...` |

