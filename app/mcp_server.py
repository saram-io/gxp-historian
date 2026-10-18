#!/usr/bin/env python3
"""
GxPHistorian Model Context Protocol (MCP) Server (`gxphistorian-mcp`).

Exposes read-only, GAMP 5 / 21 CFR Part 11 compliant historian tools and resources
to MCP clients (Claude Desktop, Cursor, Antigravity, or Pydantic AI `MCP(local=...)`):
  - All time-series calculations run deterministically in ClickHouse (`WHERE quality >= 192`).
  - Continuous tags (`is_step_tag=False`) use `LINEAR` interpolation; discrete state tags
    (`is_step_tag=True`) use integer `LOCF_STEP` interpolation.
  - Exposes SHA-256 WORM audit verification and automated Event Frame deviation briefs.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Header
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from gxp_ai_agent import (
    DEFAULT_MODEL_NAME,
    DeviationInvestigationBrief,
    GxPHistorianDeps,
    StagedTagProposalItem,
    build_deterministic_deviation_brief,
)


class TagOnboardingApprovalRequest(BaseModel):
    proposal: StagedTagProposalItem
    approved: bool = Field(
        default=False,
        description="False to stage and return DeferredToolRequests; True to approve and commit with Part 11 headers.",
    )


def create_gxphistorian_mcp_server(deps_factory: Callable[[], GxPHistorianDeps]) -> FastMCP:
    """
    Create and configure the `gxphistorian-mcp` FastMCP server bound to Pillar 2 (ClickHouse)
    and Pillar 3 (PostgreSQL) via `deps_factory`.
    """
    mcp = FastMCP(
        name="gxphistorian-mcp",
        instructions=(
            "GxPHistorian 21 CFR Part 11 / EU GMP Annex 11 Industrial Historian MCP Server. "
            "All analytical queries enforce OPC quality >= 192 and respect tag interpolation mode "
            "(LINEAR vs LOCF_STEP)."
        ),
    )

    @mcp.tool()
    def mcp_browse_assets(root_path: Optional[str] = None) -> Dict[str, Any]:
        """Browse the ISA-95 ltree asset hierarchy and tag catalog in PostgreSQL."""
        deps = deps_factory()
        return deps.get_assets_tree_fn(root_path)

    @mcp.tool()
    def mcp_get_lttb_plot_values(
        tag_id: int,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        intervals: int = 100,
    ) -> Dict[str, Any]:
        """
        Fetch peak-preserving LTTB (`largestTriangleThreeBuckets`) downsampled telemetry
        from ClickHouse (`WHERE quality >= 192`).
        """
        deps = deps_factory()
        bounded_intervals = max(2, min(int(intervals), 2000))
        return deps.get_plot_values_fn(tag_id, start_time, end_time, bounded_intervals)

    @mcp.tool()
    def mcp_get_sampled_datalink(
        tag_name: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        step_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Fetch PI DataLink-compatible sampled telemetry (`WHERE quality >= 192`) using
        ClickHouse `LINEAR` interpolation (`is_step_tag=False`) or `LOCF_STEP` (`is_step_tag=True`).
        """
        deps = deps_factory()
        return deps.get_datalink_sampled_fn(tag_name, start_time, end_time, step_seconds)

    @mcp.tool()
    def mcp_list_event_frames() -> Dict[str, Any]:
        """List ISA-88 Event Frames, captured KPI snapshots, and 21 CFR Part 11 e-signature status."""
        deps = deps_factory()
        return deps.list_event_frames_fn()

    @mcp.tool()
    def mcp_verify_part11_audit_chain() -> Dict[str, Any]:
        """Verify the cryptographic SHA-256 WORM hash chain across PostgreSQL `part11_audit_log`."""
        deps = deps_factory()
        return deps.verify_audit_trail_fn()

    @mcp.tool()
    def mcp_draft_deviation_brief(event_id: str) -> Dict[str, Any]:
        """
        Generate an auditor-ready 21 CFR Part 11 Advisory Deviation & CAPA Pre-Investigation Brief
        for a specific Event Frame UUID.
        """
        deps = deps_factory()
        brief = build_deterministic_deviation_brief(deps, event_id=event_id)
        return brief.model_dump(mode="json")

    @mcp.resource("gxphistorian://assets/tree")
    def resource_assets_tree() -> str:
        """Full ISA-95 asset hierarchy and tag metadata catalog as JSON."""
        deps = deps_factory()
        return json.dumps(deps.get_assets_tree_fn(None), default=str, indent=2)

    @mcp.resource("gxphistorian://audit/verify")
    def resource_audit_verify() -> str:
        """Live 21 CFR Part 11 SHA-256 WORM hash chain verification report."""
        deps = deps_factory()
        return json.dumps(deps.verify_audit_trail_fn(), default=str, indent=2)

    @mcp.resource("gxphistorian://docs/catalog")
    def resource_docs_catalog() -> str:
        """Index of GxPHistorian biopharma instrument and hardware connector guides."""
        deps = deps_factory()
        guides = sorted(p.name for p in deps.docs_dir.glob("*.md")) if deps.docs_dir.is_dir() else []
        return json.dumps({"docs_dir": str(deps.docs_dir), "guides": guides}, indent=2)

    return mcp


