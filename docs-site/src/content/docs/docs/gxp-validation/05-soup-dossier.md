---
title: "Document 05 — SOUP / Open-Source Software (OSS) Vendor Qualification Dossier"
description: "Document 05 — SOUP / Open-Source Software Vendor Qualification Dossier & Container SHA-256 Digests."
---
**Document ID:** `SOUP-GXPHISTORIAN-2026-005` | **Generated (UTC):** `2026-10-18T19:42:45Z` | **Standard:** GAMP 5 Category 3/4 & ISO/IEC 62304 SOUP Qualification

## 1. Qualified Open-Source Software & Live Container SHA-256 Digest Matrix

| Service Container | Software Component | License | Corporate / Foundation Backing | GAMP Category | Live Container Image `@sha256` Digest | Supply-Chain & GxP Controls |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `clickhouse-archive` | **ClickHouse Server 24.8 LTS** | `Apache-2.0` | ClickHouse, Inc. | Category 4 (Configured Time-Series Archive) | `sha256:b002e56ed5c16e224c312527f6fcba7e77216fec5d7a88a7828f59efc614feb5` | Alpine 3.20 minimal base, pinned @sha256 digest, read-only init mounts, non-default auth |
| `postgres-control` | **PostgreSQL 16 (ltree + pgcrypto)** | `PostgreSQL License (OSI Approved)` | PostgreSQL Global Development Group | Category 4 (Configured Relational Control Plane) | `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685` | Alpine minimal image, cryptographic pgcrypto SHA-256 & bcrypt triggers, WORM enforcement |
| `instrument-mock-server` | **Multi-Protocol Biopharma Instrument Mock Server (OPC UA / Modbus / BACnet / S7 / Serial / OPC DA)** | `MIT / Apache-2.0` | GxPHistorian / Python Software Foundation | Category 5 (Multi-Protocol Qualification Simulator) | `sha256:04735be0226f8e577065458fd68c7fe88f43f17f500f99a453093bf94d8c2ae9` | Isolated Docker network listeners (:4840, :5020, :47808/udp, :1102, :4001, :8095), deterministic wire-format verification |
| `edge-collector` | **InfluxData Telegraf 1.32 + Python 3.12 Execd Worker** | `MIT License / PSF License` | InfluxData / Python Software Foundation | Category 4 / Category 5 (Custom Deadband Script) | `sha256:cb42fe2988d21a5c7d65ffb12ffdd562549ad5a2c7ec467d8271e4f7d46a48a7` | Disk-backed WAL (/var/lib/telegraf/buffer), local localhost COM/HTTP isolation |
| `historian-api` | **FastAPI 0.115 / Uvicorn / PyArrow 17 / Psycopg 3** | `MIT / Apache-2.0 / LGPL-3.0` | FastAPI / Apache Software Foundation | Category 5 (Custom GxP Application Layer) | `sha256:5299006ee553ce68bc9a88a42b97fd86211541ee3587c9559fa2e21d2fa60104` | Pinned requirements.txt versions, mandatory Part 11 header enforcement, 100% OQ test coverage |
| `gxphistorian-mcp` | **Pydantic AI 2.0 + FastMCP Streamable HTTP Server** | `MIT / Apache-2.0` | Pydantic Services Inc. / Prefect Technologies | Category 5 (Advisory AI Co-Pilot & MCP Server) | `sha256:fa13138908164594243a1181f867aa0a81e3c9300dc8fd423d18035d253ca64c` | Read-only quality >= 192 queries, ApprovalRequired Part 11 mutation gate, zero e-signature bypass |
| `grafana-vision` | **Grafana OSS 11.2.0 + ClickHouse Datasource Plugin** | `AGPL-3.0 / Apache-2.0` | Grafana Labs | Category 4 (Configured HMI Visualization) | `sha256:408afb9726de5122b00a2576763a8a57a3c86d5b0eff5305bc994ceb3eb96c3f` | Read-only provisioned datasources, non-default admin credentials, zero direct DB write privileges |

