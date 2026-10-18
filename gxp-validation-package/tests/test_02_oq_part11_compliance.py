"""
Operational Qualification (OQ) — 21 CFR Part 11 Technical Controls (URS-006 through URS-010).

Verifies:
  - Rejection of PostgreSQL mutations missing app.actor_id or app.change_reason
  - WORM immutability of part11_audit_log against UPDATE, DELETE, and TRUNCATE
  - Electronic Signature rejection on invalid credentials (HTTP 401)
  - Electronic Signature execution with valid credentials (qa_approver_01) and HMAC-SHA256 verification
  - End-to-end cryptographic SHA-256 hash chain verification (/api/v1/audit-trail/verify)
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict

import httpx
import psycopg
import pytest

from conftest import EvidenceTracker, get_setting


def test_oq_01_reject_mutations_without_actor_or_reason(
    pg_conn: psycopg.Connection[Dict[str, Any]],
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-006: Verify mutating any of the 10 GxP configuration/state tables without app.actor_id / app.change_reason is rejected."""
    api_client.post("/api/v1/event-frames/evaluate")
    unattributed_challenges = [
        ("asset_templates", "UPDATE asset_templates SET template_name = 'unauth' WHERE template_id = 1;"),
        ("assets", "UPDATE assets SET asset_name = 'unauth' WHERE asset_id = 1;"),
        ("tags", "UPDATE tags SET exc_dev = 0.08 WHERE tag_id = 101;"),
        (
            "event_frames",
            "INSERT INTO event_frames (event_name, event_template, asset_id, start_time) VALUES ('unauth', 'Test', 1, NOW());",
        ),
        ("digital_state_sets", "UPDATE digital_state_sets SET description = 'unauth';"),
        ("event_frame_templates", "UPDATE event_frame_templates SET severity = 'INFO';"),
        (
            "event_frame_signatures",
            "INSERT INTO event_frame_signatures (event_id, user_id, signer_full_name, signer_role, signature_meaning, change_reason, signature_hash) "
            "VALUES ((SELECT event_id FROM event_frames LIMIT 1), 'u', 'n', 'r', 'm', 'c', 'h');",
        ),
        (
            "manual_logger_entries",
            "INSERT INTO manual_logger_entries (tag_id, sample_ts, val, operator_id) VALUES (101, NOW(), 7.0, 'unauth');",
        ),
        ("notification_rules", "UPDATE notification_rules SET is_active = FALSE;"),
        (
            "notification_deliveries",
            "INSERT INTO notification_deliveries (rule_id, event_id, channel_type, target_endpoint) "
            "VALUES ((SELECT rule_id FROM notification_rules LIMIT 1), (SELECT event_id FROM event_frames LIMIT 1), 'SMS', '+1');",
        ),
    ]
    verified_tables: list[str] = []
    err_msg = ""
    for tbl_name, sql_stmt in unattributed_challenges:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            with pg_conn.cursor() as cur:
                cur.execute(sql_stmt)
        pg_conn.rollback()
        err_msg = str(exc_info.value)
        assert "21 CFR Part 11 Violation: app.actor_id and app.change_reason are mandatory" in err_msg
        verified_tables.append(tbl_name)

    # Also verify REST API rejects POST /api/v1/tags without X-Actor-Id / X-Change-Reason headers
    resp = api_client.post(
        "/api/v1/tags",
        json={
            "tag_name": "UNAUTH_TEST_TAG",
            "asset_id": 1,
            "attribute_name": "Unauthorized_Attr",
            "eng_units": "degC",
            "source_protocol": "OPC_UA",
        },
    )
    assert resp.status_code == 400
    assert "21 CFR Part 11 Violation" in resp.text

    evidence.record(
        assertion_summary="Confirmed PostgreSQL PL/pgSQL trigger across all 10 GxP tables and FastAPI reject unattributed mutations.",
        input_payload={"challenged_tables": verified_tables},
        output_payload={"postgres_exception": err_msg.strip(), "verified_table_count": len(verified_tables), "api_status_code": resp.status_code},
    )


def test_oq_02_worm_audit_log_immutability(
    pg_conn: psycopg.Connection[Dict[str, Any]],
    evidence: EvidenceTracker,
) -> None:
    """URS-007: Verify UPDATE, DELETE, and TRUNCATE on part11_audit_log raise WORM exception."""
    captured_errors: Dict[str, str] = {}

    for op_name, stmt in [
        ("UPDATE", "UPDATE part11_audit_log SET actor_id = 'tampered' WHERE audit_id = 1;"),
        ("DELETE", "DELETE FROM part11_audit_log WHERE audit_id = 1;"),
        ("TRUNCATE", "TRUNCATE TABLE part11_audit_log;"),
    ]:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            with pg_conn.cursor() as cur:
                cur.execute(stmt)
        pg_conn.rollback()
        err_text = str(exc_info.value).strip()
        assert "21 CFR Part 11 WORM Violation: Audit trail records are immutable" in err_text
        captured_errors[op_name] = err_text

    evidence.record(
        assertion_summary="Verified UPDATE, DELETE, and TRUNCATE on part11_audit_log unconditionally raise 21 CFR Part 11 WORM Violation.",
        input_payload={"attempted_operations": ["UPDATE", "DELETE", "TRUNCATE"]},
        output_payload={"worm_exceptions": captured_errors},
    )