def get_mcp_manifest_summary() -> Dict[str, Any]:
    """Return a structured manifest of `gxphistorian-mcp` tools, resources, and Pydantic AI capabilities."""
    import os

    use_live_llm = os.getenv("GXPHISTORIAN_USE_LIVE_LLM", "0").strip().lower() in ("1", "true", "yes")
    mcp_port = os.getenv("MCP_PORT", "8030")
    return {
        "server_name": "gxphistorian-mcp",
        "container_service": "gxphistorian-mcp",
        "protocol": "Model Context Protocol (MCP) + Pydantic AI",
        "http_mcp_endpoint": f"http://localhost:{mcp_port}/mcp",
        "health_endpoint": f"http://localhost:{mcp_port}/health",
        "ai_model": DEFAULT_MODEL_NAME,
        "live_llm_enabled": use_live_llm,
        "gxp_guardrails": {
            "quality_filter": "WHERE quality >= 192",
            "interpolation_modes": {
                "continuous_analog": "LINEAR (is_step_tag=False)",
                "discrete_state": "LOCF_STEP (is_step_tag=True)",
            },
            "part11_mutation_gate": "ApprovalRequired (DeferredToolRequests) + X-Actor-Id & X-Change-Reason",
            "part11_esig_gate": "Human-only dual-challenge via POST /api/v1/event-frames/{event_id}/sign",
        },
        "pydantic_ai_agents": [
            {
                "name": "gxp_deviation_investigator_agent",
                "output_type": "DeviationInvestigationBrief",
                "capabilities": ["Caching(messages=False)", "part11-forensics (defer_loading=True)"],
            },
            {
                "name": "gxp_copilot_agent",
                "output_type": "[str, BrownfieldOnboardingPlan, DeferredToolRequests]",
                "capabilities": [
                    "Caching()",
                    "part11-forensics (defer_loading=True)",
                    "brownfield-onboarding (defer_loading=True)",
                ],
            },
        ],
        "mcp_tools": [
            "mcp_browse_assets",
            "mcp_get_lttb_plot_values",
            "mcp_get_sampled_datalink",
            "mcp_list_event_frames",
            "mcp_verify_part11_audit_chain",
            "mcp_draft_deviation_brief",
        ],
        "mcp_resources": [
            "gxphistorian://assets/tree",
            "gxphistorian://audit/verify",
            "gxphistorian://docs/catalog",
        ],
    }


