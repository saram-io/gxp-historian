---
title: "Upstream Bioreactors & Parallel Microbioreactors Integration Guide"
description: "Upstream bioreactor integration for Sartorius Biostat STR & Ambr 15/250 (BioPAT MFCS), Thermo Fisher HyPerforma S.U.B. (TruBio DV), and Eppendorf BioFlo / DASGIP."
---
**Connecting Sartorius Biostat® STR, Sartorius Ambr® 15/250, Thermo Fisher HyPerforma™ (TruBio® DV), and Eppendorf BioFlo® / DASGIP® Systems to OpenHistorian GxP Industrial Historian**

> For **Cytiva Xcellerex™ X-Platform** bioreactors, see the dedicated guide: [XCELLEREX_X_PLATFORM_INTEGRATION.md](/biopharma-integration/xcellerex-x-platform/).

---

## 1. Overview of Upstream Bioreactor Platforms

Upstream Processing (USP) seed trains, Process Development (PD) high-throughput screening, and GMP production vessels rely on four dominant bioreactor automation ecosystems alongside Cytiva Figurate™:

1. **Sartorius Biostat® STR (Gen 3) & Biostat® B-DCU:** Controlled by local **Biobrain / DCU-4** (Siemens SIMATIC S7-1500 PLC) and supervised by **BioPAT® MFCS 4** SCADA, exposing native **OPC UA** and **Siemens S7comm** interfaces.
2. **Sartorius Ambr® 250 High Throughput & Ambr® 15 Cell Culture:** Automated parallel microbioreactor workstations (12, 24, or 48 single-use vessels) exposing a unified **Ambr® OPC UA Server** (or bridged via BioPAT® MFCS) with multi-vessel namespace trees.
3. **Thermo Fisher Scientific HyPerforma™ S.U.B. / S.U.F. (50 L – 5000 L):** Powered by **TruBio® DV** software built natively on **Emerson DeltaV™ DCS**, exposing **OPC UA** (DeltaV PK / Application Station) and legacy **OPC DA**.
4. **Eppendorf BioFlo® 320 / 720 & DASGIP® Parallel Bioreactors:** Equipped with **DASware® connect**, which provides an integrated **OPC UA** and **OPC DA** server for seamless historian and DoE integration.

---

## 2. Integration Architecture

```mermaid
flowchart LR
  subgraph USP["Upstream Bioreactor Skids & Workstations"]
    SART["Sartorius Biostat® STR Gen 3\n(Biobrain S7-1500 / BioPAT® MFCS 4)"]
    AMBR["Sartorius Ambr® 250 / Ambr® 15\n(12–48 Parallel Vessels OPC UA)"]
    TRUBIO["Thermo Fisher HyPerforma™ S.U.B.\n(TruBio® DV / Emerson DeltaV™)"]
    EPP["Eppendorf BioFlo® / DASGIP®\n(DASware® connect)"]
  end

  subgraph Edge["Pillar 1: Edge Collector (edge-collector)"]
    OPCUA["Telegraf [[inputs.opcua]] /\nPython Deadband Worker"]
    S7["Siemens S7comm Worker\n(Rack/Slot DB Polling)"]
    WAL["Telegraf Disk WAL\n(/var/lib/telegraf/buffer)"]
    OPCUA --> WAL
    S7 --> WAL
  end

  subgraph Core["OpenHistorian GxP Historian"]
    CH["ClickHouse 24.8 Archive\n(pi_historian.sensor_data)"]
    PG["PostgreSQL 16 Control Plane\n(ltree ISA-95 + Event Frames)"]
  end

  SART -->|"OPC UA (:4840) or S7comm (:102)"| OPCUA
  SART -.->|"Direct S7-1500 DB"| S7
  AMBR -->|"OPC UA (:4840)"| OPCUA
  TRUBIO -->|"DeltaV OPC UA (:4840)"| OPCUA
  EPP -->|"DASware connect OPC UA"| OPCUA
  WAL -->|"JSONEachRow"| CH
  PG -.->|"pg_asset_tags Dictionary"| CH
```

---

## 3. Platform-Specific Configuration

### 3.1 Sartorius Biostat® STR (Gen 3) & BioPAT® MFCS 4
Sartorius **BioPAT® MFCS 4** acts as the supervisory SCADA and batch server for Biostat® B, Biostat® D-DCU, and Biostat® STR single-use bioreactors, while **Biostat® STR Gen 3** also offers direct OPC UA server access from its **Biobrain** (Siemens S7-1500) automation controller.

