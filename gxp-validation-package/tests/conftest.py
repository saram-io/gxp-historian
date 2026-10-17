"""
Pytest Configuration, Live Stack Fixtures, and GAMP 5 / FDA CSA Evidence Recorder.

Automatically captures test execution metadata (start/end UTC timestamps, duration,
assertion details, input/output payloads, and pass/fail status) and writes
gxp-validation-package/evidence/oq_execution_results.json after test session completion.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import platform
from typing import Any, Dict, Iterator

import clickhouse_connect
import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "gxp-validation-package" / "evidence"
EVIDENCE_FILE = EVIDENCE_DIR / "oq_execution_results.json"


def _load_dotenv() -> Dict[str, str]:
    env_map: Dict[str, str] = {}
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()
    return env_map


_DOTENV = _load_dotenv()


def get_setting(key: str, default: str) -> str:
    return os.getenv(key, _DOTENV.get(key, default))


PG_HOST = get_setting("PG_HOST_TEST", "localhost")
PG_PORT = int(get_setting("PG_PORT", "5435"))
PG_USER = get_setting("PG_USER", "historian_admin")
PG_PASSWORD = get_setting("PG_PASSWORD", "GxP_Pg_Secret_2026!")
PG_DB = get_setting("PG_DB", "pi_control_plane")

CH_HOST = get_setting("CH_HOST_TEST", "localhost")
CH_HTTP_PORT = int(get_setting("CH_HTTP_PORT", "8125"))
CH_USER = get_setting("CH_USER", "historian_admin")
CH_PASSWORD = get_setting("CH_PASSWORD", "GxP_Ch_Secret_2026!")
CH_DB = get_setting("CH_DB", "pi_historian")

API_BASE_URL = get_setting("API_BASE_URL", f"http://localhost:{get_setting('API_PORT', '8020')}")
GRAFANA_BASE_URL = get_setting("GRAFANA_BASE_URL", f"http://localhost:{get_setting('GRAFANA_PORT', '3020')}")
GRAFANA_PASSWORD = get_setting("GRAFANA_PASSWORD", "GxP_Grafana_2026!")

_SESSION_START_UTC: str = ""
_TEST_EVIDENCE_RECORDS: Dict[str, Dict[str, Any]] = {}


class EvidenceTracker:
    """Allows individual IQ/OQ tests to attach structured input/output payloads and assertion details."""

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.assertions: list[str] = []
        self.input_payload: Dict[str, Any] = {}
        self.output_payload: Dict[str, Any] = {}

    def record(
        self,
        assertion_summary: str,
        input_payload: Dict[str, Any] | None = None,
        output_payload: Dict[str, Any] | None = None,
    ) -> None:
        self.assertions.append(assertion_summary)
        if input_payload is not None:
            self.input_payload.update(input_payload)
        if output_payload is not None:
            self.output_payload.update(output_payload)


@pytest.fixture
def evidence(request: pytest.FixtureRequest) -> Iterator[EvidenceTracker]:
    nodeid = request.node.nodeid
    tracker = EvidenceTracker(nodeid=nodeid)
    yield tracker
    rec = _TEST_EVIDENCE_RECORDS.setdefault(nodeid, {})
    rec["assertion_details"] = tracker.assertions
    rec["input_payload"] = tracker.input_payload
    rec["output_payload"] = tracker.output_payload


@pytest.fixture
def pg_conn() -> Iterator[psycopg.Connection[Dict[str, Any]]]:
    conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB,
        row_factory=dict_row,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def ch_client() -> Iterator[Any]:
    client = clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_HTTP_PORT,
        username=CH_USER,
        password=CH_PASSWORD,
        database=CH_DB,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def api_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_BASE_URL, timeout=15.0) as client:
        yield client


def pytest_sessionstart(session: pytest.Session) -> None:
    global _SESSION_START_UTC
    _SESSION_START_UTC = dt.datetime.now(dt.timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    start_ts = dt.datetime.fromtimestamp(call.start, tz=dt.timezone.utc).isoformat()
    outcome = yield
    report = outcome.get_result()

    if report.when == "call":
        end_ts = dt.datetime.fromtimestamp(call.stop, tz=dt.timezone.utc).isoformat()
        rec = _TEST_EVIDENCE_RECORDS.setdefault(item.nodeid, {})
        rec.update(
            {
                "pytest_node_id": item.nodeid,
                "test_name": item.name,
                "module": item.module.__name__,
                "docstring": (item.obj.__doc__ or "").strip(),
                "start_utc": start_ts,
                "end_utc": end_ts,
                "duration_seconds": round(report.duration, 4),
                "status": "PASS" if report.passed else "FAIL",
                "longrepr": str(report.longrepr) if report.failed else None,
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    session_end_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    records = list(_TEST_EVIDENCE_RECORDS.values())
    passed_count = sum(1 for r in records if r.get("status") == "PASS")
    failed_count = sum(1 for r in records if r.get("status") != "PASS")

    payload = {
        "qualification_suite": "OpenHistorian GxP Industrial Historian IQ/OQ/PQ Automated Qualification Suite",
        "regulatory_standard": "21 CFR Part 11 / EU GMP Annex 11 / ISPE GAMP 5 / FDA CSA",
        "execution_environment": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "postgres_endpoint": f"{PG_HOST}:{PG_PORT}/{PG_DB}",
            "clickhouse_endpoint": f"{CH_HOST}:{CH_HTTP_PORT}/{CH_DB}",
            "historian_api_url": API_BASE_URL,
            "grafana_url": GRAFANA_BASE_URL,
        },
        "session_start_utc": _SESSION_START_UTC,
        "session_end_utc": session_end_utc,
        "overall_status": "PASS" if (exitstatus == 0 and failed_count == 0 and passed_count > 0) else "FAIL",
        "summary": {
            "total_tests": len(records),
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate_pct": round((passed_count / len(records)) * 100.0, 2) if records else 0.0,
        },
        "test_results": records,
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