def build_standalone_mcp_app() -> Any:
    """
    Build the standalone ASGI application for the `gxphistorian-mcp` Docker Compose container
    (`uvicorn mcp_server:build_standalone_mcp_app --factory --host 0.0.0.0 --port 8030`).

    Exposes:
      - `GET /health` & `GET /api/v1/health`: Container health and DB connectivity status
      - `GET /mcp/manifest` & `GET /api/v1/ai/mcp/manifest`: MCP & Pydantic AI capabilities catalog
      - `POST /api/v1/ai/event-frames/{event_id}/investigate`: `gxp_deviation_investigator_agent`
      - `POST /api/v1/ai/copilot/propose-tag`: `gxp_copilot_agent` Human-in-the-Loop Part 11 gate
      - `POST / GET /mcp`: Native FastMCP Streamable HTTP protocol endpoint
    """
    from main import (
        build_gxp_ai_deps,
        get_ch_client,
        get_pg_conn,
        investigate_event_frame_with_ai,
        propose_or_approve_tag_with_ai,
    )

    mcp = create_gxphistorian_mcp_server(deps_factory=build_gxp_ai_deps)
    mcp_http = mcp.http_app(path="/mcp")

    service_app = FastAPI(
        title="GxPHistorian Pydantic AI Co-Pilot & MCP Server (gxphistorian-mcp)",
        description=(
            "Standalone Pillar 3 Advisory AI Agent & Model Context Protocol (Streamable HTTP) Server "
            "enforcing 21 CFR Part 11, EU GMP Annex 11, and ISPE GAMP 5 guardrails."
        ),
        version="1.0.0",
        lifespan=mcp_http.lifespan,
    )

    @service_app.get("/health")
    @service_app.get("/api/v1/health")
    def mcp_health() -> Dict[str, Any]:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok;")
                pg_ok = cur.fetchone()["ok"] == 1
        ch = get_ch_client()
        ch_ok = ch.command("SELECT 1") == 1
        manifest = get_mcp_manifest_summary()
        return {
            "status": "healthy" if (pg_ok and ch_ok) else "degraded",
            "service": "gxphistorian-mcp",
            "protocol": manifest["protocol"],
            "mcp_endpoint": "/mcp",
            "ai_model": manifest["ai_model"],
            "live_llm_enabled": manifest["live_llm_enabled"],
            "postgres": {"connected": pg_ok},
            "clickhouse": {"connected": ch_ok},
            "pydantic_ai_agents": [a["name"] for a in manifest["pydantic_ai_agents"]],
            "mcp_tools_count": len(manifest["mcp_tools"]),
            "mcp_resources_count": len(manifest["mcp_resources"]),
        }

    @service_app.get("/mcp/manifest")
    @service_app.get("/api/v1/ai/mcp/manifest")
    def mcp_manifest() -> Dict[str, Any]:
        return get_mcp_manifest_summary()

    @service_app.post(
        "/api/v1/ai/event-frames/{event_id}/investigate",
        response_model=DeviationInvestigationBrief,
    )
    def mcp_investigate_event_frame(event_id: uuid.UUID) -> DeviationInvestigationBrief:
        return investigate_event_frame_with_ai(event_id=event_id)

    @service_app.post("/api/v1/ai/copilot/propose-tag")
    def mcp_propose_or_approve_tag(
        body: TagOnboardingApprovalRequest,
        x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
        x_change_reason: Optional[str] = Header(default=None, alias="X-Change-Reason"),
    ) -> Dict[str, Any]:
        return propose_or_approve_tag_with_ai(
            body=body,
            x_actor_id=x_actor_id,
            x_change_reason=x_change_reason,
        )

    service_app.mount("/", mcp_http)
    return service_app


if __name__ == "__main__":
    import argparse
    import os
    import uvicorn
    from main import build_gxp_ai_deps

    parser = argparse.ArgumentParser(description="GxPHistorian MCP & Pydantic AI Server")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default=os.getenv("MCP_TRANSPORT", "http"),
        help="Transport mode: 'http' (Streamable HTTP + REST on port 8030) or 'stdio'",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host for HTTP transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT_INTERNAL", "8030")),
        help="Bind port for HTTP transport",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        server = create_gxphistorian_mcp_server(deps_factory=build_gxp_ai_deps)
        server.run(transport="stdio")
    else:
        uvicorn.run(
            "mcp_server:build_standalone_mcp_app",
            factory=True,
            host=args.host,
            port=args.port,
        )