#### Option 1: OPC UA via BioPAT® MFCS 4 or Biobrain (`edge-collector/telegraf-clickhouse.conf`)
```toml
[[inputs.opcua]]
  name = "sensor_data"
  endpoint = "opc.tcp://10.20.40.15:4840"
  security_policy = "Basic256Sha256"
  security_mode = "SignAndEncrypt"
  certificate = "/etc/telegraf/certs/openhistorian_client_cert.pem"
  private_key = "/etc/telegraf/certs/openhistorian_client_key.pem"
  auth_method = "UserName"
  username = "${MFCS_OPCUA_USER}"
  password = "${MFCS_OPCUA_PASSWORD}"

  nodes = [
    # Biostat STR 2000L Process Variables
    { name = "val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Variables.TEMP.Value", default_tags = { tag_id = "201" } },
    { name = "val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Variables.PH1.Value",  default_tags = { tag_id = "202" } },
    { name = "val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Variables.PO2_1.Value", default_tags = { tag_id = "203" } },
    { name = "val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Variables.STIRR.Value", default_tags = { tag_id = "204" } },
    { name = "val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Variables.SUBS_A.Value", default_tags = { tag_id = "205" } },
    { name = "str_val", namespace = "2", identifier_type = "s", identifier = "Units.STR2000_01.Batch.PhaseName", default_tags = { tag_id = "206" } }
  ]
```

#### Option 2: Direct Siemens S7-1500 (`S7COMM`) Polling
For discrete safety interlocks, agitator drive status words, or jacket valve states stored in non-optimized S7-1500 Data Blocks (`DB`), OpenHistorian natively supports `S7COMM` metadata in `tags.source_config` (matching seeded Tag `103` in `init-postgres/01_control_plane_part11.sql`):
```json
{
  "plc_ip": "10.20.40.16",
  "rack": 0,
  "slot": 1,
  "db": 10,
  "offset": 0,
  "data_type": "INT"
}
```

---

### 3.2 Sartorius Ambr® 250 High Throughput & Ambr® 15 (Multi-Vessel Array Pattern)
An **Ambr® 250** (12 or 24 vessels) or **Ambr® 15** (24 or 48 vessels) generates hundreds of tags across parallel mini-bioreactors running Design of Experiments (DoE) clone selection or media optimization studies.

Because OpenHistorian GxP Historian models its Asset Framework in PostgreSQL using `ltree` (`assets.asset_path`) and `asset_templates`, you can instantiate all 24 or 48 Ambr vessels from a single template in one audited SQL transaction:

```sql
BEGIN;
SET LOCAL app.actor_id = 'operator_01';
SET LOCAL app.change_reason = 'Provision Ambr 250 HT 24-Vessel DoE Array in USP PD Lab';

-- 1. Create Reusable Ambr 250 Vessel Template
INSERT INTO asset_templates (template_id, template_name, attribute_specs) VALUES
  (10, 'Sartorius_Ambr250_Vessel_Template', '[
    {"attribute_name": "Vessel_Temperature", "eng_units": "degC", "low_limit": 36.0, "high_limit": 37.5, "is_step_tag": false},
    {"attribute_name": "Media_pH", "eng_units": "pH", "low_limit": 6.7, "high_limit": 7.3, "is_step_tag": false},
    {"attribute_name": "Dissolved_Oxygen", "eng_units": "%Sat", "low_limit": 20.0, "high_limit": 100.0, "is_step_tag": false},
    {"attribute_name": "Stirrer_Speed", "eng_units": "RPM", "low_limit": 100.0, "high_limit": 1500.0, "is_step_tag": false},
    {"attribute_name": "Pumped_Base_Volume", "eng_units": "mL", "is_step_tag": false}
  ]'::jsonb)
ON CONFLICT (template_id) DO NOTHING;

-- 2. Register Vessels 01..24 under BioCorp.Fremont.PD_USP.Ambr250_01.Vessel_XX
INSERT INTO assets (asset_name, asset_path, template_id, metadata)
SELECT
  format('Ambr250_Vessel_%s', lpad(v::text, 2, '0')),
  text2ltree(format('BioCorp.Fremont.PD_USP.Ambr250_01.Vessel_%s', lpad(v::text, 2, '0'))),
  10,
  jsonb_build_object('vessel_number', v, 'working_volume_mL', 250, 'system', 'Sartorius Ambr 250 HT')
FROM generate_series(1, 24) AS v
ON CONFLICT (asset_path) DO NOTHING;

COMMIT;
```

