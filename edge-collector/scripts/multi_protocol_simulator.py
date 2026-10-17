#!/usr/bin/env python3
"""
Multi-Protocol Industrial Plant Simulator & Stage 1 Exception/Deadband Filter.

Continuously generates deterministic + realistic telemetry for the 5 GxP tags,
applies OSIsoft PI-style Stage 1 Exception/Deadband filtering (ExcDev & ExcMax)
in memory, and emits Influx Line Protocol to stdout for Telegraf [[inputs.execd]].
"""

from __future__ import annotations

import math
import random
import signal
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class TagFilterConfig:
    tag_id: int
    tag_name: str
    protocol: str
    exc_dev: float
    exc_max: float
    is_step_tag: bool = False


@dataclass
class TagState:
    last_good_val: Optional[float] = None
    last_emitted_val: Optional[float] = None
    last_quality: Optional[int] = None
    last_status_code: Optional[int] = None
    last_emit_ts: Optional[float] = None


class ExceptionDeadbandFilter:
    """Stage 1 Exception/Deadband Filter (ExcDev / ExcMax)."""

    def __init__(self, configs: Dict[int, TagFilterConfig]) -> None:
        self.configs = configs
        self.states: Dict[int, TagState] = {tag_id: TagState() for tag_id in configs}

    def should_emit(
        self,
        tag_id: int,
        ts: float,
        val: float,
        quality: int,
        status_code: int,
    ) -> bool:
        cfg = self.configs[tag_id]
        st = self.states[tag_id]

        # 1. Always emit the initial value on startup
        if st.last_emit_ts is None:
            self._record(st, ts, val, quality, status_code)
            return True

        # 2. Always emit immediately on OPC quality or status_code transition
        if quality != st.last_quality or status_code != st.last_status_code:
            self._record(st, ts, val, quality, status_code)
            return True

        # 3. Always emit if ExcMax heartbeat timer has elapsed
        elapsed = ts - st.last_emit_ts
        if elapsed >= cfg.exc_max:
            self._record(st, ts, val, quality, status_code)
            return True

        # 4. Compare against last reference value using ExcDev deadband
        ref_val = st.last_good_val if st.last_good_val is not None else st.last_emitted_val
        if ref_val is None:
            self._record(st, ts, val, quality, status_code)
            return True

        if cfg.is_step_tag:
            if val != ref_val:
                self._record(st, ts, val, quality, status_code)
                return True
        else:
            if abs(val - ref_val) >= cfg.exc_dev:
                self._record(st, ts, val, quality, status_code)
                return True

        return False

    @staticmethod
    def _record(
        st: TagState,
        ts: float,
        val: float,
        quality: int,
        status_code: int,
    ) -> None:
        st.last_emitted_val = val
        if quality >= 192:
            st.last_good_val = val
        st.last_quality = quality
        st.last_status_code = status_code
        st.last_emit_ts = ts


def map_bacnet_status_flags(
    in_alarm: bool = False,
    fault: bool = False,
    overridden: bool = False,
    out_of_service: bool = False,
) -> Tuple[int, int]:
    """Map IEEE/ASHRAE BACnet Status_Flags bitstring to OPC Quality and status_code."""
    if fault:
        return 0, 1  # Bad quality, device fault
    if out_of_service or overridden:
        return 64, 3  # Uncertain quality, out-of-service / overridden
    if in_alarm:
        return 192, 4  # Good quality, alarm active
    return 192, 0