def test_oq_03_electronic_signature_rejects_invalid_credentials(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-008: Verify signing an Event Frame with wrong password returns HTTP 401."""
    eval_resp = api_client.post("/api/v1/event-frames/evaluate")
    assert eval_resp.status_code == 200

    ef_list = api_client.get("/api/v1/event-frames").json()["event_frames"]
    assert len(ef_list) > 0
    target_event_id = ef_list[0]["event_id"]

    bad_sign_resp = api_client.post(
        f"/api/v1/event-frames/{target_event_id}/sign",
        headers={
            "X-Actor-Id": "qa_approver_01",
            "X-Change-Reason": "Negative OQ Test - Invalid Password Challenge",
        },
        json={
            "user_id": "qa_approver_01",
            "password": "WRONG_PASSWORD_2026!",
            "signature_meaning": "Batch Release Approval",
            "change_reason": "Negative OQ Test - Invalid Password Challenge",
        },
    )
    assert bad_sign_resp.status_code == 401
    assert "Electronic Signature Authentication Failed" in bad_sign_resp.text

    evidence.record(
        assertion_summary="Verified POST /api/v1/event-frames/{id}/sign rejects invalid password with HTTP 401.",
        input_payload={"event_id": target_event_id, "user_id": "qa_approver_01", "password": "REDACTED_INVALID"},
        output_payload={"status_code": bad_sign_resp.status_code, "response": bad_sign_resp.json()},
    )


def test_oq_04_electronic_signature_approval_and_hmac(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-009: Verify valid Electronic Signature execution, HMAC-SHA256 binding, and audit log increment."""
    before_audit = api_client.get("/api/v1/audit-trail/verify").json()
    before_count = int(before_audit["total_records"])

    ef_list = api_client.get("/api/v1/event-frames").json()["event_frames"]
    assert len(ef_list) > 0
    target_event_id = ef_list[0]["event_id"]

    sign_resp = api_client.post(
        f"/api/v1/event-frames/{target_event_id}/sign",
        headers={
            "X-Actor-Id": "qa_approver_01",
            "X-Change-Reason": "Formal OQ Batch Release Electronic Signature Qualification",
        },
        json={
            "user_id": "qa_approver_01",
            "password": "QA_Approver_2026!",
            "signature_meaning": "Batch Release Approval",
            "change_reason": "Formal OQ Batch Release Electronic Signature Qualification",
        },
    )
    assert sign_resp.status_code == 200
    signed_data = sign_resp.json()
    ef = signed_data["event_frame"]
    assert ef["signed_by"] == "qa_approver_01"
    assert ef["signature_meaning"] == "Batch Release Approval"
    assert len(ef["signature_hash"]) == 64

    # Independently recompute HMAC-SHA256 to verify cryptographic binding
    secret_key = get_setting("ESIG_SECRET_KEY", "Part11_Hmac_Key_2026!")
    signed_at_dt_str = ef["signed_at"].replace("Z", "+00:00")
    canonical = f"{target_event_id}|qa_approver_01|Batch Release Approval|{signed_at_dt_str}"
    expected_hmac = hmac.new(
        secret_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert ef["signature_hash"] == expected_hmac

    after_audit = api_client.get("/api/v1/audit-trail/verify").json()
    assert int(after_audit["total_records"]) >= before_count + 1
    assert after_audit["chain_valid"] is True

    evidence.record(
        assertion_summary="Verified dual-challenge electronic signature execution, HMAC-SHA256 binding, and audit trail logging.",
        input_payload={"event_id": target_event_id, "user_id": "qa_approver_01", "signature_meaning": "Batch Release Approval"},
        output_payload={"signed_event_frame": ef, "hmac_verified": True, "audit_records_after": after_audit["total_records"]},
    )


def test_oq_05_cryptographic_hash_chain_verification(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """URS-010: Verify end-to-end SHA-256 hash chain from GENESIS_0000000000000000."""
    resp = api_client.get("/api/v1/audit-trail/verify")
    assert resp.status_code == 200
    audit_report = resp.json()

    assert audit_report["chain_valid"] is True
    assert audit_report["total_records"] >= 10
    assert audit_report["verified_hashes"] == audit_report["total_records"]
    assert audit_report["broken_at_audit_id"] is None

    evidence.record(
        assertion_summary="Verified 100% of part11_audit_log records form an unbroken SHA-256 hash chain from GENESIS_0000000000000000.",
        input_payload={"endpoint": "/api/v1/audit-trail/verify"},
        output_payload=audit_report,
    )
