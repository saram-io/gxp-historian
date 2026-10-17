#!/usr/bin/env python3
"""
GxPHistorian DataLink Excel UDF & CLI Module (PI DataLink Replacement).

Provides drop-in Excel worksheet functions via xlwings as well as a standalone
CLI/CSV helper:
  - =GXPHISTORIAN_SAMPLED(tag_name, start_time, end_time, step_seconds)
  - =GXPHISTORIAN_PLOT_VALUES(tag_name, start_time, end_time, intervals)
  - =GXPHISTORIAN_EVENT_SUMMARY(event_name)
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Callable, Dict, List, Optional, TypeVar

import httpx

F = TypeVar("F", bound=Callable[..., Any])

try:
    import xlwings as xw  # type: ignore[import-not-found]

    def xl_func(fn: F) -> F:
        return xw.func(fn)  # type: ignore[return-value]

except ImportError:

    def xl_func(fn: F) -> F:
        return fn


HISTORIAN_API_URL = os.getenv("HISTORIAN_API_URL", "http://localhost:8000")

# Local tag_name -> tag_id resolution cache
_TAG_ID_CACHE: Dict[str, int] = {
    "BR201_TEMP_PV": 101,
    "BR201_PH_PV": 102,
    "BR201_AGIT_STATE": 103,
    "CR_ISO7_DP_PV": 301,
    "CHROM_UV280_PV": 401,
}


def _resolve_tag_id(tag_name: str, api_base: str = HISTORIAN_API_URL) -> int:
    if tag_name in _TAG_ID_CACHE:
        return _TAG_ID_CACHE[tag_name]
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{api_base}/api/v1/assets/tree")
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            for tg in asset.get("tags", []):
                _TAG_ID_CACHE[tg["tag_name"]] = int(tg["tag_id"])
    if tag_name not in _TAG_ID_CACHE:
        raise ValueError(f"Unknown historian tag_name: {tag_name}")
    return _TAG_ID_CACHE[tag_name]


@xl_func
def GXPHISTORIAN_SAMPLED(
    tag_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    step_seconds: int = 60,
) -> List[List[Any]]:
    """
    Drop-in replacement for OSIsoft PI DataLink =PISampDat().
    Returns a 2D array [[Timestamp, Value, Units, InterpolationMode], ...] suitable
    for spilling directly into an Excel worksheet grid.
    """
    params: Dict[str, Any] = {
        "tag_name": tag_name,
        "step_seconds": int(step_seconds),
        "format": "json",
    }
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{HISTORIAN_API_URL}/api/v1/datalink/sampled", params=params)
        resp.raise_for_status()
        data = resp.json()

    rows: List[List[Any]] = [
        ["Timestamp (UTC)", f"{data['tag_name']} ({data['eng_units']})", "Interpolation Mode"]
    ]
    for pt in data.get("points", []):
        rows.append([pt["ts"], pt["val"], data["interpolation_mode"]])
    return rows


@xl_func
def GXPHISTORIAN_PLOT_VALUES(
    tag_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    intervals: int = 500,
) -> List[List[Any]]:
    """
    Drop-in replacement for PI DataLink / PI Vision PlotValues using ClickHouse
    largestTriangleThreeBuckets(intervals)(ts, val).
    """
    tag_id = _resolve_tag_id(tag_name)
    params: Dict[str, Any] = {
        "tag_id": tag_id,
        "intervals": int(intervals),
    }
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{HISTORIAN_API_URL}/api/v1/trends/plot-values", params=params)
        resp.raise_for_status()
        data = resp.json()

    rows: List[List[Any]] = [
        ["Timestamp (UTC)", f"{data['tag_name']} ({data['eng_units']})", "Asset Path"]
    ]
    for pt in data.get("points", []):
        rows.append([pt["ts"], pt["val"], data.get("asset_path", "")])
    return rows


@xl_func
def GXPHISTORIAN_EVENT_SUMMARY(event_name: str) -> List[List[Any]]:
    """
    Retrieves ISA-88 Event Frame summary metrics and 21 CFR Part 11 electronic
    signature status by event_name.
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{HISTORIAN_API_URL}/api/v1/event-frames")
        resp.raise_for_status()
        events = resp.json().get("event_frames", [])

    matched = [ef for ef in events if ef.get("event_name") == event_name or event_name in ef.get("event_name", "")]
    if not matched:
        return [["Event Frame Not Found", event_name]]

    ef = matched[0]
    metrics = ef.get("captured_metrics") or {}
    rows: List[List[Any]] = [
        ["Field", "Value"],
        ["event_id", ef.get("event_id")],
        ["event_name", ef.get("event_name")],
        ["event_template", ef.get("event_template")],
        ["asset_path", ef.get("asset_path")],
        ["start_time", ef.get("start_time")],
        ["end_time", ef.get("end_time") or "ACTIVE"],
        ["severity", ef.get("severity")],
        ["signed_by", ef.get("signed_by") or "UNSIGNED"],
        ["signature_meaning", ef.get("signature_meaning") or "-"],
        ["signature_hash", ef.get("signature_hash") or "-"],
    ]
    for k, v in metrics.items():
        rows.append([f"metric.{k}", v])
    return rows


def main() -> None:
    global HISTORIAN_API_URL
    parser = argparse.ArgumentParser(description="GxPHistorian DataLink CLI & UDF Helper")
    parser.add_argument("--api-url", default=HISTORIAN_API_URL, help="Historian API base URL")
    parser.add_argument("--tag", default="BR201_TEMP_PV", help="Tag name to query")
    parser.add_argument("--step", type=int, default=5, help="Sample step seconds")
    args = parser.parse_args()

    HISTORIAN_API_URL = args.api_url

    sampled = GXPHISTORIAN_SAMPLED(args.tag, step_seconds=args.step)
    print(json.dumps({"header": sampled[0], "sample_rows": sampled[1:6]}, indent=2))


if __name__ == "__main__":
    main()