def generate_plant_signals(
    tick: int,
    now_sec: float,
    rng: random.Random,
) -> list[Tuple[int, float, str, int, int]]:
    """
    Generate one 1-second scan across all 5 industrial protocols:
      - 101: BR201_TEMP_PV (OPC UA)
      - 102: BR201_PH_PV (OPC UA with periodic quality=0, status_code=2, val=99.9 fault)
      - 103: BR201_AGIT_STATE (Siemens S7 discrete step tag: 0=OFF, 1=LOW, 2=HIGH_RUN)
      - 301: CR_ISO7_DP_PV (BACnet/IP cleanroom differential pressure)
      - 401: CHROM_UV280_PV (Windows OPC DA chromatography UV absorbance profile)
    """
    samples: list[Tuple[int, float, str, int, int]] = []

    # --- Tag 101: BR201_TEMP_PV (OPC UA) ---
    # Sinusoidal 37.0°C ± 0.3°C with periodic thermal excursions up to 38.6°C
    phase_101 = (tick % 60) / 60.0 * (2.0 * math.pi)
    if 40 <= (tick % 60) <= 48:
        # Simulated jacket control valve excursion up to 38.6°C
        excursion_progress = math.sin(((tick % 60) - 40) / 8.0 * math.pi)
        temp_val = 37.3 + 1.3 * excursion_progress
    else:
        temp_val = 37.0 + 0.3 * math.sin(phase_101) + rng.uniform(-0.04, 0.04)
    samples.append((101, round(temp_val, 4), "", 192, 0))

    # --- Tag 102: BR201_PH_PV (OPC UA) ---
    # Steady 7.05 ± 0.05 pH, with periodic quality=0, status_code=2, val=99.9 fault
    if tick % 5 == 2:
        # Simulated broken pH electrode wire / I/O timeout fault
        samples.append((102, 99.9, "IO_TIMEOUT_FAULT", 0, 2))
    else:
        ph_val = 7.05 + 0.05 * math.cos(tick * 0.25) + rng.uniform(-0.015, 0.015)
        samples.append((102, round(ph_val, 4), "", 192, 0))

    # --- Tag 103: BR201_AGIT_STATE (Siemens S7 Step Tag) ---
    # Discrete step values (0 = OFF, 1 = LOW, 2 = HIGH_RUN) changing every 60 seconds
    agit_cycle = (int(now_sec) // 60) % 3
    if agit_cycle == 0:
        # Ensure active run state is visible while cycling deterministically every 60s
        agit_val, agit_str = 2.0, "HIGH_RUN"
    elif agit_cycle == 1:
        agit_val, agit_str = 1.0, "LOW"
    else:
        agit_val, agit_str = 0.0, "OFF"
    samples.append((103, agit_val, agit_str, 192, 0))

    # --- Tag 301: CR_ISO7_DP_PV (BACnet/IP Cleanroom Differential Pressure) ---
    # 18.5 Pa ± 0.8 Pa with BACnet Status_Flags mapped to quality=192
    dp_val = 18.5 + 0.8 * math.sin(tick * 0.18) + rng.uniform(-0.08, 0.08)
    bacnet_quality, bacnet_status = map_bacnet_status_flags(
        in_alarm=False, fault=False, overridden=False, out_of_service=False
    )
    samples.append((301, round(dp_val, 4), "", bacnet_quality, bacnet_status))

    # --- Tag 401: CHROM_UV280_PV (Legacy Windows OPC DA Bridge) ---
    # Chromatography UV 280nm absorbance Gaussian elution peak profile
    chrom_pos = tick % 90
    baseline_mau = 12.0 + 1.5 * math.sin(tick * 0.1)
    main_peak_mau = 780.0 * math.exp(-((chrom_pos - 45.0) ** 2) / (2.0 * (9.5 ** 2)))
    impurity_shoulder_mau = 95.0 * math.exp(-((chrom_pos - 26.0) ** 2) / (2.0 * (4.0 ** 2)))
    uv_val = baseline_mau + main_peak_mau + impurity_shoulder_mau + rng.uniform(-0.3, 0.3)
    samples.append((401, round(uv_val, 4), "", 192, 0))

    return samples


def format_influx_line(
    tag_id: int,
    val: float,
    str_val: str,
    quality: int,
    status_code: int,
    ts_ns: int,
) -> str:
    escaped_str = str_val.replace('\\', '\\\\').replace('"', '\\"')
    return (
        f"sensor_data,tag_id={tag_id} "
        f"val={val},str_val=\"{escaped_str}\",quality={quality}i,status_code={status_code}i "
        f"{ts_ns}"
    )


def main() -> None:
    running = True

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tag_configs: Dict[int, TagFilterConfig] = {
        101: TagFilterConfig(101, "BR201_TEMP_PV", "OPC_UA", exc_dev=0.05, exc_max=5.0, is_step_tag=False),
        102: TagFilterConfig(102, "BR201_PH_PV", "OPC_UA", exc_dev=0.02, exc_max=5.0, is_step_tag=False),
        103: TagFilterConfig(103, "BR201_AGIT_STATE", "S7COMM", exc_dev=0.0, exc_max=5.0, is_step_tag=True),
        301: TagFilterConfig(301, "CR_ISO7_DP_PV", "BACNET_IP", exc_dev=0.10, exc_max=5.0, is_step_tag=False),
        401: TagFilterConfig(401, "CHROM_UV280_PV", "OPC_DA", exc_dev=0.05, exc_max=5.0, is_step_tag=False),
    }

    exc_filter = ExceptionDeadbandFilter(tag_configs)
    rng = random.Random(20261017)
    tick = 0

    while running:
        now_sec = time.time()
        ts_ms = int(now_sec * 1000)
        ts_ns = ts_ms * 1_000_000

        samples = generate_plant_signals(tick=tick, now_sec=now_sec, rng=rng)
        for tag_id, val, str_val, quality, status_code in samples:
            if exc_filter.should_emit(tag_id, now_sec, val, quality, status_code):
                line = format_influx_line(tag_id, val, str_val, quality, status_code, ts_ns)
                sys.stdout.write(line + "\n")

        sys.stdout.flush()
        tick += 1
        time.sleep(1.0)


if __name__ == "__main__":
    main()