In Grafana (`openhistorian_bioreactor_hmi.json`), changing the `$asset_path` dropdown or querying `asset_path <@ 'BioCorp.Fremont.PD_USP.Ambr250_01'` in ClickHouse via `dictGet('pi_historian.pg_asset_tags', 'asset_path', toUInt64(tag_id))` lets scientists overlay all 24 vessels or export the entire 24-vessel DoE dataset into a single Apache Parquet file (`POST /api/v1/lakehouse/export-parquet` with `"asset_path": "BioCorp.Fremont.PD_USP.Ambr250_01"`).

---

### 3.3 Thermo Fisher HyPerforma™ S.U.B. / TruBio® DV & Eppendorf DASware® connect

#### Thermo Fisher HyPerforma™ with TruBio® DV (DeltaV™)
TruBio® DV uses standard Emerson DeltaV™ modules (e.g., `TC-101` temperature control loop, `AC-101` pH control loop, `AC-102` DO control loop, `FC-101..104` gas MFCs, `SC-101` agitator speed, and `WC-101` vessel weight).
- **Modern DeltaV (v13/v14/v15+):** Connect `edge-collector` directly to the DeltaV Application Station / PK Controller OPC UA Server (`opc.tcp://<deltav-app-station>:4840`).
- **Legacy DeltaV OPC Mirror (OPC DA 2.05a):** Run `edge-collector/scripts/opcda_windows_forwarder.py` with `OPCDA_PROG_ID="OPC.DeltaV.1"` directly on the DeltaV Application Station to stream deadband-filtered JSON batches to `http://<edge-collector>:8080/ingest`.

#### Eppendorf BioFlo® / DASGIP® with DASware® connect
DASware® connect exposes each reactor module (`Unit 1` .. `Unit 16`) over OPC UA (`opc.tcp://<dasware-host>:4840/DASwareConnect`):
- Map `UnitX.T.PV` (Temperature), `UnitX.pH.PV` (pH), `UnitX.DO.PV` (Dissolved Oxygen), `UnitX.N.PV` (Agitation RPM), `UnitX.F.PV` ( Gas Flow `sL/h`), and `UnitX.Level.PV` (Foam/Level) with `is_step_tag = false`.
- Map `UnitX.InoculationTime` and `UnitX.ProcessState` with `is_step_tag = true` (`LOCF`).

---

## 4. Recommended Tag Deadband & Limit Reference for USP Bioreactors

| Parameter | Eng Units | `is_step_tag` | Recommended `exc_dev` | Recommended `exc_max` | Typical Mammalian Cell Culture Limits |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Vessel Temperature (`TEMP.PV`)** | `degC` | `false` (`LINEAR`) | `0.05` | `10.0 s` | `35.0` – `38.0 °C` |
| **Media pH (`PH.PV`)** | `pH` | `false` (`LINEAR`) | `0.02` | `10.0 s` | `6.80` – `7.40 pH` |
| **Dissolved Oxygen (`DO.PV`)** | `%Sat` | `false` (`LINEAR`) | `0.20` | `10.0 s` | `20.0` – `100.0 %Sat` |
| **Dissolved $\text{CO}_2$ (`pCO2.PV`)** | `mmHg` | `false` (`LINEAR`) | `0.50` | `30.0 s` | `20.0` – `120.0 mmHg` |
| **Agitation Speed (`AGIT_RPM.PV`)** | `RPM` | `false` (`LINEAR`) | `0.50` | `30.0 s` | Vessel scale dependent |
| **Agitator / Pump State** | `state` | `true` (`LOCF`) | `0.00` | `60.0 s` | `0` (`OFF`), `1` (`LOW`), `2` (`RUN`) |
| **Sparger / Overlay MFCs ($\text{Air}, \text{O}_2, \text{CO}_2, \text{N}_2$)** | `SLPM` | `false` (`LINEAR`) | `0.02` | `15.0 s` | `0.0` – Max MFC rating |
| **Vessel Weight / Feed Scale (`WT.PV`)** | `kg` or `g` | `false` (`LINEAR`) | `0.10` | `30.0 s` | Scale capacity limits |
| **Redox Potential (`ORP.PV`)** | `mV` | `false` (`LINEAR`) | `1.00` | `30.0 s` | `-400` – `+400 mV` |
| **ISA-88 Batch Phase (`PHASE_STATE`)** | `phase` | `true` (`LOCF`) | `0.00` | `60.0 s` | String state in `str_val` |

