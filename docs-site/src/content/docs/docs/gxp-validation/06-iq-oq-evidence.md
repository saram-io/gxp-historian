---
title: "Document 06 — Executed IQ/OQ Protocol & Cryptographic Evidence Report"
description: "Document 06 — Executed IQ/OQ Protocol & Cryptographic Evidence Report (17 Automated Tests)."
---
**Document ID:** `EPR-GXPHISTORIAN-2026-006` | **Session Start (UTC):** `2026-10-17T21:20:39.505782+00:00` | **Session End (UTC):** `2026-10-17T21:20:41.678732+00:00` | **Verdict:** **PASS (17/17 Passed, 100.0%)**

## 1. Executed Automated IQ/OQ Test Results (`oq_execution_results.json`)

| Test ID | Pytest Node ID | Start (UTC) | Duration (s) | Executed Assertions & Evidence Summary | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_01_services_and_non_default_credentials` | `2026-10-17T21:20:39.970921+00:00` | `0.0404` | Verified PostgreSQL, ClickHouse, FastAPI, and Grafana health with non-default GxP secrets. | **PASS** |
| **TC-02** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_02_postgres_extensions_and_schema` | `2026-10-17T21:20:40.021429+00:00` | `0.0084` | Verified PostgreSQL 16 extensions (btree_gist, ltree, pgcrypto), 6 GxP tables, and seeded Part 11 users. | **PASS** |
| **TC-03** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_03_clickhouse_compression_codecs` | `2026-10-17T21:20:40.039575+00:00` | `0.003` | Verified ClickHouse pi_historian.sensor_data column codecs (Delta, DoubleDelta, Gorilla, T64 + ZSTD(1)). | **PASS** |
| **TC-04** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_04_clickhouse_postgres_dictionary_sync` | `2026-10-17T21:20:40.050924+00:00` | `0.0035` | Verified all 5 seeded GxP tags and ISA-95 ltree paths resolve in ClickHouse pg_asset_tags dictionary. | **PASS** |
| **TC-05** | `gxp-validation-package/tests/test_01_iq_infrastructure.py::test_iq_05_edge_collector_wal_and_deadband` | `2026-10-17T21:20:40.055345+00:00` | `0.0011` | Verified disk-backed WAL buffer configuration and Stage 1 ExceptionDeadbandFilter suppression/emission rules. | **PASS** |
| **TC-06** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_01_reject_mutations_without_actor_or_reason` | `2026-10-17T21:20:40.069923+00:00` | `0.0144` | Confirmed both PostgreSQL PL/pgSQL trigger and FastAPI reject unattributed mutations. | **PASS** |
| **TC-07** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_02_worm_audit_log_immutability` | `2026-10-17T21:20:40.096811+00:00` | `0.0042` | Verified UPDATE, DELETE, and TRUNCATE on part11_audit_log unconditionally raise 21 CFR Part 11 WORM Violation. | **PASS** |
| **TC-08** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_03_electronic_signature_rejects_invalid_credentials` | `2026-10-17T21:20:40.112150+00:00` | `0.0911` | Verified POST /api/v1/event-frames/{id}/sign rejects invalid password with HTTP 401. | **PASS** |
| **TC-09** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_04_electronic_signature_approval_and_hmac` | `2026-10-17T21:20:40.209120+00:00` | `0.2172` | Verified dual-challenge electronic signature execution, HMAC-SHA256 binding, and audit trail logging. | **PASS** |
| **TC-10** | `gxp-validation-package/tests/test_02_oq_part11_compliance.py::test_oq_05_cryptographic_hash_chain_verification` | `2026-10-17T21:20:40.434308+00:00` | `0.0758` | Verified 100% of part11_audit_log records form an unbroken SHA-256 hash chain from GENESIS_0000000000000000. | **PASS** |
| **TC-11** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_06_multi_protocol_telemetry_ingestion` | `2026-10-17T21:20:40.518892+00:00` | `0.007` | Verified active telemetry ingestion across all 5 multi-protocol tags (101, 102, 103, 301, 401). | **PASS** |
| **TC-12** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_07_bad_quality_exclusion_in_rollup` | `2026-10-17T21:20:40.533897+00:00` | `0.0373` | Proved mv_sensor_rollup_1m excludes quality=0 fault spike (9999.0), computing exact GMP rollup avg=37.5, max=38.0. | **PASS** |
| **TC-13** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_08_datalink_linear_and_locf_step_interpolation` | `2026-10-17T21:20:40.586473+00:00` | `0.0575` | Verified exact linear midpoint (37.0) on BR201_TEMP_PV and integer LOCF ([1, 1, 2]) on BR201_AGIT_STATE. | **PASS** |
| **TC-14** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_09_lttb_downsampling_preserves_local_peak` | `2026-10-17T21:20:40.659313+00:00` | `0.0211` | Verified ClickHouse LTTB 10x downsampling (100 -> 10 points) preserved exact peak magnitude (845.75 mAU) and timestamp (12:00:50Z). | **PASS** |
| **TC-15** | `gxp-validation-package/tests/test_03_oq_historian_core.py::test_oq_10_event_frame_excursion_and_parquet_lakehouse_export` | `2026-10-17T21:20:40.686786+00:00` | `0.2702` | Verified Event Frame evaluation and Apache Parquet export with 100% row/value fidelity via pyarrow. | **PASS** |
| **TC-16** | `gxp-validation-package/tests/test_04_ai_agent_and_mcp.py::test_oq_11_pydantic_ai_deviation_investigator_and_mcp` | `2026-10-17T21:20:40.964214+00:00` | `0.4761` | Verified Pydantic AI `gxp_deviation_investigator_agent` produces a validated `DeviationInvestigationBrief` with `part11-forensics` capability and `gxphistorian-mcp` manifest. | **PASS** |
| **TC-17** | `gxp-validation-package/tests/test_04_ai_agent_and_mcp.py::test_oq_12_pydantic_ai_part11_human_in_the_loop_tag_approval` | `2026-10-17T21:20:41.446523+00:00` | `0.2313` | Verified Pydantic AI `ApprovalRequired` (`DeferredToolRequests` / `DeferredToolResults`), `args_validator` `ModelRetry` recovery, and 21 CFR Part 11 WORM audit logging. | **PASS** |

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
| `2afff150-dbad-4919-b3df-3e5d1250d988` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 21:05:22.193+00` | `qa_approver_01` | Batch Release Approval | `9de08871f6bf6288d58ded3b...` |
| `0fe19399-8c0c-4379-bb55-583871f7d448` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 16:40:19.789+00` | `qa_approver_01` | Batch Release Approval | `705d6b4d11ed782087a688a1...` |
| `12006ce1-5502-461a-9cb4-3ec7efcc5e46` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 13:20:17.952+00` | `qa_approver_01` | Batch Release Approval | `eb4025c9ecc02a2b7118cd50...` |
| `f5aff8cb-2d04-4fc8-b854-ff8c63943e88` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 12:26:14.459+00` | `qa_approver_01` | Batch Release Approval | `ce044436f26c50818761708b...` |
| `d74b43a4-3dab-4181-8c51-8c906f92f451` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 12:26:14.459+00` | `qa_approver_01` | Excursion Investigation Reviewed | `0ab77f66b7de5503633a3213...` |
| `8217b8ad-b909-4b03-8922-aab83751609f` | **USP_Batch_2026_BR201_001** | `Fermentation_Batch` | `INFO` | `2026-10-17 12:25:32.453+00` | `UNSIGNED` | - | `-...` |
| `ef356048-497b-40ed-8e88-ec5f1861e2ec` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 21:04:21.185+00` | `UNSIGNED` | - | `-...` |
| `6c6c18ea-685d-4e3f-a4f4-7f29b4a26357` | **BR201_TEMP_PV_High_Limit_Excursion** | `Temp_Excursion` | `CRITICAL` | `2026-10-17 21:02:22.167+00` | `UNSIGNED` | - | `-...` |

