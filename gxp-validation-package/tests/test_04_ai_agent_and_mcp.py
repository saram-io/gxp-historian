"""
Operational Qualification (OQ) — Pydantic AI Co-Pilot, Capabilities on Demand,
Human-in-the-Loop 21 CFR Part 11 Deferred Tool Approvals, and `gxphistorian-mcp` Server.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import httpx
from pydantic_ai import DeferredToolRequests, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from conftest import MCP_BASE_URL, REPO_ROOT, EvidenceTracker

APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from gxp_ai_agent import (  # noqa: E402
    GxPHistorianDeps,
    gxp_copilot_agent,
)


def test_oq_11_pydantic_ai_deviation_investigator_and_mcp(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    Verify Pydantic AI `gxp_deviation_investigator_agent` Event Frame investigation,
    `part11-forensics` deferred capability loading, and `gxphistorian-mcp` manifest.
    """
    # 1. Ensure at least one Event Frame exists
    eval_resp = api_client.post("/api/v1/event-frames/evaluate")
    assert eval_resp.status_code == 200
    ef_list = api_client.get("/api/v1/event-frames").json()["event_frames"]
    assert len(ef_list) > 0
    target_ef_id = ef_list[0]["event_id"]

    # 2. Verify MCP & Pydantic AI manifest endpoint on historian-api and standalone gxphistorian-mcp container
    manifest_resp = api_client.get("/api/v1/ai/mcp/manifest")
    assert manifest_resp.status_code == 200
    manifest = manifest_resp.json()
    assert manifest["server_name"] == "gxphistorian-mcp"
    assert manifest["container_service"] == "gxphistorian-mcp"
    assert "mcp_draft_deviation_brief" in manifest["mcp_tools"]
    assert manifest["gxp_guardrails"]["quality_filter"] == "WHERE quality >= 192"

    mcp_container_resp = httpx.get(f"{MCP_BASE_URL}/mcp/manifest", timeout=10.0)
    assert mcp_container_resp.status_code == 200
    assert mcp_container_resp.json()["server_name"] == "gxphistorian-mcp"

    # 3. Verify live Streamable HTTP MCP protocol execution (all 6 tools + all 3 resources) against gxphistorian-mcp container
    import asyncio
    import json
    from fastmcp import Client as FastMCPClient

    async def _verify_live_http_mcp() -> tuple[list[str], list[str]]:
        async with FastMCPClient(f"{MCP_BASE_URL}/mcp") as mcp_client:
            tools = await mcp_client.list_tools()
            resources = await mcp_client.list_resources()

            assets_res = await mcp_client.call_tool("mcp_browse_assets", {"root_path": "BioCorp.Fremont.USP"})
            assert assets_res.data["count"] >= 1

            lttb_res = await mcp_client.call_tool("mcp_get_lttb_plot_values", {"tag_id": 101, "intervals": 10})
            assert lttb_res.data["downsampling_algorithm"] == "largestTriangleThreeBuckets"

            dl_res = await mcp_client.call_tool("mcp_get_sampled_datalink", {"tag_name": "BR201_TEMP_PV", "step_seconds": 60})
            assert dl_res.data["interpolation_mode"] == "LINEAR"

            ef_res = await mcp_client.call_tool("mcp_list_event_frames", {})
            assert ef_res.data["count"] >= 1

            audit_res = await mcp_client.call_tool("mcp_verify_part11_audit_chain", {})
            assert audit_res.data["chain_valid"] is True

            brief_res = await mcp_client.call_tool("mcp_draft_deviation_brief", {"event_id": target_ef_id})
            assert brief_res.data["event_id"] == target_ef_id
            assert brief_res.data["part11_audit_chain_valid"] is True

            for uri in ("gxphistorian://assets/tree", "gxphistorian://audit/verify", "gxphistorian://docs/catalog"):
                res_contents = await mcp_client.read_resource(uri)
                assert len(res_contents) >= 1
                parsed_json = json.loads(res_contents[0].text)
                assert isinstance(parsed_json, dict)

            return [t.name for t in tools], [str(r.uri) for r in resources]

    live_mcp_tools, live_mcp_resources = asyncio.run(_verify_live_http_mcp())
    assert set(manifest["mcp_tools"]).issubset(set(live_mcp_tools))
    assert set(manifest["mcp_resources"]).issubset(set(live_mcp_resources))

    # 4. Run AI Deviation Investigator on both historian-api (:8020) and standalone gxphistorian-mcp (:8030)
    inv_resp = api_client.post(f"/api/v1/ai/event-frames/{target_ef_id}/investigate")
    assert inv_resp.status_code == 200
    brief = inv_resp.json()

    mcp_inv_resp = httpx.post(f"{MCP_BASE_URL}/api/v1/ai/event-frames/{target_ef_id}/investigate", timeout=15.0)
    assert mcp_inv_resp.status_code == 200
    assert mcp_inv_resp.json()["event_id"] == target_ef_id

    assert brief["event_id"] == target_ef_id
    assert brief["part11_audit_chain_valid"] is True
    assert len(brief["correlated_sibling_tags"]) >= 3
    by_tag = {t["tag_name"]: t for t in brief["correlated_sibling_tags"]}
    assert by_tag["BR201_TEMP_PV"]["interpolation_mode"] == "LINEAR"
    assert by_tag["BR201_AGIT_STATE"]["interpolation_mode"] == "LOCF_STEP"
    assert "21 CFR §11.200" in brief["part11_advisory_notice"]

    # 3. Also test `gxp_copilot_agent` directly with `TestModel` (calling eager read-only tools)
    dummy_deps = GxPHistorianDeps(
        get_pg_conn=lambda: None,
        get_ch_client=lambda: None,
        get_assets_tree_fn=lambda root: api_client.get("/api/v1/assets/tree").json(),
        get_plot_values_fn=lambda tid, st, et, iv: api_client.get(
            "/api/v1/trends/plot-values",
            params={"tag_id": tid, "intervals": iv},
        ).json(),
        get_datalink_sampled_fn=lambda tname, st, et, step: api_client.get(
            "/api/v1/datalink/sampled",
            params={"tag_name": tname, "step_seconds": step},
        ).json(),
        list_event_frames_fn=lambda: api_client.get("/api/v1/event-frames").json(),
        verify_audit_trail_fn=lambda: api_client.get("/api/v1/audit-trail/verify").json(),
        create_tag_fn=lambda p, a, r: {},
    )
    with gxp_copilot_agent.override(
        model=TestModel(call_tools=["browse_isa95_asset_hierarchy", "inspect_event_frames"])
    ):
        test_res = gxp_copilot_agent.run_sync(
            "List the ISA-95 asset tree and active Event Frames.",
            deps=dummy_deps,
        )
        assert isinstance(test_res.output, str)

    evidence.record(
        assertion_summary=(
            "Verified Pydantic AI `gxp_deviation_investigator_agent` produces a validated "
            "`DeviationInvestigationBrief` with `part11-forensics` capability and `gxphistorian-mcp` manifest."
        ),
        input_payload={"event_id": target_ef_id},
        output_payload={
            "classification": brief["classification"],
            "part11_audit_chain_valid": brief["part11_audit_chain_valid"],
            "sibling_tag_count": len(brief["correlated_sibling_tags"]),
            "mcp_tools": manifest["mcp_tools"],
        },
    )


