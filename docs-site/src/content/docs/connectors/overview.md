---
title: "Connectors, Protocols & Wiring Encyclopedia: Master Reference"
description: "Master visual encyclopedia of all physical hardware connectors (RJ45, M12 D/X/A-Coded, DB9 RS-232, Phoenix RS-485 & 4–20 mA terminals) and 10 software protocol connectors in GxPHistorian."
---
**Document ID:** `REF-CONNECTORS-ENCYCLOPEDIA-GXPHISTORIAN-2026`  
**Scope:** Complete Visual & Technical Reference for Every Physical Hardware Connector (Layer 1) and Software Protocol Connector (Layer 7) Supported by **GxPHistorian**  
**Regulatory Alignment:** 21 CFR Part 11, EU GMP Annex 11, ISPE GAMP 5 (Second Edition), IEC 62443 (Industrial Cybersecurity), NAMUR NE 43, ASHRAE 135, IEC 62541

---

## 1. Visual Overview: Physical Hardware Plugs vs. Software Protocol Connectors

When connecting laboratory, cleanroom, or utility equipment to **GxPHistorian**, there are always **two layers** to understand:
1. **The Physical Connector (OSI Layer 1 — "What Plug Is on the Back of the Machine?"):** Is it an 8-pin **RJ45 Ethernet** jack, a circular waterproof **M12 screw-lock** socket, a 9-pin **DB9 RS-232** serial port, or a green **Phoenix screw-terminal** block (`RS-485` / `4–20 mA`)?
2. **The Software Protocol Connector (OSI Layer 7 — "What Language Does the Machine Speak Over That Wire?"):** Does it speak **OPC UA**, **Classic OPC DA**, **BACnet/IP & MS/TP**, **Modbus TCP/RTU**, **Siemens S7comm**, **Allen-Bradley EtherNet/IP**, **4–20 mA + HART**, **RS-232 ASCII (`MT-SICS` / `ASTM`)**, or **File Watch-Folder (`CSV/XML` UFL)**?

![GxPHistorian Connectors Encyclopedia: Physical Plugs & Software Protocols](/images/connectors/connector-encyclopedia-overview.svg)

Also refer to our step-by-step physical connector field guide for non-technical operators and scientists:

![Physical Connectors Field Guide for Non-Technical Users](/images/instruments/physical-connectors-field-guide.svg)

---

## 2. Part 1: Physical Hardware Connectors (What They Look Like & Pinouts)

### 2.1 RJ45 (8P8C) Industrial & Cleanroom Ethernet Connector
- **What It Looks Like:** Rectangular 8-pin modular jack with a plastic retaining clip and two status LEDs (**Green = Link**, **Amber blinking = Activity**).
- **Cables Used:**
  - **Cat6 UTP (Unshielded Twisted Pair):** Standard for benchtop laboratory analyzers (Vi-CELL BLU, BioProfile FLEX2, Binder stability chambers).
  - **Cat6A S/FTP (Shielded Foiled Twisted Pair with metal RJ45 shell):** Mandatory inside industrial PLC cabinets (Xcellerex, Biostat STR, Lyophilizers) to prevent Variable Frequency Drive (VFD) motor electromagnetic interference (EMI) from corrupting packets.
- **T568B Pinout (100BASE-TX & 1000BASE-T Gigabit Ethernet + 802.3af PoE):**
  - **Pin 1 (`White/Orange`) & Pin 2 (`Orange`):** Transmit Differential Pair (`TX+` / `TX-` at 100 Mbps; Bidirectional Pair A at 1 Gbps).
  - **Pin 3 (`White/Green`) & Pin 6 (`Green`):** Receive Differential Pair (`RX+` / `RX-` at 100 Mbps; Bidirectional Pair B at 1 Gbps).
  - **Pin 4 (`Blue`) & Pin 5 (`White/Blue`):** Bidirectional Pair C (1 Gbps) + **Power-over-Ethernet (PoE Mode B `+48V DC`)** used by fixed cleanroom particle counters (**PMS Airnet® II**).
  - **Pin 7 (`White/Brown`) & Pin 8 (`Brown`):** Bidirectional Pair D (1 Gbps) + **PoE Mode B Return (`0V`)**.

