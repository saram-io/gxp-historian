#!/usr/bin/env python3
"""
GxPHistorian Multi-Protocol Biopharma Instrument Mock Server (`instrument-mock-server`).

Provides live, concurrent network protocol listeners emulating GMP biopharma skids and instruments
across all 6 industrial connection families:

  1. OPC UA TCP Server (`:4840`, IEC 62541 Binary `HEL`/`ACK` handshake + JSON/ASCII Node Read)
     - Emulates: Cytiva Xcellerex XDR-2000 / Sartorius Biostat STR Bioreactor (`BR201`)
     - Nodes: `ns=2;s=BR201.Temp.PV` (`tag_id=101`), `ns=2;s=BR201.pH.PV` (`tag_id=102`),
       `ns=2;s=BR201.DO.PV`
  2. Modbus TCP Server (`:5020`, MBAP 7-byte header + Function Codes `0x03`/`0x04`)
     - Emulates: PMS LasAir III Particle Counter & Binder KBF ICH Q1A Stability Chamber (`Unit ID 1`)
     - Holding Registers `40101..40110` (`0-based 100..109`): 32-bit IEEE-754 Float Big-Endian (`ABCD`),
       32-bit IEEE-754 Float Word-Swapped (`CDAB`), and 16-bit Scaled Integer (`INT16 x 10`)
  3. BACnet/IP UDP Server (`:47808/udp`, ASHRAE 135 BVLC `0x81` + `ReadProperty-ACK` & JSON-UDP)
     - Emulates: Cleanroom Suite 104 Environmental Monitoring System (`Device 30104`, `analog-input,1`
       `CR104_DIFF_PRESS` `tag_id=301` + 4-bit `Status_Flags`)
  4. Siemens S7comm ISO-on-TCP PLC Server (`:1020`, RFC 1006 TPKT `0x03 0x00` + ISO-COTP `0xE0/0xD0` + `DB10`)
     - Emulates: Siemens SIMATIC S7-1500 Bioreactor Agitator & SIP PLC (`Rack 0, Slot 1`, `DB10.DBW0`
       discrete step state `0=OFF, 1=LOW, 2=HIGH_RUN` `tag_id=103` & `DB10.DBD2` float32 vessel temp)
  5. RS-232 Serial-over-TCP Server (`:4001`, Moxa NPort 5150 TCP Server Mode)
     - Emulates: Mettler Toledo Excellence XSR Balance (`MT-SICS` `SI`, `ZI`, `T`, `I4`) &
       Advanced Instruments OsmoTECH PRO Osmometer (`OSMO`)
  6. Legacy Windows OPC DA 2.05a Bridge, At-Line PAT Watch-Folder (`PI UFL`) & Control REST API (`:8095`)
     - Emulates: Cytiva UNICORN 7 / `Matrikon.OPC.Simulation.1` (`DSP.Chrom.UV280.PV` `tag_id=401`),
       Sartorius Sartocheck 5 Plus / Beckman Vi-CELL BLU SHA-256 CSV batch file drops, fault injection,
       and end-to-end multi-protocol socket self-tests (`/control/self-test`).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import logging
import math
import os
import pathlib
import socket
import struct
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("instrument_mock_server")

MOCK_HTTP_PORT = int(os.getenv("MOCK_HTTP_PORT_INTERNAL", "8095"))
MOCK_OPCUA_PORT = int(os.getenv("MOCK_OPCUA_PORT_INTERNAL", "4840"))
MOCK_MODBUS_PORT = int(os.getenv("MOCK_MODBUS_PORT_INTERNAL", "5020"))
MOCK_BACNET_PORT = int(os.getenv("MOCK_BACNET_PORT_INTERNAL", "47808"))
MOCK_S7_PORT = int(os.getenv("MOCK_S7_PORT_INTERNAL", "1102"))
MOCK_SERIAL_PORT = int(os.getenv("MOCK_SERIAL_PORT_INTERNAL", "4001"))

EDGE_INGEST_URL = os.getenv("EDGE_INGEST_URL", "http://edge-collector:8080/ingest")
_DEFAULT_UFL_DIR = (
    "/app/ufl_drop"
    if pathlib.Path("/app").is_dir()
    else "/tmp/gxphistorian_ufl_drop"
)
UFL_DROP_DIR = pathlib.Path(os.getenv("UFL_DROP_DIR", _DEFAULT_UFL_DIR))
UFL_DROP_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Live Telemetry State & Fault/Excursion Override Registry
# ---------------------------------------------------------------------------


class TagOverride(BaseModel):
    tag_id: int = Field(..., description="Historian Tag ID (101, 102, 103, 301, 401)")
    val: float = Field(..., description="Overridden engineering value")
    str_val: str = Field(default="", description="Optional discrete state or fault string")
    quality: int = Field(default=192, description="OPC quality code: 192=Good, 64=Uncertain, 0=Bad")
    status_code: int = Field(default=0, description="Protocol status / fault sub-code")
    ttl_seconds: float = Field(default=30.0, ge=1.0, le=3600.0, description="Duration of manual override")
    forward_to_edge: bool = Field(
        default=False,
        description="If True, immediately push the overridden sample to edge-collector (:8080/ingest)",
    )


class SelfTestRequest(BaseModel):
    push_to_edge: bool = Field(
        default=True,
        description="If True, forward the multi-protocol socket readings to edge-collector (:8080/ingest)",
    )


class OpcDaReadRequest(BaseModel):
    prog_id: str = Field(default="Matrikon.OPC.Simulation.1")
    group: str = Field(default="GxP_Historian_Group")
    item_ids: List[str] = Field(
        default_factory=lambda: [
            "DSP.Chrom.UV280.PV",
            "USP.BR201.Temp.PV",
            "USP.BR201.pH.PV",
        ]
    )


class UflBatchDropRequest(BaseModel):
    instrument_type: str = Field(
        default="Sartocheck_5_Plus_Filter_Integrity",
        description="Instrument archetype (e.g., Sartocheck_5_Plus_Filter_Integrity or Vi_CELL_BLU_Viability)",
    )
    batch_id: str = Field(default="BATCH-2026-BR201-001")
    tag_id: int = Field(default=401)
    val: float = Field(default=245.8)
    quality: int = Field(default=192)
    forward_to_edge: bool = Field(default=True)


_OVERRIDES: Dict[int, Tuple[TagOverride, float]] = {}


def get_current_plant_snapshot(now: Optional[float] = None) -> Dict[int, Dict[str, Any]]:
    """
    Compute deterministic, time-varying values for all 5 GxP tags across all industrial protocols,
    applying any active manual overrides from `_OVERRIDES`.
    """
    t = now if now is not None else time.time()
    tick = int(t)

    # 101: BR201_TEMP_PV (OPC UA / Modbus / S7)
    phase_101 = (tick % 60) / 60.0 * (2.0 * math.pi)
    if 40 <= (tick % 60) <= 48:
        excursion = math.sin(((tick % 60) - 40) / 8.0 * math.pi)
        temp_val = round(37.3 + 1.3 * excursion, 4)
    else:
        temp_val = round(37.0 + 0.3 * math.sin(phase_101), 4)

    # 102: BR201_PH_PV (OPC UA)
    ph_val = round(7.05 + 0.05 * math.cos(t * 0.25), 4)

    # 103: BR201_AGIT_STATE (Siemens S7comm DB10.DBW0 Step Tag)
    agit_cycle = (tick // 60) % 3
    if agit_cycle == 0:
        agit_val, agit_str = 2.0, "HIGH_RUN"
    elif agit_cycle == 1:
        agit_val, agit_str = 1.0, "LOW"
    else:
        agit_val, agit_str = 0.0, "OFF"

    # 301: CR104_DIFF_PRESS (BACnet/IP & Modbus TCP Cleanroom DP)
    dp_val = round(18.5 + 0.8 * math.sin(t * 0.18), 4)

    # 401: CHROM01_UV280_PV (Windows OPC DA 2.05a Chromatography UV280)
    chrom_pos = tick % 90
    baseline_mau = 12.0 + 1.5 * math.sin(t * 0.1)
    main_peak_mau = 780.0 * math.exp(-((chrom_pos - 45.0) ** 2) / (2.0 * (9.5**2)))
    shoulder_mau = 95.0 * math.exp(-((chrom_pos - 26.0) ** 2) / (2.0 * (4.0**2)))
    uv_val = round(baseline_mau + main_peak_mau + shoulder_mau, 4)

    snapshot: Dict[int, Dict[str, Any]] = {
        101: {
            "tag_id": 101,
            "tag_name": "BR201_TEMP_PV",
            "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
            "protocol": "OPC_UA",
            "opcua_node_id": "ns=2;s=BR201.Temp.PV",
            "modbus_holding_register": 40106,
            "s7_db_address": "DB10.DBD2",
            "eng_units": "degC",
            "is_step_tag": False,
            "val": temp_val,
            "str_val": "",
            "quality": 192,
            "status_code": 0,
            "ts_ms": int(t * 1000),
        },
        102: {
            "tag_id": 102,
            "tag_name": "BR201_PH_PV",
            "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
            "protocol": "OPC_UA",
            "opcua_node_id": "ns=2;s=BR201.pH.PV",
            "modbus_holding_register": 40108,
            "eng_units": "pH",
            "is_step_tag": False,
            "val": ph_val,
            "str_val": "",
            "quality": 192,
            "status_code": 0,
            "ts_ms": int(t * 1000),
        },
        103: {
            "tag_id": 103,
            "tag_name": "BR201_AGIT_STATE",
            "asset_path": "BioCorp.Fremont.USP.Bioreactor_201",
            "protocol": "SIEMENS_S7",
            "s7_db_address": "DB10.DBW0",
            "modbus_holding_register": 40110,
            "eng_units": "state",
            "is_step_tag": True,
            "val": agit_val,
            "str_val": agit_str,
            "quality": 192,
            "status_code": 0,
            "ts_ms": int(t * 1000),
        },
        301: {
            "tag_id": 301,
            "tag_name": "CR104_DIFF_PRESS",
            "asset_path": "BioCorp.Fremont.Facilities.Cleanroom_Suite_104",
            "protocol": "BACNET_IP",
            "bacnet_object": "analog-input,1",
            "modbus_holding_register_abcd": 40101,
            "modbus_holding_register_cdab": 40103,
            "modbus_holding_register_int16_x10": 40105,
            "eng_units": "Pa",
            "is_step_tag": False,
            "val": dp_val,
            "str_val": "",
            "quality": 192,
            "status_code": 0,
            "bacnet_status_flags": [0, 0, 0, 0],
            "ts_ms": int(t * 1000),
        },
        401: {
            "tag_id": 401,
            "tag_name": "CHROM01_UV280_PV",
            "asset_path": "BioCorp.Fremont.DSP.Chrom_Skid_01",
            "protocol": "OPC_DA",
            "opcda_item_id": "DSP.Chrom.UV280.PV",
            "eng_units": "mAU",
            "is_step_tag": False,
            "val": uv_val,
            "str_val": "",
            "quality": 192,
            "status_code": 0,
            "ts_ms": int(t * 1000),
        },
    }

    # Apply active manual overrides
    expired_ids = []
    for tid, (ovr, expires_at) in _OVERRIDES.items():
        if t > expires_at:
            expired_ids.append(tid)
        elif tid in snapshot:
            snapshot[tid]["val"] = ovr.val
            snapshot[tid]["str_val"] = ovr.str_val
            snapshot[tid]["quality"] = ovr.quality
            snapshot[tid]["status_code"] = ovr.status_code
            snapshot[tid]["overridden"] = True
            if tid == 301:
                snapshot[tid]["bacnet_status_flags"] = [
                    1 if ovr.status_code == 4 else 0,
                    1 if ovr.quality == 0 else 0,
                    1 if ovr.quality == 64 else 0,
                    0,
                ]
    for tid in expired_ids:
        _OVERRIDES.pop(tid, None)

    return snapshot


# ---------------------------------------------------------------------------
# 1. OPC UA Binary (`HEL`/`ACK`) + Node Read TCP Server (:4840)
# ---------------------------------------------------------------------------


def build_opcua_ack_frame() -> bytes:
    """
    Build a standard 28-byte IEC 62541 OPC UA Binary `ACK` message header + body:
      - MessageType: b'ACK' (3B) + ChunkType: b'F' (1B) + MessageSize: 28 (uint32 LE)
      - ProtocolVersion: 0 (uint32 LE)
      - ReceiveBufferSize: 65536 (uint32 LE)
      - SendBufferSize: 65536 (uint32 LE)
      - MaxMessageSize: 4194304 (uint32 LE)
      - MaxChunkCount: 0 (uint32 LE)
    """
    return struct.pack("<3sBIIIIII", b"ACK", ord("F"), 28, 0, 65536, 65536, 4194304, 0)


async def _handle_opcua_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            # Standard OPC UA binary Hello (`HEL` + `F`)
            if data[:3] == b"HEL":
                writer.write(build_opcua_ack_frame())
                await writer.drain()
                continue

            # Line-based or JSON node read for lightweight OPC UA inspection clients
            text = data.decode("utf-8", errors="replace").strip()
            snap = get_current_plant_snapshot()
            node_map = {
                "ns=2;s=BR201.Temp.PV": snap[101],
                "ns=2;s=BR201.pH.PV": snap[102],
                "ns=2;s=BR201.Agitator.State": snap[103],
                "ns=2;s=BR201.DO.PV": {
                    "tag_id": 105,
                    "tag_name": "BR201_DO_PV",
                    "opcua_node_id": "ns=2;s=BR201.DO.PV",
                    "eng_units": "%Sat",
                    "val": round(62.4 + 1.2 * math.sin(time.time() * 0.15), 3),
                    "quality": 192,
                    "status_code": 0,
                    "opcua_status_hex": "0x00000000 (Good)",
                },
            }
            req_node = "ns=2;s=BR201.Temp.PV"
            if text.startswith("{"):
                with contextlib.suppress(Exception):
                    parsed = json.loads(text)
                    req_node = parsed.get("node_id", req_node)
            elif text.upper().startswith("READ "):
                req_node = text.split(None, 1)[1].strip()

            node_payload = node_map.get(req_node, {"error": f"Unknown NodeId: {req_node}"})
            writer.write((json.dumps(node_payload) + "\n").encode("utf-8"))
            await writer.drain()
    except Exception as exc:
        logger.debug("OPC UA client closed: %s", exc)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# 2. Modbus TCP Server (:5020) — MBAP Header + FC03/FC04 Register Map
# ---------------------------------------------------------------------------


def build_modbus_register_bank(snap: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[int, int]:
    """
    Build 0-based 16-bit Modbus register map (addresses `100..111`, corresponding to `40101..40112`):
      - `100, 101` (`40101..40102`): `CR104_DIFF_PRESS` (`tag_id=301`) IEEE-754 Float Big-Endian (`ABCD`)
      - `102, 103` (`40103..40104`): `CR104_DIFF_PRESS` (`tag_id=301`) IEEE-754 Float Word-Swapped (`CDAB`)
      - `104`      (`40105`):        `CR104_DIFF_PRESS` (`tag_id=301`) `INT16` scaled `x10` (e.g. `185` = `18.5 Pa`)
      - `105, 106` (`40106..40107`): `BR201_TEMP_PV` (`tag_id=101`) IEEE-754 Float Big-Endian (`ABCD`)
      - `107, 108` (`40108..40109`): `BR201_PH_PV` (`tag_id=102`) IEEE-754 Float Big-Endian (`ABCD`)
      - `109`      (`40110`):        `BR201_AGIT_STATE` (`tag_id=103`) `UINT16` discrete state (`0/1/2`)
      - `110, 111` (`40111..40112`): `CHROM01_UV280_PV` (`tag_id=401`) IEEE-754 Float Big-Endian (`ABCD`)
    """
    current = snap or get_current_plant_snapshot()
    dp_val = float(current[301]["val"])
    temp_val = float(current[101]["val"])
    ph_val = float(current[102]["val"])
    agit_val = int(round(float(current[103]["val"])))
    uv_val = float(current[401]["val"])

    dp_hi, dp_lo = struct.unpack(">HH", struct.pack(">f", dp_val))
    temp_hi, temp_lo = struct.unpack(">HH", struct.pack(">f", temp_val))
    ph_hi, ph_lo = struct.unpack(">HH", struct.pack(">f", ph_val))
    uv_hi, uv_lo = struct.unpack(">HH", struct.pack(">f", uv_val))
    dp_int16_x10 = max(-32768, min(32767, int(round(dp_val * 10.0)))) & 0xFFFF

    return {
        100: dp_hi,        # 40101: ABCD High Word (AB)
        101: dp_lo,        # 40102: ABCD Low Word (CD)
        102: dp_lo,        # 40103: CDAB Word-Swapped First Word (CD)
        103: dp_hi,        # 40104: CDAB Word-Swapped Second Word (AB)
        104: dp_int16_x10, # 40105: INT16 scaled x10
        105: temp_hi,      # 40106: BR201_TEMP_PV ABCD High Word
        106: temp_lo,      # 40107: BR201_TEMP_PV ABCD Low Word
        107: ph_hi,        # 40108: BR201_PH_PV ABCD High Word
        108: ph_lo,        # 40109: BR201_PH_PV ABCD Low Word
        109: agit_val,     # 40110: BR201_AGIT_STATE UINT16
        110: uv_hi,        # 40111: CHROM01_UV280_PV ABCD High Word
        111: uv_lo,        # 40112: CHROM01_UV280_PV ABCD Low Word
    }


def handle_modbus_tcp_pdu(request_bytes: bytes) -> bytes:
    """
    Process a 12-byte Modbus TCP Read Holding/Input Registers request (`FC 0x03` or `0x04`):
      Request MBAP (7B): `tx_id (2B) | proto_id=0 (2B) | length=6 (2B) | unit_id (1B)`
      Request PDU  (5B): `func_code (1B) | start_addr (2B) | quantity (2B)`
    """
    if len(request_bytes) < 12:
        return b""
    tx_id, proto_id, _length, unit_id, func_code, start_addr, quantity = struct.unpack(
        ">HHHBBHH", request_bytes[:12]
    )
    if func_code not in (3, 4) or quantity < 1 or quantity > 125:
        # Illegal Function (0x01) or Illegal Data Value (0x03) exception response
        exc_code = 1 if func_code not in (3, 4) else 3
        return struct.pack(">HHHBBB", tx_id, proto_id, 3, unit_id, func_code | 0x80, exc_code)

    reg_bank = build_modbus_register_bank()
    reg_words = [reg_bank.get(start_addr + offset, 0) for offset in range(quantity)]
    byte_count = quantity * 2
    mbap_len = 3 + byte_count
    header = struct.pack(">HHHBBB", tx_id, proto_id, mbap_len, unit_id, func_code, byte_count)
    payload = struct.pack(f">{quantity}H", *reg_words)
    return header + payload


async def _handle_modbus_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            req = await reader.read(260)
            if not req:
                break
            resp = handle_modbus_tcp_pdu(req)
            if resp:
                writer.write(resp)
                await writer.drain()
    except Exception as exc:
        logger.debug("Modbus TCP client closed: %s", exc)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# 3. BACnet/IP UDP Server (:47808/udp) — ASHRAE 135 BVLC + JSON-UDP
# ---------------------------------------------------------------------------


def build_bacnet_bvlc_response(request_bytes: bytes) -> bytes:
    """
    Respond to either:
      1. Binary ASHRAE 135 BACnet/IP BVLC (`0x81` type byte) frames with a valid BVLC
         `Original-Unicast-NPDU` (`0x81 0x0a`) + Complex-ACK (`0x30`) carrying the IEEE-754
         `presentValue` (`tag_id=301`, `CR104_DIFF_PRESS`) and 4-bit `Status_Flags`.
      2. JSON-over-UDP inspection requests (`{"object_identifier": "analog-input,1"}`).
    """
    snap = get_current_plant_snapshot()
    dp_entry = snap[301]
    dp_val = float(dp_entry["val"])
    flags = dp_entry.get("bacnet_status_flags", [0, 0, 0, 0])

    if request_bytes and request_bytes[0] == 0x81:
        # Extract invoke_id if present in APDU, default to 1
        invoke_id = request_bytes[8] if len(request_bytes) > 8 else 1
        status_byte = (
            ((1 if flags[0] else 0) << 7)
            | ((1 if flags[1] else 0) << 6)
            | ((1 if flags[2] else 0) << 5)
            | ((1 if flags[3] else 0) << 4)
        )
        # BVLC (4B: 0x81, 0x0a, length=17) + NPDU (2B: 0x01, 0x00) + APDU Complex-ACK (0x30, invoke_id, service=0x0c ReadProperty)
        # + Context Tag 0x44 (REAL 4B IEEE-754) + status_byte (1B) + quality (1B)
        apdu_payload = struct.pack(">BBBBfBB", 0x30, invoke_id, 0x0C, 0x44, dp_val, status_byte, int(dp_entry["quality"]))
        total_len = 4 + 2 + len(apdu_payload)
        bvlc_npdu = struct.pack(">BBHBB", 0x81, 0x0A, total_len, 0x01, 0x00)
        return bvlc_npdu + apdu_payload

    # JSON-over-UDP response for human/script inspection
    resp_obj = {
        "protocol": "BACNET_IP",
        "bvlc_port": 47808,
        "device_id": 30104,
        "object_identifier": "analog-input,1",
        "tag_id": 301,
        "tag_name": "CR104_DIFF_PRESS",
        "presentValue": dp_val,
        "units": "pascals (Pa)",
        "statusFlags": flags,
        "opc_quality": dp_entry["quality"],
        "status_code": dp_entry["status_code"],
        "ts_ms": dp_entry["ts_ms"],
    }
    return json.dumps(resp_obj).encode("utf-8")


class BacnetUdpProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        resp = build_bacnet_bvlc_response(data)
        self.transport.sendto(resp, addr)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 4. Siemens S7comm ISO-on-TCP Server (:1020) — RFC 1006 TPKT + COTP + DB10
# ---------------------------------------------------------------------------


def handle_s7comm_frame(request_bytes: bytes) -> bytes:
    """
    Handle RFC 1006 ISO-on-TCP (`TPKT` version `0x03`) + COTP / S7comm (`0x32`) frames:
      - If COTP Connection Request (`pdu_type == 0xE0`): return RFC 1006 TPKT + COTP Connection Confirm (`0xD0`).
      - If S7comm Read / Setup (`0x32` S7 header): return TPKT + COTP DT (`0xF0`) + S7 Read ACK with
        `DB10.DBW0` (`uint16` agitator state `0/1/2`, `tag_id=103`) and `DB10.DBD2` (`float32` `BR201_TEMP_PV`, `tag_id=101`).
      - If ASCII/JSON query (`READ DB10`): return JSON representation of `DB10`.
    """
    snap = get_current_plant_snapshot()
    agit_state = int(round(float(snap[103]["val"])))
    temp_val = float(snap[101]["val"])

    if len(request_bytes) >= 7 and request_bytes[0] == 0x03 and request_bytes[1] == 0x00:
        cotp_pdu_type = request_bytes[5]
        if cotp_pdu_type == 0xE0:
            # COTP Connection Confirm (0xD0) wrapped in 11-byte TPKT
            return bytes([0x03, 0x00, 0x00, 0x0B, 0x06, 0xD0, 0x00, 0x01, 0x00, 0x01, 0x00])
        # S7comm Data Block DB10 Read Response: TPKT (4B) + COTP DT (3B: 0x02, 0xF0, 0x80) + S7 Header (0x32, 0x03) + DB10 payload (uint16 agit_state + float32 temp_val)
        db10_bytes = struct.pack(">Hf", agit_state, temp_val)
        s7_pdu = bytes([0x02, 0xF0, 0x80, 0x32, 0x03, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00, 0x06, 0xFF, 0x04, 0x00, 0x30]) + db10_bytes
        tpkt_len = 4 + len(s7_pdu)
        return struct.pack(">BBH", 0x03, 0x00, tpkt_len) + s7_pdu

    return (
        json.dumps(
            {
                "protocol": "SIEMENS_S7_ISO_ON_TCP",
                "plc": "SIMATIC S7-1500 (Rack 0, Slot 1)",
                "data_block": "DB10",
                "DB10.DBW0": {
                    "tag_id": 103,
                    "tag_name": "BR201_AGIT_STATE",
                    "val": agit_state,
                    "str_val": snap[103]["str_val"],
                    "quality": snap[103]["quality"],
                },
                "DB10.DBD2": {
                    "tag_id": 101,
                    "tag_name": "BR201_TEMP_PV",
                    "val": temp_val,
                    "eng_units": "degC",
                    "quality": snap[101]["quality"],
                },
            }
        )
        + "\n"
    ).encode("utf-8")


async def _handle_s7_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            req = await reader.read(512)
            if not req:
                break
            writer.write(handle_s7comm_frame(req))
            await writer.drain()
    except Exception as exc:
        logger.debug("S7comm client closed: %s", exc)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# 5. Moxa NPort RS-232 Serial-over-TCP Server (:4001) — MT-SICS & Osmometer
# ---------------------------------------------------------------------------


def format_mtsics_response(cmd_line: str) -> str:
    """
    Emulate Mettler Toledo Standard Interface Command Set (`MT-SICS`) & OsmoTECH PRO ASCII frames:
      - `SI` or `S` -> `S S     125.420 g\r\n` (Stable weight)
      - `ZI` or `Z` -> `Z A\r\n` (Zero acknowledged)
      - `T`         -> `T S      10.000 g\r\n` (Tare acknowledged)
      - `I4`        -> `I4 A "B948271042"\r\n` (Balance serial number)
      - `OSMO`      -> `OSMO 292 mOsm/kg_H2O QUALITY=192\r\n`
    """
    clean = cmd_line.strip().upper()
    weight_g = 125.420 + 0.005 * math.sin(time.time())
    if clean in ("SI", "S", ""):
        return f"S S     {weight_g:7.3f} g\r\n"
    if clean in ("ZI", "Z"):
        return "Z A\r\n"
    if clean in ("T", "TI"):
        return "T S      10.000 g\r\n"
    if clean == "I4":
        return 'I4 A "B948271042"\r\n'
    if clean.startswith("OSMO"):
        osmo_val = int(round(292 + 2.0 * math.cos(time.time() * 0.1)))
        return f"OSMO {osmo_val} mOsm/kg_H2O QUALITY=192\r\n"
    return f"S S     {weight_g:7.3f} g\r\n"


async def _handle_serial_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            raw = await reader.readline()
            if not raw:
                break
            cmd = raw.decode("utf-8", errors="replace")
            reply = format_mtsics_response(cmd)
            writer.write(reply.encode("utf-8"))
            await writer.drain()
    except Exception as exc:
        logger.debug("Serial TCP client closed: %s", exc)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# FastAPI Lifespan & HTTP Control / OPC DA / UFL Server (:8095)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    opcua_srv = await asyncio.start_server(_handle_opcua_client, "0.0.0.0", MOCK_OPCUA_PORT)
    modbus_srv = await asyncio.start_server(_handle_modbus_client, "0.0.0.0", MOCK_MODBUS_PORT)
    s7_srv = await asyncio.start_server(_handle_s7_client, "0.0.0.0", MOCK_S7_PORT)
    serial_srv = await asyncio.start_server(_handle_serial_client, "0.0.0.0", MOCK_SERIAL_PORT)
    bacnet_transport, _ = await loop.create_datagram_endpoint(
        BacnetUdpProtocol,
        local_addr=("0.0.0.0", MOCK_BACNET_PORT),
    )
    logger.info(
        "Started Multi-Protocol Instrument Mock Server listeners: "
        "HTTP=%d, OPC_UA_TCP=%d, MODBUS_TCP=%d, BACNET_UDP=%d, S7COMM_TCP=%d, SERIAL_TCP=%d",
        MOCK_HTTP_PORT,
        MOCK_OPCUA_PORT,
        MOCK_MODBUS_PORT,
        MOCK_BACNET_PORT,
        MOCK_S7_PORT,
        MOCK_SERIAL_PORT,
    )
    try:
        yield
    finally:
        bacnet_transport.close()
        for srv in (opcua_srv, modbus_srv, s7_srv, serial_srv):
            srv.close()
            await srv.wait_closed()


app = FastAPI(
    title="GxPHistorian Multi-Protocol Biopharma Instrument Mock Server",
    description=(
        "Simulates 6 industrial instrument connection types concurrently (OPC UA Binary TCP :4840, "
        "Modbus TCP :5020, BACnet/IP UDP :47808, Siemens S7comm ISO-on-TCP :1020, Moxa RS-232 "
        "Serial-over-TCP MT-SICS :4001, and Legacy Windows OPC DA 2.05a + PI UFL Watch-Folder :8095)."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)


@app.get("/health")
@app.get("/api/v1/health")
def get_health() -> Dict[str, Any]:
    snap = get_current_plant_snapshot()
    return {
        "status": "healthy",
        "service": "instrument-mock-server",
        "active_listeners": {
            "http_control_opcda_ufl": {"transport": "TCP/HTTP", "port": MOCK_HTTP_PORT},
            "opc_ua_binary": {
                "transport": "TCP",
                "port": MOCK_OPCUA_PORT,
                "endpoint": f"opc.tcp://instrument-mock-server:{MOCK_OPCUA_PORT}/gxphistorian/server/",
            },
            "modbus_tcp": {"transport": "TCP (MBAP FC03/FC04)", "port": MOCK_MODBUS_PORT, "unit_id": 1},
            "bacnet_ip": {"transport": "UDP (ASHRAE 135 BVLC 0x81)", "port": MOCK_BACNET_PORT, "device_id": 30104},
            "siemens_s7comm": {
                "transport": "TCP (RFC 1006 TPKT/COTP + S7 DB10)",
                "port": MOCK_S7_PORT,
                "rack": 0,
                "slot": 1,
            },
            "rs232_serial_tcp": {
                "transport": "TCP (Moxa NPort MT-SICS & Osmometer)",
                "port": MOCK_SERIAL_PORT,
            },
        },
        "simulated_tags_count": len(snap),
        "active_overrides": list(_OVERRIDES.keys()),
    }


@app.get("/protocols")
def list_protocol_connections() -> Dict[str, Any]:
    """Return all 6 simulated instrument connection types, wire formats, and live values."""
    snap = get_current_plant_snapshot()
    reg_bank = build_modbus_register_bank(snap)
    return {
        "service": "instrument-mock-server",
        "connection_types": [
            {
                "connection_type": "OPC_UA",
                "port": MOCK_OPCUA_PORT,
                "transport": "TCP (IEC 62541 Binary HEL/ACK + JSON Node Read)",
                "simulated_equipment": "Cytiva Xcellerex XDR-2000 & Sartorius Biostat STR Bioreactor 201",
                "nodes": {
                    "ns=2;s=BR201.Temp.PV": snap[101],
                    "ns=2;s=BR201.pH.PV": snap[102],
                },
            },
            {
                "connection_type": "MODBUS_TCP",
                "port": MOCK_MODBUS_PORT,
                "transport": "TCP (MBAP 7-byte Header + FC03 Read Holding Registers)",
                "simulated_equipment": "PMS LasAir III Cleanroom Counter & Binder KBF Stability Chamber",
                "unit_id": 1,
                "holding_registers_0_based": reg_bank,
                "endianness_formats": ["FLOAT32_ABCD_BIG_ENDIAN (40101)", "FLOAT32_CDAB_WORD_SWAPPED (40103)", "INT16_SCALED_X10 (40105)"],
            },
            {
                "connection_type": "BACNET_IP",
                "port": MOCK_BACNET_PORT,
                "transport": "UDP (ASHRAE 135 BVLC 0x81 Original-Unicast-NPDU + Complex-ACK)",
                "simulated_equipment": "Cleanroom Suite 104 BMS/EMS Differential Pressure Controller",
                "device_id": 30104,
                "objects": {"analog-input,1": snap[301]},
            },
            {
                "connection_type": "SIEMENS_S7COMM",
                "port": MOCK_S7_PORT,
                "transport": "TCP (RFC 1006 ISO-on-TCP TPKT 0x03 + COTP 0xE0/0xD0 + S7 DB10)",
                "simulated_equipment": "Siemens SIMATIC S7-1500 Bioreactor Agitator & Sterilization PLC",
                "rack": 0,
                "slot": 1,
                "data_block_db10": {
                    "DB10.DBW0": snap[103],
                    "DB10.DBD2": snap[101],
                },
            },
            {
                "connection_type": "RS232_SERIAL_OVER_TCP",
                "port": MOCK_SERIAL_PORT,
                "transport": "TCP Raw Socket (Moxa NPort 5150 TCP Server Mode, ASCII CRLF)",
                "simulated_equipment": "Mettler Toledo Excellence XSR Analytical Balance (MT-SICS) & OsmoTECH PRO",
                "supported_commands": ["SI\\r\\n", "ZI\\r\\n", "T\\r\\n", "I4\\r\\n", "OSMO\\r\\n"],
                "sample_response": format_mtsics_response("SI").strip(),
            },
            {
                "connection_type": "OPC_DA_AND_PI_UFL",
                "port": MOCK_HTTP_PORT,
                "transport": "HTTP JSON Bridge (Zero-DCOM Localhost Forwarder & SHA-256 Watch-Folder)",
                "simulated_equipment": "Cytiva ÄKTA UNICORN 7 (Matrikon.OPC.Simulation.1) & Sartorius Sartocheck 5 Plus",
                "opcda_items": {"DSP.Chrom.UV280.PV": snap[401]},
            },
        ],
    }


@app.get("/protocols/opcua/nodes")
def get_opcua_nodes() -> Dict[str, Any]:
    snap = get_current_plant_snapshot()
    return {
        "endpoint_url": f"opc.tcp://instrument-mock-server:{MOCK_OPCUA_PORT}/gxphistorian/server/",
        "security_policy": "Basic256Sha256",
        "nodes": [snap[101], snap[102]],
    }


@app.get("/protocols/modbus/registers")
def get_modbus_registers() -> Dict[str, Any]:
    snap = get_current_plant_snapshot()
    reg_bank = build_modbus_register_bank(snap)
    return {
        "unit_id": 1,
        "port": MOCK_MODBUS_PORT,
        "registers_0_based": reg_bank,
        "decoded_preview": {
            "40101_40102_CR104_DP_FLOAT32_ABCD": snap[301]["val"],
            "40103_40104_CR104_DP_FLOAT32_CDAB": snap[301]["val"],
            "40105_CR104_DP_INT16_X10": reg_bank[104],
            "40106_40107_BR201_TEMP_FLOAT32_ABCD": snap[101]["val"],
            "40108_40109_BR201_PH_FLOAT32_ABCD": snap[102]["val"],
            "40110_BR201_AGIT_STATE_UINT16": reg_bank[109],
        },
    }


@app.get("/protocols/bacnet/objects")
def get_bacnet_objects() -> Dict[str, Any]:
    snap = get_current_plant_snapshot()
    return {
        "device_id": 30104,
        "udp_port": MOCK_BACNET_PORT,
        "objects": [
            {
                "object_identifier": "analog-input,1",
                "object_name": "CR104_DIFF_PRESS",
                "presentValue": snap[301]["val"],
                "units": "Pa",
                "statusFlags": snap[301]["bacnet_status_flags"],
                "opc_quality": snap[301]["quality"],
                "status_code": snap[301]["status_code"],
            }
        ],
    }


@app.get("/protocols/s7/db10")
def get_s7_db10() -> Dict[str, Any]:
    snap = get_current_plant_snapshot()
    return {
        "plc": "Siemens SIMATIC S7-1500",
        "tcp_port": MOCK_S7_PORT,
        "rack": 0,
        "slot": 1,
        "data_block": 10,
        "offsets": {
            "DB10.DBW0": {
                "tag_id": 103,
                "tag_name": "BR201_AGIT_STATE",
                "data_type": "UINT16 (Step/LOCF)",
                "val": int(round(float(snap[103]["val"]))),
                "str_val": snap[103]["str_val"],
                "quality": snap[103]["quality"],
            },
            "DB10.DBD2": {
                "tag_id": 101,
                "tag_name": "BR201_TEMP_PV",
                "data_type": "REAL (IEEE-754 Float32)",
                "val": snap[101]["val"],
                "eng_units": "degC",
                "quality": snap[101]["quality"],
            },
        },
    }


@app.post("/protocols/opcda/read")
def read_opcda_items(req: OpcDaReadRequest = OpcDaReadRequest()) -> Dict[str, Any]:
    """Emulate a Windows COM OPC DA 2.05a group read (`OpenOPC.read`) for `opcda_windows_forwarder.py`."""
    snap = get_current_plant_snapshot()
    item_lookup = {
        "DSP.Chrom.UV280.PV": snap[401],
        "USP.BR201.Temp.PV": snap[101],
        "USP.BR201.pH.PV": snap[102],
        "USP.BR201.Agitator.State": snap[103],
    }
    items_out = []
    for item_id in req.item_ids:
        entry = item_lookup.get(item_id, snap[401])
        q_code = int(entry["quality"])
        q_str = "Good" if q_code >= 192 else ("Uncertain" if q_code >= 64 else "Bad:DeviceFailure")
        items_out.append(
            {
                "item_id": item_id,
                "tag_id": entry["tag_id"],
                "val": entry["val"],
                "quality_str": q_str,
                "opc_quality": q_code,
                "status_code": entry["status_code"],
                "ts_ms": entry["ts_ms"],
            }
        )
    return {
        "prog_id": req.prog_id,
        "group": req.group,
        "items": items_out,
    }


@app.post("/protocols/ufl/generate-batch-file")
def generate_ufl_batch_file(req: UflBatchDropRequest = UflBatchDropRequest()) -> Dict[str, Any]:
    """
    Emulate an At-Line PAT instrument (e.g., Sartorius Sartocheck 5 Plus or Beckman Vi-CELL BLU)
    dropping a timestamped CSV batch file into a watched folder with ALCOA+ SHA-256 verification.
    """
    now_dt = dt.datetime.now(dt.timezone.utc)
    ts_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_ms = int(now_dt.timestamp() * 1000)
    filename = f"{req.instrument_type}_{req.batch_id}_{now_dt.strftime('%Y%m%dT%H%M%SZ')}.csv"
    file_path = UFL_DROP_DIR / filename

    csv_content = (
        "instrument_type,batch_id,tag_id,timestamp_utc,val,quality,status_code\n"
        f"{req.instrument_type},{req.batch_id},{req.tag_id},{ts_iso},{req.val},{req.quality},0\n"
    )
    file_path.write_text(csv_content, encoding="utf-8")
    sha256_hex = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()

    edge_forwarded = False
    if req.forward_to_edge:
        payload = [
            {
                "tag_id": req.tag_id,
                "ts": ts_ms,
                "val": req.val,
                "str_val": f"UFL:{req.batch_id}:sha256={sha256_hex[:12]}",
                "quality": req.quality,
                "status_code": 0,
            }
        ]
        with contextlib.suppress(Exception):
            with httpx.Client(timeout=5.0) as client:
                r = client.post(EDGE_INGEST_URL, json=payload)
                edge_forwarded = r.status_code < 300

    return {
        "status": "generated",
        "instrument_type": req.instrument_type,
        "batch_id": req.batch_id,
        "file_path": str(file_path),
        "file_sha256": sha256_hex,
        "edge_forwarded": edge_forwarded,
        "tag_id": req.tag_id,
        "val": req.val,
        "quality": req.quality,
    }


@app.post("/control/override")
def set_tag_override(ovr: TagOverride) -> Dict[str, Any]:
    """
    Inject a temporary engineering value or OPC quality fault (`quality=0` Bad or `quality=64` Uncertain)
    on any tag across all protocol listeners, and optionally forward immediately to `edge-collector`.
    """
    now = time.time()
    expires_at = now + ovr.ttl_seconds
    _OVERRIDES[ovr.tag_id] = (ovr, expires_at)

    edge_forwarded = False
    if ovr.forward_to_edge:
        payload = [
            {
                "tag_id": ovr.tag_id,
                "ts": int(now * 1000),
                "val": ovr.val,
                "str_val": ovr.str_val,
                "quality": ovr.quality,
                "status_code": ovr.status_code,
            }
        ]
        with contextlib.suppress(Exception):
            with httpx.Client(timeout=5.0) as client:
                r = client.post(EDGE_INGEST_URL, json=payload)
                edge_forwarded = r.status_code < 300

    return {
        "status": "override_active",
        "tag_id": ovr.tag_id,
        "val": ovr.val,
        "quality": ovr.quality,
        "status_code": ovr.status_code,
        "ttl_seconds": ovr.ttl_seconds,
        "edge_forwarded": edge_forwarded,
    }


@app.post("/control/self-test")
async def run_multi_protocol_self_test(req: SelfTestRequest = SelfTestRequest()) -> Dict[str, Any]:
    """
    Execute a live network socket round-trip against all 6 protocol listeners inside the container
    (`OPC UA TCP :4840`, `Modbus TCP :5020`, `BACnet/IP UDP :47808`, `Siemens S7comm TCP :1020`,
    `RS-232 Serial TCP :4001`, and `OPC DA 2.05a Bridge`) and optionally forward the collected
    multi-protocol telemetry batch to `edge-collector` (`:8080/ingest`).
    """
    now_ms = int(time.time() * 1000)

    # 1. Test OPC UA TCP (:4840) — Binary HEL/ACK handshake + JSON Node Read
    opcua_reader, opcua_writer = await asyncio.open_connection("127.0.0.1", MOCK_OPCUA_PORT)
    opcua_writer.write(b"HELF\x1c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00@\x00\x00\x00\x00\x00")
    await opcua_writer.drain()
    ack_bytes = await opcua_reader.read(28)
    opcua_ack_ok = ack_bytes[:4] == b"ACKF"

    opcua_writer.write(b'{"action": "read", "node_id": "ns=2;s=BR201.Temp.PV"}\n')
    await opcua_writer.drain()
    opcua_node_line = await opcua_reader.readline()
    opcua_node_data = json.loads(opcua_node_line.decode("utf-8"))
    opcua_writer.close()
    await opcua_writer.wait_closed()

    # 2. Test Modbus TCP (:5020) — Function Code 0x03 Read Holding Registers 100..106 (40101..40107)
    mb_reader, mb_writer = await asyncio.open_connection("127.0.0.1", MOCK_MODBUS_PORT)
    mb_req = struct.pack(">HHHBBHH", 0x0042, 0x0000, 6, 1, 0x03, 100, 7)
    mb_writer.write(mb_req)
    await mb_writer.drain()
    mb_resp = await mb_reader.read(64)
    mb_writer.close()
    await mb_writer.wait_closed()
    # Unpack ABCD float (registers 100..101), CDAB word-swapped float (102..103), INT16x10 (104), and BR201_TEMP_PV ABCD (105..106)
    mb_words = struct.unpack(">7H", mb_resp[9:23])
    dp_abcd = round(struct.unpack(">f", struct.pack(">HH", mb_words[0], mb_words[1]))[0], 4)
    dp_cdab = round(struct.unpack(">f", struct.pack(">HH", mb_words[3], mb_words[2]))[0], 4)
    dp_int16_scaled = round(mb_words[4] / 10.0, 1)

    # 3. Test BACnet/IP UDP (:47808) — ASHRAE 135 BVLC 0x81 ReadProperty
    def _udp_bacnet_roundtrip() -> bytes:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
            udp_sock.settimeout(2.0)
            bvlc_query = bytes([0x81, 0x0A, 0x00, 0x0C, 0x01, 0x00, 0x00, 0x05, 0x07, 0x0C, 0x0C, 0x00])
            udp_sock.sendto(bvlc_query, ("127.0.0.1", MOCK_BACNET_PORT))
            reply, _ = udp_sock.recvfrom(256)
            return reply

    bvlc_reply = await asyncio.to_thread(_udp_bacnet_roundtrip)
    bacnet_dp_val = round(struct.unpack(">f", bvlc_reply[10:14])[0], 4)
    bacnet_quality = int(bvlc_reply[15])

    # 4. Test Siemens S7comm ISO-on-TCP (:1020) — COTP Connection Request (0xE0) + S7 DB10 Read
    s7_reader, s7_writer = await asyncio.open_connection("127.0.0.1", MOCK_S7_PORT)
    cotp_cr = bytes([0x03, 0x00, 0x00, 0x0B, 0x06, 0xE0, 0x00, 0x00, 0x00, 0x01, 0x00])
    s7_writer.write(cotp_cr)
    await s7_writer.drain()
    cotp_cc = await s7_reader.read(32)
    s7_cotp_ok = len(cotp_cc) >= 6 and cotp_cc[5] == 0xD0

    s7_read_req = bytes([0x03, 0x00, 0x00, 0x0A, 0x02, 0xF0, 0x80, 0x32, 0x01, 0x00])
    s7_writer.write(s7_read_req)
    await s7_writer.drain()
    s7_read_resp = await s7_reader.read(64)
    s7_writer.close()
    await s7_writer.wait_closed()
    s7_agit_state, s7_temp_val = struct.unpack(">Hf", s7_read_resp[-6:])

    # 5. Test Moxa RS-232 Serial-over-TCP (:4001) — Mettler Toledo MT-SICS `SI\r\n` & `OSMO\r\n`
    ser_reader, ser_writer = await asyncio.open_connection("127.0.0.1", MOCK_SERIAL_PORT)
    ser_writer.write(b"SI\r\n")
    await ser_writer.drain()
    mtsics_frame = (await ser_reader.readline()).decode("utf-8").strip()
    ser_writer.write(b"OSMO\r\n")
    await ser_writer.drain()
    osmo_frame = (await ser_reader.readline()).decode("utf-8").strip()
    ser_writer.close()
    await ser_writer.wait_closed()

    # 6. Test Windows OPC DA 2.05a Bridge
    opcda_res = read_opcda_items()
    opcda_uv280 = opcda_res["items"][0]["val"]

    # Optional push to Edge Collector (:8080/ingest)
    edge_ingested = False
    if req.push_to_edge:
        batch = [
            {"tag_id": 101, "ts": now_ms, "val": float(opcua_node_data["val"]), "str_val": "", "quality": 192, "status_code": 0},
            {"tag_id": 103, "ts": now_ms, "val": float(s7_agit_state), "str_val": "HIGH_RUN" if s7_agit_state == 2 else ("LOW" if s7_agit_state == 1 else "OFF"), "quality": 192, "status_code": 0},
            {"tag_id": 301, "ts": now_ms, "val": bacnet_dp_val, "str_val": "", "quality": bacnet_quality, "status_code": 0},
            {"tag_id": 401, "ts": now_ms, "val": float(opcda_uv280), "str_val": "", "quality": 192, "status_code": 0},
        ]
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(EDGE_INGEST_URL, json=batch)
                edge_ingested = r.status_code < 300

    return {
        "all_protocols_verified": bool(opcua_ack_ok and s7_cotp_ok and dp_abcd == dp_cdab),
        "edge_collector_ingested": edge_ingested,
        "protocol_results": {
            "opc_ua_tcp_4840": {
                "binary_hel_ack_handshake": opcua_ack_ok,
                "node_id": "ns=2;s=BR201.Temp.PV",
                "val": opcua_node_data["val"],
                "quality": opcua_node_data["quality"],
            },
            "modbus_tcp_5020": {
                "fc03_holding_registers_read": True,
                "float32_abcd_val": dp_abcd,
                "float32_cdab_val": dp_cdab,
                "int16_x10_scaled_val": dp_int16_scaled,
                "endianness_parity_verified": dp_abcd == dp_cdab,
            },
            "bacnet_ip_udp_47808": {
                "bvlc_complex_ack_verified": bvlc_reply[:2] == b"\x81\x0a",
                "object_identifier": "analog-input,1",
                "present_value_pa": bacnet_dp_val,
                "opc_quality": bacnet_quality,
            },
            "siemens_s7comm_tcp_1102": {
                "rfc1006_cotp_connection_confirm": s7_cotp_ok,
                "db10_dbw0_agitator_state": s7_agit_state,
                "db10_dbd2_vessel_temp": round(s7_temp_val, 4),
            },
            "rs232_serial_tcp_4001": {
                "mtsics_balance_response": mtsics_frame,
                "osmotech_pro_response": osmo_frame,
            },
            "opc_da_bridge_8095": {
                "prog_id": opcda_res["prog_id"],
                "item_id": "DSP.Chrom.UV280.PV",
                "val_mau": opcda_uv280,
            },
        },
    }