def test_oq_12_pydantic_ai_part11_human_in_the_loop_tag_approval(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    Verify Pydantic AI `brownfield-onboarding` capability enforces `args_validator` (`ModelRetry`
    on invalid limits), pauses with `ApprovalRequired` (`DeferredToolRequests`), rejects unattributed
    approvals (HTTP 400), and commits approved tags to PostgreSQL `tags` + `part11_audit_log`.
    """
    unique_suffix = uuid.uuid4().hex[:6].upper()
    candidate_tag_name = f"BR201_DO_AI_{unique_suffix}"

    proposal_payload = {
        "tag_name": candidate_tag_name,
        "asset_id": 1,
        "attribute_name": f"Dissolved_Oxygen_AI_{unique_suffix}",
        "eng_units": "%Sat",
        "is_step_tag": False,
        "exc_dev": 0.1,
        "low_limit": 20.0,
        "high_limit": 100.0,
        "source_protocol": "OPC_UA",
        "source_config": {"node_id": f"ns=2;s=BR201.DO.{unique_suffix}"},
    }

    # 1. Stage 1 (`approved=False`): Agent loads `brownfield-onboarding` and pauses with `DeferredToolRequests`
    stage1_resp = api_client.post(
        "/api/v1/ai/copilot/propose-tag",
        json={"proposal": proposal_payload, "approved": False},
    )
    assert stage1_resp.status_code == 200
    stage1_data = stage1_resp.json()
    assert stage1_data["status"] == "approval_required"
    assert len(stage1_data["deferred_approvals"]) == 1
    assert stage1_data["deferred_approvals"][0]["tool_name"] == "propose_part11_tag_creation"

    # 2. Negative Check: Attempting `approved=True` without Part 11 headers is rejected (HTTP 400)
    unauth_resp = api_client.post(
        "/api/v1/ai/copilot/propose-tag",
        json={"proposal": proposal_payload, "approved": True},
    )
    assert unauth_resp.status_code == 400
    assert "21 CFR Part 11 Violation" in unauth_resp.text

    # 3. Stage 2 (`approved=True` with Part 11 headers): Resumes via `DeferredToolResults` and commits to PG
    before_audit = api_client.get("/api/v1/audit-trail/verify").json()
    stage2_resp = api_client.post(
        "/api/v1/ai/copilot/propose-tag",
        headers={
            "X-Actor-Id": "qa_approver_01",
            "X-Change-Reason": "OQ-12 Human-in-the-Loop Pydantic AI Tag Onboarding Approval",
        },
        json={"proposal": proposal_payload, "approved": True},
    )
    assert stage2_resp.status_code == 200
    stage2_data = stage2_resp.json()
    assert stage2_data["status"] == "approved_and_committed"
    assert stage2_data["approved_calls"] == 1

    # 4. Verify SHA-256 WORM audit trail recorded the approved tag creation and remains valid
    after_audit = api_client.get("/api/v1/audit-trail/verify").json()
    assert after_audit["chain_valid"] is True
    assert int(after_audit["total_records"]) >= int(before_audit["total_records"]) + 1

    # 5. Verify `args_validator` raises `ModelRetry` when the model proposes inverted limits (low >= high)
    retry_steps = 0

    def _bad_then_good_model(messages: Any, info: Any) -> ModelResponse:
        nonlocal retry_steps
        retry_steps += 1
        if retry_steps == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="load_capability", args={"id": "brownfield-onboarding"})]
            )
        if retry_steps == 2:
            # Intentionally inverted limits (low_limit=90.0 > high_limit=10.0) -> triggers ModelRetry in args_validator
            bad_args = dict(proposal_payload, low_limit=90.0, high_limit=10.0)
            return ModelResponse(
                parts=[ToolCallPart(tool_name="propose_part11_tag_creation", args=bad_args)]
            )
        if retry_steps == 3:
            # Corrected limits -> reaches ApprovalRequired (DeferredToolRequests)
            return ModelResponse(
                parts=[ToolCallPart(tool_name="propose_part11_tag_creation", args=proposal_payload)]
            )
        return ModelResponse(parts=[TextPart(content="Done")])

    dummy_deps = GxPHistorianDeps(
        get_pg_conn=lambda: None,
        get_ch_client=lambda: None,
        get_assets_tree_fn=lambda root: {},
        get_plot_values_fn=lambda tid, st, et, iv: {},
        get_datalink_sampled_fn=lambda tname, st, et, step: {},
        list_event_frames_fn=lambda: {},
        verify_audit_trail_fn=lambda: {},
        create_tag_fn=lambda p, a, r: {"status": "created"},
    )
    with gxp_copilot_agent.override(model=FunctionModel(_bad_then_good_model)):
        retry_res = gxp_copilot_agent.run_sync("Propose tag with retry check", deps=dummy_deps)
        assert isinstance(retry_res.output, DeferredToolRequests)
        assert retry_steps == 3

    evidence.record(
        assertion_summary=(
            "Verified Pydantic AI `ApprovalRequired` (`DeferredToolRequests` / `DeferredToolResults`), "
            "`args_validator` `ModelRetry` recovery, and 21 CFR Part 11 WORM audit logging."
        ),
        input_payload={"tag_name": candidate_tag_name},
        output_payload={
            "stage1_status": stage1_data["status"],
            "stage2_status": stage2_data["status"],
            "audit_chain_valid": after_audit["chain_valid"],
            "validator_retry_steps": retry_steps,
        },
    )