### 2.2 M12 Circular Metric Washdown Connectors (`IP67` / `IP69K`)
Stainless-steel cleanroom skids that undergo caustic CIP/SIP and VHP/sporicidal washdowns replace rectangular RJ45 jacks with **12 mm threaded circular metal connectors (IEC 61076-2-101)**. Because an M12 plug has a mechanical keyway notch, **you must match the letter code**:

| M12 Coding | Number of Pins | Keyway Notch Position | Electrical Standard | Where You Will See It in Biopharma |
| :--- | :--- | :--- | :--- | :--- |
| **M12 D-Coded** | **4-Pin** (`TX+`, `TX-`, `RX+`, `RX-`) | Rectangular keyway | **100BASE-TX Industrial Ethernet** / PROFINET / EtherNet/IP | Bulkhead SCADA ports on **[Sartorius Sartoflow®](https://www.sartorius.com/en/products/tangential-flow-filtration-tff/tff-systems)**, **[Biostat STR®](https://www.sartorius.com/en/products/bioreactors-fermenters/single-use-bioreactors/biostat-str-generation-3-1110594)**, and **[Cytiva NanoAssemblr™](https://www.cytivalifesciences.com/en/us/shop/lipid-nanoparticle-instruments-and-reagents/nanoparticle-formulation-systems/nanoassemblr-commercial-formulation-system-p-43407)** washdown carts (use an *M12 D-Coded Male to RJ45 Male* patch cord). |
| **M12 X-Coded** | **8-Pin** (4 shielded pairs separated by an X-shaped metal cross) | X-shaped metal divider | **10 Gbps Gigabit Industrial Ethernet** (+ PoE) | High-speed vision inspection machines, newer **[Siemens SCALANCE](https://www.siemens.com)** cleanroom switches, and **Bausch+Ströbel** isolator bulkheads. |
| **M12 A-Coded** | **4-Pin, 5-Pin, or 8-Pin** | Single round notch | **$24\text{V DC}$ + RS-485 Modbus RTU** / CANopen / `4–20 mA` | **[Hamilton Arc® Smart Sensors](https://www.hamiltoncompany.com/process-analytics/arc-sensors)** (`EasyFerm Plus pH`, `VisiFerm DO`, `Incyte VCD` use an **8-Pin M12 A-Coded** socket on top of the sensor head). |

### 2.3 DB9 (DE-9) 9-Pin D-Subminiature Serial & MPI Connector
- **What It Looks Like:** Metallic D-shaped shield with 5 pins on the top row (`Pins 1–5`) and 4 pins on the bottom row (`Pins 6–9`), flanked by two #4-40 thumbscrews.
- **Warning — Three Completely Different Protocols Use the Same 9-Pin DB9 Shell:**
  1. **RS-232 Serial (`±3V` to `±15V` single-ended):** Used on analytical balances (**[Mettler Toledo XPR](https://www.mt.com/us/en/home/products/Laboratory_Weighing_Solutions/Balances/XPR-analytical-balance.html)**, **[Sartorius Cubis® II](https://www.sartorius.com/en/products/lab-weighing/lab-balances/cubis-ii)**), osmometers (**[Advanced Instruments OsmoTECH®](https://www.aicompanies.com/product/osmotech-xt-single-sample-micro-osmometer/)**), and controlled-rate freezers (**[Planer Kryo 560](https://planer.com)**). Uses **Pin 2 (`RX`)**, **Pin 3 (`TX`)**, and **Pin 5 (`GND`)**.
  2. **RS-485 / RS-422 Serial (`0V` to `+5V` differential):** Used on industrial gateways (**[Moxa NPort 5150](https://www.moxa.com/en/products/industrial-edge-connectivity/serial-device-servers/general-device-servers/nport-5100-series)** configurable modes).
  3. **Siemens MPI / PROFIBUS DP (`RS-485` + `+24V` power on Pin 7, `+5V` on Pin 6):** Used on legacy **Siemens S7-300 / S7-400** PLCs. **Never** plug a standard RS-232 cable into a Siemens `MPI/DP` port—use a **[Helmholz NETLink® PRO Compact](https://www.helmholz.de/en/products/fieldbus-applications/profibus/gateways/netlink-pro/artikel/show/700-884-mpi21/)** adapter!

### 2.4 Pluggable Green Screw-Terminal Blocks (Phoenix Contact / Euroblock) & DIN-Rail Gateways
- **What It Looks Like:** Green polyamide pluggable connector (`3.81 mm` or `5.08 mm` pitch) where bare stripped copper wires (`16–24 AWG` or ferrules) are clamped under flathead screws.
- **Used For & Recommended DIN-Rail Gateways (with Official Product Links):**
  - **2-Wire RS-485 (`Modbus RTU` & `BACnet MS/TP`):** Three terminals labeled **`D+` (or `B` / `MS/TP+`)**, **`D-` (or `A` / `MS/TP-`)**, and **`GND` (or `S` / `COM`)** $\rightarrow$ Bridge via **[Moxa MGate MB3180](https://www.moxa.com/en/products/industrial-edge-connectivity/protocol-gateways/modbus-tcp-gateways/mgate-mb3180-mb3280-mb3480-series)** (Modbus RTU-to-TCP) or **[Contemporary Controls BASrouter](https://www.ccontrols.com/basautomation/basrouters.php)** / **[LOYTEC LIP-ME201](https://www.loytec.com)** (BACnet MS/TP-to-IP).
  - **4–20 mA Current Loops & 4-Wire Class A PT100 RTD Probes:** Two terminals (`AI+`/`AI-`) or four terminals (`I+`/`V+`/`V-`/`I-`) $\rightarrow$ Digitize via **[Advantech ADAM-6017 / ADAM-6015](https://www.advantech.com/en/products/iot-modules/adam-6017/mod_9df3d854-3e9a-4712-9856-d76ffefb2100)** into Modbus TCP (`:502`).

---

## 3. Part 2: Master Comparison of All 10 Software Protocol Connectors

| Connector / Protocol Name | Transport & Default Port | Addressing / Tag Format | Data Acquisition Mechanism | Native Quality & Diagnostic Bits | GxPHistorian Pillar 1 Implementation | Detailed Deep-Dive Guide |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. OPC UA (`IEC 62541`)** | `TCP :4840` (`opc.tcp://`) | `ns=<idx>;s=<String>` or `ns=<idx>;i=<Int>` | **Report-by-Exception Subscriptions** (`MonitoredItems`) or Polling | 32-Bit `StatusCode` (`0x00000000` Good $\rightarrow$ `192`, `0x40000000` Uncertain $\rightarrow$ `64`, `0x80000000` Bad $\rightarrow$ `0`) | Telegraf `[[inputs.opcua]]` + Python Deadband Worker | [CONNECTOR_GUIDE_OPC_UA_AND_OPC_DA.md](/connectors/opc-ua-and-opc-da/) |
| **2. Classic OPC DA (`2.05a / 3.0`)** | Windows Local `COM` $\rightarrow$ Outbound `HTTP :8080` | `ProgID` + Hierarchical `ItemID` (`AKTA.UV1_280.Value`) | Localhost `127.0.0.1` COM Group/Item Read + Disk Spool | 8-Bit COM Quality (`0xC0` Good $\rightarrow$ `192`, `0x40` Uncertain $\rightarrow$ `64`, `0x00` Bad $\rightarrow$ `0`) | `edge-collector/scripts/opcda_windows_forwarder.py` | [CONNECTOR_GUIDE_OPC_UA_AND_OPC_DA.md](/connectors/opc-ua-and-opc-da/) |
| **3. BACnet/IP (`ASHRAE 135 Annex J`)** | `UDP :47808` (`0xBAC0`) | `Device_ID` + `Object_Type,Instance` (`analog-input,1`) | **`SubscribeCOV` (Change of Value)** or `ReadPropertyMultiple` | 4-Bit `Status_Flags` (`[in_alarm, fault, overridden, out_of_service]`) | `edge-collector/scripts/bacnet_cov_worker.py` | [CONNECTOR_GUIDE_BACNET_IP_AND_MSTP.md](/connectors/bacnet-ip-and-mstp/) |
| **4. BACnet MS/TP (`EIA-485`)** | `RS-485` (`9600–76800` bd) $\rightarrow$ Router `UDP :47808` | Routed `DNET:DADR` (`2001:13`) + `Object_ID` | Token-passing ring bridged via BACnet/IP Router / BBMD | Same 4-Bit `Status_Flags` preserved end-to-end by router | `bacnet_cov_worker.py` via LOYTEC / BASrouter | [CONNECTOR_GUIDE_BACNET_IP_AND_MSTP.md](/connectors/bacnet-ip-and-mstp/) |
| **5. Modbus TCP** | `TCP :502` (`MBAP` frame) | `Unit_ID (1..247)` + Register `0x/1x/3x/4x` | Master/Client Polling (`FC 01, 02, 03, 04`) | TCP Socket + Modbus Exception Code (`0x01..0x0B` $\rightarrow$ `quality = 0`) | Telegraf `[[inputs.modbus]]` (`ABCD`/`CDAB` Float32) | [CONNECTOR_GUIDE_MODBUS_TCP_AND_RTU.md](/connectors/modbus-tcp-and-rtu/) |
| **6. Modbus RTU** | `RS-485` / `RS-232` $\rightarrow$ Moxa Gateway `:502` | `Slave_ID (1..247)` + Register Offset | Serial Master/Slave with 16-bit `CRC-16` checksum | `CRC-16` validation + Exception Code + Gateway timeout check | Telegraf `[[inputs.modbus]]` (`rtuovertcp` or MGate) | [CONNECTOR_GUIDE_MODBUS_TCP_AND_RTU.md](/connectors/modbus-tcp-and-rtu/) |
| **7. Siemens S7comm (`RFC 1006`)** | `TCP :102` (ISO-on-TCP) | `Rack/Slot` + Data Block (`DB10.DBD0`, `DB10.DBW4`) | Direct Data Block memory read (`PUT/GET` protocol) | PDU return code `0xFF` (Success $\rightarrow$ `192`) vs access error (`0`) | Python `snap7` / S7comm Edge Worker | [CONNECTOR_GUIDE_PLC_S7_ETHERNETIP_HART_SERIAL_UFL.md](/connectors/plc-s7-ethernetip-hart-serial-ufl/) |
| **8. Allen-Bradley EtherNet/IP (`CIP`) & DF1** | `TCP :44818` (Explicit CIP) | Symbolic Tag (`Tank_Temp_PV`) or PCCC (`F8:0`) | CIP `ReadTagFragmented` (`0x52`) service | CIP General Status `0x00` + PlantPAx `.Sts_Bad` bit | Python `pycomm3` (`LogixDriver` / `SLCDriver`) | [CONNECTOR_GUIDE_PLC_S7_ETHERNETIP_HART_SERIAL_UFL.md](/connectors/plc-s7-ethernetip-hart-serial-ufl/) |
| **9. 4–20 mA Analog Loop & HART 7** | Current Loop $\rightarrow$ Remote I/O (`TCP :502`) | Channel `AI0..AI7` or HART Multidrop Poll | 16/24-bit ADC across $250\,\Omega$ shunt + Bell 202 FSK | **NAMUR NE 43:** `< 3.6 mA` (cut wire) or `> 21.0 mA` $\rightarrow$ `quality = 0` | Advantech `ADAM-6017` / HART Mux $\rightarrow$ `[[inputs.modbus]]` | [CONNECTOR_GUIDE_PLC_S7_ETHERNETIP_HART_SERIAL_UFL.md](/connectors/plc-s7-ethernetip-hart-serial-ufl/) |
| **10. RS-232 Serial & File Watch-Folder (`PI UFL`)** | Moxa NPort `TCP :4001` or `SMB/SFTP` Share | Regex Capture Group or CSV/XML Column Map | Event-Driven Print/Assay Stream + `SHA-256` File Seal | Balance Stability Flag (`S S` = `192` Good, `S D` = `64` Dynamic) | Serial Stream & Watchfolder Workers $\rightarrow$ `:8080/ingest` | [CONNECTOR_GUIDE_PLC_S7_ETHERNETIP_HART_SERIAL_UFL.md](/connectors/plc-s7-ethernetip-hart-serial-ufl/) |

---

## 4. Universal GxPHistorian Normalization Contract

Regardless of which physical cable or software protocol is used at the edge, **Pillar 1 (`edge-collector`)** normalizes every single measurement into an identical 6-field GxP telemetry tuple before writing it to the disk-backed Write-Ahead Log (`/var/lib/telegraf/buffer`) and **ClickHouse (`pi_historian.sensor_data`)**:

```json
{
  "tag_id": 101,
  "ts": 1792256400125,
  "val": 37.02,
  "str_val": "",
  "quality": 192,
  "status_code": 0
}
```

1. **`tag_id` (`UInt32`):** Foreign key mapped to the PostgreSQL `tags` catalog and ISA-95 `ltree` asset hierarchy (`BioCorp.Fremont.USP.Bioreactor_201`).
2. **`ts` (`DateTime64(3, 'UTC')`):** Exact source measurement timestamp in UTC milliseconds (preserving the PLC's `SourceTimestamp` or PAT analyzer's sample draw time).
3. **`val` (`Float64`):** IEEE-754 64-bit floating-point engineering value, compressed on disk with ClickHouse `Gorilla` + `ZSTD(1)`.
4. **`str_val` (`LowCardinality(String)`):** Optional string state for ISA-88 batch phases (`"FED_BATCH"`, `"ELUTION"`), lot numbers, or sample barcodes.
5. **`quality` (`UInt8`):** Mandatory OPC quality code (`192` = Good, `64` = Uncertain, `0` = Bad). Every analytical rollup, Event Frame summary, and Excel DataLink interpolation query strictly filters `WHERE quality >= 192`.
6. **`status_code` (`UInt32`):** Protocol-specific diagnostic sub-code (`0` = Normal, `1` = Hardware Fault, `3` = Manual Override / Out-of-Service, `4` = Active Process Alarm).

---

## 5. Deep-Dive Connector Guides in This Section

1. **[OPC UA (`:4840`) & Classic OPC DA (`COM/DCOM`) Connector Guide](/connectors/opc-ua-and-opc-da/)**
2. **[BACnet/IP (`UDP :47808`) & BACnet MS/TP (`RS-485`) Connector Guide](/connectors/bacnet-ip-and-mstp/)**
3. **[Modbus TCP (`:502`) & Modbus RTU (`RS-485`) Connector Guide](/connectors/modbus-tcp-and-rtu/)**
4. **[Siemens S7comm (`:102`), Allen-Bradley EtherNet/IP (`:44818`), 4–20 mA / HART, RS-232 Serial & File Watch-Folder (`PI UFL`) Connector Guide](/connectors/plc-s7-ethernetip-hart-serial-ufl/)**

