#!/usr/bin/env python3
"""
Production Reference: Legacy Windows OPC DA 2.05a Localhost COM Forwarder.

Runs directly on the Windows chromatography skid workstation (avoiding DCOM port
135/ephemeral firewall exposure), polls local COM OPC DA servers via pywin32 /
OpenOPC, applies Stage 1 Exception/Deadband filtering, buffers to a local disk
spool if the network is unreachable, and forwards normalized JSON batches to
the Linux Edge Collector HTTP listener (:8080/ingest).
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("opcda_windows_forwarder")


class TelemetryPoint(BaseModel):
    tag_id: int
    ts: int = Field(description="UTC epoch timestamp in milliseconds")
    val: float
    str_val: str = ""
    quality: int = Field(default=192, description="192=Good, 64=Uncertain, 0=Bad")
    status_code: int = 0


class OpcDaTagSpec(BaseModel):
    tag_id: int
    item_id: str
    exc_dev: float = 0.05
    exc_max: float = 10.0


def map_opcda_quality(com_quality_str: str) -> int:
    """Normalize OpenOPC / OPC DA 2.05a quality strings to integer OPC quality codes."""
    normalized = (com_quality_str or "").strip().lower()
    if normalized.startswith("good"):
        return 192
    if normalized.startswith("uncertain"):
        return 64
    return 0


class LocalSpoolBuffer:
    """Disk-backed JSONL store-and-forward spool for transient network outages."""

    def __init__(self, spool_path: pathlib.Path) -> None:
        self.spool_path = spool_path
        self.spool_path.parent.mkdir(parents=True, exist_ok=True)

    def append_batch(self, batch: List[TelemetryPoint]) -> None:
        with self.spool_path.open("a", encoding="utf-8") as fh:
            for pt in batch:
                fh.write(pt.model_dump_json() + "\n")

    def drain_batches(self, max_items: int = 500) -> List[Dict[str, object]]:
        if not self.spool_path.exists():
            return []
        lines = self.spool_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return []
        drained = [json.loads(line) for line in lines[:max_items] if line.strip()]
        remaining = lines[max_items:]
        if remaining:
            self.spool_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            self.spool_path.unlink(missing_ok=True)
        return drained


class WindowsOpcDaForwarder:
    """Polls local Windows COM OPC DA server and forwards batches to Edge Collector :8080/ingest."""

    def __init__(
        self,
        prog_id: str,
        ingest_url: str,
        tags: List[OpcDaTagSpec],
        spool_file: str = "./opcda_spool.jsonl",
    ) -> None:
        self.prog_id = prog_id
        self.ingest_url = ingest_url
        self.tags = {t.item_id: t for t in tags}
        self.spool = LocalSpoolBuffer(pathlib.Path(spool_file))
        self.last_val: Dict[int, float] = {}
        self.last_quality: Dict[int, int] = {}
        self.last_emit: Dict[int, float] = {}
        self._opc_client = None

    def connect_com(self) -> None:
        try:
            import OpenOPC  # type: ignore[import-not-found]

            self._opc_client = OpenOPC.client()
            self._opc_client.connect(self.prog_id, "localhost")
            logger.info("Connected to local Windows OPC DA COM server: %s", self.prog_id)
        except ImportError:
            logger.warning("OpenOPC/pywin32 not installed on this platform; using simulated COM read")
            self._opc_client = None

    def poll_once(self) -> List[TelemetryPoint]:
        now = time.time()
        ts_ms = int(now * 1000)
        raw_items: List[tuple[str, float, str]] = []

        if self._opc_client is not None:
            results = self._opc_client.read(list(self.tags.keys()), group="GxP_Historian_Group")
            for item_id, val, quality_str, _ts in results:
                raw_items.append((item_id, float(val or 0.0), str(quality_str)))
        else:
            for item_id in self.tags:
                raw_items.append((item_id, 125.4, "Good"))

        emitted: List[TelemetryPoint] = []
        for item_id, val, quality_str in raw_items:
            spec = self.tags[item_id]
            quality = map_opcda_quality(quality_str)
            status_code = 0 if quality >= 192 else 2

            prev_val: Optional[float] = self.last_val.get(spec.tag_id)
            prev_q: Optional[int] = self.last_quality.get(spec.tag_id)
            prev_ts: float = self.last_emit.get(spec.tag_id, 0.0)

            if (
                prev_val is None
                or quality != prev_q
                or (now - prev_ts) >= spec.exc_max
                or abs(val - prev_val) >= spec.exc_dev
            ):
                self.last_val[spec.tag_id] = val
                self.last_quality[spec.tag_id] = quality
                self.last_emit[spec.tag_id] = now
                emitted.append(
                    TelemetryPoint(
                        tag_id=spec.tag_id,
                        ts=ts_ms,
                        val=val,
                        quality=quality,
                        status_code=status_code,
                    )
                )
        return emitted

    def flush_to_edge(self, points: List[TelemetryPoint]) -> None:
        payload = self.spool.drain_batches() + [pt.model_dump() for pt in points]
        if not payload:
            return
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(self.ingest_url, json=payload)
                resp.raise_for_status()
        except Exception as exc:
            logger.error("Edge collector unreachable (%s); spooling %d points to disk", exc, len(points))
            self.spool.append_batch(points)


if __name__ == "__main__":
    forwarder = WindowsOpcDaForwarder(
        prog_id=os.getenv("OPCDA_PROG_ID", "Matrikon.OPC.Simulation.1"),
        ingest_url=os.getenv("EDGE_INGEST_URL", "http://localhost:8080/ingest"),
        tags=[
            OpcDaTagSpec(
                tag_id=401,
                item_id="DSP.Chrom.UV280.PV",
                exc_dev=0.05,
                exc_max=10.0,
            )
        ],
    )
    forwarder.connect_com()
    batch = forwarder.poll_once()
    logger.info("Prepared %d OPC DA telemetry points for edge ingestion", len(batch))
