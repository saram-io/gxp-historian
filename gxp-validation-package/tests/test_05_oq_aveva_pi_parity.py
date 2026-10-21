"""
Operational Qualification (OQ) — AVEVA PI System Full Analytical, Asset Framework,
BatchView, Manual Logger, Swinging Door Compression & Notifications Parity
(URS-018 through URS-021).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, List

import httpx

from conftest import EvidenceTracker


def _ensure_pi_parity_oq_dataset(ch_client: Any) -> None:
    """
    Idempotently seed deterministic OQ synthetic telemetry in a dedicated
    historical window (2026-01-16 10:00:00 .. 19:00:00 UTC) without ever
    executing ALTER TABLE ... DELETE/UPDATE on ClickHouse.
    """
    existing = int(
        ch_client.command(
            """
            SELECT count()
            FROM pi_historian.sensor_data
            WHERE ts >= '2026-01-16 10:00:00'
              AND ts < '2026-01-16 20:00:00'
            """
        )
        or 0
    )
    # Ensure Tag 301 (CR_ISO7_DP_PV) SQC window is seeded even if 2026-01-16 base dataset was created earlier
    existing_sqc_301 = int(
        ch_client.command(
            """
            SELECT count()
            FROM pi_historian.sensor_data
            WHERE tag_id = 301
              AND ts >= '2026-01-16 16:00:00'
              AND ts < '2026-01-16 16:30:00'
            """
        )
        or 0
    )
    if existing_sqc_301 == 0:
        sqc_rows: List[List[Any]] = []
        base_sqc = dt.datetime(2026, 1, 16, 16, 0, 0, tzinfo=dt.timezone.utc)
        for i in range(19):
            val = 18.0 + ((i % 3) - 1) * 0.15
            sqc_rows.append([301, base_sqc + dt.timedelta(minutes=i), val, "", 192, 0])
        sqc_rows.append([301, base_sqc + dt.timedelta(minutes=19), 42.0, "DP_SPIKE_OUTLIER", 192, 0])
        ch_client.insert(
            "pi_historian.sensor_data",
            sqc_rows,
            column_names=["tag_id", "ts", "val", "str_val", "quality", "status_code"],
        )

    if existing > 0:
        return

    rows: List[List[Any]] = [
        # 1. URS-018 DataLink & StreamSets Window (2026-01-16 10:00:00 .. 10:10:00 UTC)
        # Tag 101 (BR201_TEMP_PV, is_step_tag=False): asymmetric intervals to prove
        # Time-Weighted Trapezoidal (38.0) vs Event-Weighted Mean (37.6667), plus a bad quality=0 fault spike.
        [101, dt.datetime(2026, 1, 16, 10, 0, 0, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
        [101, dt.datetime(2026, 1, 16, 10, 2, 0, tzinfo=dt.timezone.utc), 39.0, "", 192, 0],
        [101, dt.datetime(2026, 1, 16, 10, 5, 0, tzinfo=dt.timezone.utc), 999.0, "BAD_SENSOR_FAULT", 0, 2],
        [101, dt.datetime(2026, 1, 16, 10, 10, 0, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
        # Tag 102 (BR201_PH_PV, is_step_tag=False)
        [102, dt.datetime(2026, 1, 16, 10, 0, 0, tzinfo=dt.timezone.utc), 7.05, "", 192, 0],
        [102, dt.datetime(2026, 1, 16, 10, 10, 0, tzinfo=dt.timezone.utc), 7.01, "", 192, 0],
        # Tag 103 (BR201_AGIT_STATE, is_step_tag=True): 1=LOW for 4 min, 2=HIGH_RUN for 6 min (60% >= 2)
        [103, dt.datetime(2026, 1, 16, 10, 0, 0, tzinfo=dt.timezone.utc), 1.0, "LOW", 192, 0],
        [103, dt.datetime(2026, 1, 16, 10, 4, 0, tzinfo=dt.timezone.utc), 2.0, "HIGH_RUN", 192, 0],
        [103, dt.datetime(2026, 1, 16, 10, 10, 0, tzinfo=dt.timezone.utc), 2.0, "HIGH_RUN", 192, 0],
    ]

    # 2. URS-019 ICH Q1A(R2) MKT Window on Tag 101 (2026-01-16 14:00:00 .. 14:09:00 UTC)
    # 5 samples at 25.0 °C and 5 samples at 30.0 °C (arithmetic mean = 27.5 °C, Arrhenius MKT > 27.5 °C)
    base_mkt = dt.datetime(2026, 1, 16, 14, 0, 0, tzinfo=dt.timezone.utc)
    for i in range(10):
        temp_val = 25.0 if i < 5 else 30.0
        rows.append([101, base_mkt + dt.timedelta(minutes=i), temp_val, "", 192, 0])

    # 3. URS-019 USP <1229> Steam Sterilization F0 Window on Tag 101 (2026-01-16 15:00:00 .. 15:15:00 UTC)
    # 15 minutes held at 121.1 °C -> lethality rate = 1.0 min/min -> cumulative F0 = 15.0 minutes
    base_f0 = dt.datetime(2026, 1, 16, 15, 0, 0, tzinfo=dt.timezone.utc)
    for i in range(16):
        rows.append([101, base_f0 + dt.timedelta(minutes=i), 121.1, "SIP_STERILIZE_HOLD", 192, 0])

    # 5. URS-019 Target Batch Window for Golden Batch Overlay on Tag 101 (2026-01-16 17:00:00 .. 17:10:00 UTC)
    rows.extend(
        [
            [101, dt.datetime(2026, 1, 16, 17, 0, 0, tzinfo=dt.timezone.utc), 37.2, "", 192, 0],
            [101, dt.datetime(2026, 1, 16, 17, 2, 0, tzinfo=dt.timezone.utc), 39.5, "", 192, 0],
            [101, dt.datetime(2026, 1, 16, 17, 10, 0, tzinfo=dt.timezone.utc), 37.4, "", 192, 0],
        ]
    )

    # 6. URS-021 Event Frame TrueFor Backfill Window on Tag 101 (2026-01-16 18:00:00 .. 18:10:00 UTC)
    # Threshold = 39.5 °C, TrueFor = 60s:
    # - 18:01:00 -> 41.2 °C, 18:01:15 -> 37.0 °C (15s transient spike < 60s -> MUST BE SUPPRESSED)
    # - 18:05:00 -> 40.6 °C, 18:06:00 -> 41.4 °C, 18:07:00 -> 40.3 °C, 18:07:30 -> 37.0 °C (120s >= 60s -> CAPTURED)
    rows.extend(
        [
            [101, dt.datetime(2026, 1, 16, 18, 0, 0, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 1, 0, tzinfo=dt.timezone.utc), 41.2, "TRANSIENT_NOISE", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 1, 15, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 5, 0, tzinfo=dt.timezone.utc), 40.6, "SUSTAINED_EXCURSION", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 6, 0, tzinfo=dt.timezone.utc), 41.4, "SUSTAINED_EXCURSION", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 7, 0, tzinfo=dt.timezone.utc), 40.3, "SUSTAINED_EXCURSION", 192, 0],
            [101, dt.datetime(2026, 1, 16, 18, 7, 30, tzinfo=dt.timezone.utc), 37.0, "", 192, 0],
        ]
    )

    ch_client.insert(
        "pi_historian.sensor_data",
        rows,
        column_names=["tag_id", "ts", "val", "str_val", "quality", "status_code"],
    )


def test_oq_13_pi_datalink_and_streamsets_parity(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    URS-018: Verify AVEVA PI DataLink & PI Web API StreamSets parity:
    PICurrVal (/current), PIArcVal (/archive-value), PICompDat (/recorded),
    PIAdvCalcDat (/calculated Time-Weighted vs Event-Weighted), PITimeFilter (/time-filter),
    and Bulk StreamSets (/streamsets/end, /streamsets/interpolated).
    """
    _ensure_pi_parity_oq_dataset(ch_client)

    # 1. PICurrVal (/api/v1/datalink/current) with UOM conversion & Digital State resolution
    curr_temp = api_client.get(
        "/api/v1/datalink/current",
        params={"tag_name": "BR201_TEMP_PV", "target_uom": "degF"},
    )
    assert curr_temp.status_code == 200
    curr_temp_data = curr_temp.json()
    assert curr_temp_data["quality"] >= 192
    assert curr_temp_data["eng_units"] == "degF"
    assert curr_temp_data["val"] > 80.0

    curr_agit = api_client.get(
        "/api/v1/datalink/current",
        params={"tag_name": "BR201_AGIT_STATE"},
    )
    assert curr_agit.status_code == 200
    curr_agit_data = curr_agit.json()
    assert curr_agit_data["is_step_tag"] is True
    assert curr_agit_data["str_val"] in {"OFF", "LOW", "HIGH_RUN"}

    # 2. PIArcVal (/api/v1/datalink/archive-value) — INTERPOLATED, PREVIOUS, NEXT
    arc_lin = api_client.get(
        "/api/v1/datalink/archive-value",
        params={
            "tag_name": "BR201_TEMP_PV",
            "timestamp": "2026-01-16T10:01:00Z",
            "retrieval_mode": "INTERPOLATED",
        },
    )
    assert arc_lin.status_code == 200
    assert arc_lin.json()["val"] == 38.0
    assert arc_lin.json()["applied_interpolation"] == "LINEAR"

    arc_prev = api_client.get(
        "/api/v1/datalink/archive-value",
        params={
            "tag_name": "BR201_TEMP_PV",
            "timestamp": "2026-01-16T10:01:00Z",
            "retrieval_mode": "PREVIOUS",
        },
    )
    assert arc_prev.status_code == 200
    assert arc_prev.json()["val"] == 37.0

    arc_step = api_client.get(
        "/api/v1/datalink/archive-value",
        params={
            "tag_name": "BR201_AGIT_STATE",
            "timestamp": "2026-01-16T10:02:00Z",
            "retrieval_mode": "INTERPOLATED",
        },
    )
    assert arc_step.status_code == 200
    assert arc_step.json()["val"] == 1
    assert arc_step.json()["str_val"] == "LOW"
    assert arc_step.json()["applied_interpolation"] == "LOCF_STEP"

    # 3. PICompDat (/api/v1/datalink/recorded) — excludes quality=0 spike (999.0) by default
    rec_resp = api_client.get(
        "/api/v1/datalink/recorded",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-16T10:00:00Z",
            "end_time": "2026-01-16T10:10:00Z",
            "include_bad_quality": False,
        },
    )
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["point_count"] == 3
    assert [p["val"] for p in rec_data["points"]] == [37.0, 39.0, 37.0]

    # 4. PIAdvCalcDat (/api/v1/datalink/calculated) — TIME_WEIGHTED vs EVENT_WEIGHTED
    calc_tw = api_client.get(
        "/api/v1/datalink/calculated",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-16T10:00:00Z",
            "end_time": "2026-01-16T10:10:00Z",
            "calculation_basis": "TIME_WEIGHTED",
        },
    )
    assert calc_tw.status_code == 200
    tw_summary = calc_tw.json()["summary"]
    assert tw_summary["average"] == 38.0
    assert tw_summary["time_weighted_average"] == 38.0
    assert tw_summary["event_weighted_average"] == 37.6667
    assert tw_summary["percent_good"] == 75.0  # 3 good points out of 4 raw points in window

    calc_ew = api_client.get(
        "/api/v1/datalink/calculated",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-16T10:00:00Z",
            "end_time": "2026-01-16T10:10:00Z",
            "calculation_basis": "EVENT_WEIGHTED",
        },
    )
    assert calc_ew.status_code == 200
    ew_summary = calc_ew.json()["summary"]
    assert ew_summary["average"] == 37.6667

    # 5. PITimeFilter (/api/v1/datalink/time-filter)
    tf_resp = api_client.get(
        "/api/v1/datalink/time-filter",
        params={
            "tag_name": "BR201_AGIT_STATE",
            "start_time": "2026-01-16T10:00:00Z",
            "end_time": "2026-01-16T10:10:00Z",
            "operator": ">=",
            "threshold": 2.0,
        },
    )
    assert tf_resp.status_code == 200
    tf_data = tf_resp.json()
    assert tf_data["true_seconds"] == 360.0
    assert tf_data["percent_true"] == 60.0

    # 6. PI Web API StreamSets (/api/v1/streamsets/end & /api/v1/streamsets/interpolated)
    ss_end = api_client.post(
        "/api/v1/streamsets/end",
        json={"asset_path": "BioCorp.Fremont.USP.Bioreactor_201"},
    )
    assert ss_end.status_code == 200
    assert ss_end.json()["count"] >= 3

    ss_interp = api_client.post(
        "/api/v1/streamsets/interpolated",
        json={
            "tag_names": ["BR201_TEMP_PV", "BR201_AGIT_STATE"],
            "start_time": "2026-01-16T10:00:00Z",
            "end_time": "2026-01-16T10:04:00Z",
            "step_seconds": 120,
        },
    )
    assert ss_interp.status_code == 200
    assert ss_interp.json()["count"] == 2

    # 7. Verify all 8 Excel DataLink UDFs in excel-datalink-client/gxphistorian_datalink_udf.py against live API
    import importlib.util
    import sys
    from conftest import API_BASE_URL, REPO_ROOT

    udf_path = REPO_ROOT / "excel-datalink-client" / "gxphistorian_datalink_udf.py"
    udf_spec = importlib.util.spec_from_file_location("gxphistorian_datalink_udf", udf_path)
    assert udf_spec is not None and udf_spec.loader is not None
    udf_mod = importlib.util.module_from_spec(udf_spec)
    sys.modules["gxphistorian_datalink_udf"] = udf_mod
    udf_spec.loader.exec_module(udf_mod)
    udf_mod.HISTORIAN_API_URL = API_BASE_URL

    udf_sampled = udf_mod.GXPHISTORIAN_SAMPLED("BR201_TEMP_PV", "2026-01-16T10:00:00Z", "2026-01-16T10:02:00Z", 60)
    assert len(udf_sampled) == 4  # header + 3 rows

    udf_plot = udf_mod.GXPHISTORIAN_PLOT_VALUES("BR201_TEMP_PV", "2026-01-16T10:00:00Z", "2026-01-16T10:10:00Z", 10)
    assert len(udf_plot) >= 2

    udf_ef = udf_mod.GXPHISTORIAN_EVENT_SUMMARY("USP_Batch")
    assert len(udf_ef) >= 5

    udf_curr = udf_mod.GXPHISTORIAN_CURRENT_VALUE("BR201_TEMP_PV", "degF")
    assert len(udf_curr) == 2 and udf_curr[1][1] > 80.0

    udf_arc = udf_mod.GXPHISTORIAN_ARCHIVE_VALUE("BR201_TEMP_PV", "2026-01-16T10:01:00Z", "INTERPOLATED")
    assert len(udf_arc) == 2 and udf_arc[1][1] == 38.0

    udf_comp = udf_mod.GXPHISTORIAN_COMPRESSED_DATA("BR201_TEMP_PV", "2026-01-16T10:00:00Z", "2026-01-16T10:10:00Z", 50)
    assert len(udf_comp) == 4  # header + 3 good points

    udf_calc = udf_mod.GXPHISTORIAN_CALCULATED_DATA("BR201_TEMP_PV", "2026-01-16T10:00:00Z", "2026-01-16T10:10:00Z", "TIME_WEIGHTED")
    assert len(udf_calc) == 10 and udf_calc[1][1] == 38.0

    udf_tf = udf_mod.GXPHISTORIAN_TIME_FILTER("BR201_AGIT_STATE", "2026-01-16T10:00:00Z", "2026-01-16T10:10:00Z", ">=", 2.0)
    assert len(udf_tf) == 2 and udf_tf[1][1] == 360.0

    evidence.record(
        assertion_summary=(
            "Verified AVEVA PI DataLink & StreamSets parity (REST + all 8 =GXPHISTORIAN_* Excel UDFs): "
            "PICurrVal UOM/DigitalState resolution, PIArcVal exact linear/LOCF retrieval, PICompDat bad-quality "
            "exclusion, PIAdvCalcDat Time-Weighted (38.0) vs Event-Weighted (37.6667) integration, PITimeFilter "
            "duration (360s / 60%), and StreamSets bulk queries."
        ),
        input_payload={"window": "2026-01-16T10:00:00Z..10:10:00Z", "tags": ["BR201_TEMP_PV", "BR201_AGIT_STATE"]},
        output_payload={
            "pi_arc_val_linear": arc_lin.json(),
            "pi_adv_calc_time_weighted": tw_summary,
            "pi_adv_calc_event_weighted": ew_summary,
            "pi_time_filter": tf_data,
            "streamsets_count": ss_end.json()["count"],
            "verified_excel_udfs": [
                "GXPHISTORIAN_SAMPLED",
                "GXPHISTORIAN_PLOT_VALUES",
                "GXPHISTORIAN_EVENT_SUMMARY",
                "GXPHISTORIAN_CURRENT_VALUE",
                "GXPHISTORIAN_ARCHIVE_VALUE",
                "GXPHISTORIAN_COMPRESSED_DATA",
                "GXPHISTORIAN_CALCULATED_DATA",
                "GXPHISTORIAN_TIME_FILTER",
            ],
        },
    )


def test_oq_14_pi_analytics_mkt_f0_sqc_and_golden_batch(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    URS-019: Verify PI Analysis Service & GxP Calculation Engine:
    ICH Q1A(R2) Mean Kinetic Temperature (MKT), USP <1229> Steam Sterilization F0 Lethality,
    PI SQC Western Electric SPC rules (Cp/Cpk), and PI BatchView Golden Batch overlay.
    """
    _ensure_pi_parity_oq_dataset(ch_client)

    # 1. ICH Q1A(R2) Mean Kinetic Temperature (MKT)
    mkt_resp = api_client.get(
        "/api/v1/analytics/mkt",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-16T14:00:00Z",
            "end_time": "2026-01-16T14:09:00Z",
        },
    )
    assert mkt_resp.status_code == 200
    mkt_data = mkt_resp.json()
    assert mkt_data["good_sample_count"] == 10
    assert mkt_data["arithmetic_mean_c"] == 27.5
    # Arrhenius exponential weighting causes MKT to exceed arithmetic mean when temperature fluctuates
    assert 27.5 < mkt_data["mkt_c"] < 30.0
    assert mkt_data["kinetic_penalty_delta_c"] > 0.0

    # 2. USP <1229> Steam Sterilization Lethality (F0)
    f0_resp = api_client.get(
        "/api/v1/analytics/f0-lethality",
        params={
            "tag_name": "BR201_TEMP_PV",
            "start_time": "2026-01-16T15:00:00Z",
            "end_time": "2026-01-16T15:15:00Z",
            "reference_temp_c": 121.1,
            "z_value_c": 10.0,
            "target_f0_minutes": 12.0,
        },
    )
    assert f0_resp.status_code == 200
    f0_data = f0_resp.json()
    assert f0_data["cumulative_f0_minutes"] == 15.0
    assert f0_data["sterilization_passed"] is True

    # 3. PI SQC / Western Electric SPC Rules (1..4) & Cp/Cpk on CR_ISO7_DP_PV (low_limit=12.5, high_limit=25.0)
    sqc_resp = api_client.get(
        "/api/v1/analytics/sqc",
        params={
            "tag_name": "CR_ISO7_DP_PV",
            "start_time": "2026-01-16T16:00:00Z",
            "end_time": "2026-01-16T16:19:00Z",
        },
    )
    assert sqc_resp.status_code == 200
    sqc_data = sqc_resp.json()
    assert sqc_data["in_statistical_control"] is False
    assert sqc_data["western_electric_violations"]["rule_1_beyond_3sigma_count"] >= 1
    assert sqc_data["capability_indices"]["cp"] is not None
    assert sqc_data["capability_indices"]["cpk"] is not None

    # 4. PI BatchView Golden Batch Relative-Time Overlay
    cmp_resp = api_client.post(
        "/api/v1/batches/compare",
        json={
            "tag_name": "BR201_TEMP_PV",
            "golden_batch": {
                "batch_id": "GOLDEN-BATCH-2026-OQ1",
                "start_time": "2026-01-16T10:00:00Z",
                "end_time": "2026-01-16T10:10:00Z",
            },
            "candidate_batches": [
                {
                    "batch_id": "TARGET-BATCH-2026-OQ2",
                    "start_time": "2026-01-16T17:00:00Z",
                    "end_time": "2026-01-16T17:10:00Z",
                }
            ],
            "duration_seconds": 600,
            "step_seconds": 120,
        },
    )
    assert cmp_resp.status_code == 200
    cmp_data = cmp_resp.json()
    assert len(cmp_data["golden_profile"]) == 6
    cand_cmp = cmp_data["candidate_comparisons"][0]
    assert cand_cmp["max_abs_deviation"] > 0.0
    assert cand_cmp["rmse_vs_golden"] > 0.0

    evidence.record(
        assertion_summary=(
            f"Verified ICH Q1A MKT ({mkt_data['mkt_c']} °C vs 27.5 °C mean), USP <1229> F0 "
            f"({f0_data['cumulative_f0_minutes']} min, PASS), Western Electric SQC Rule 1 detection, "
            f"and PI BatchView relative-time Golden Batch overlay (RMSE={cand_cmp['rmse_vs_golden']})."
        ),
        input_payload={"mkt_window": "14:00..14:09Z", "f0_window": "15:00..15:15Z", "sqc_window": "16:00..16:19Z"},
        output_payload={
            "mkt_result": mkt_data,
            "f0_result": {k: f0_data[k] for k in ("cumulative_f0_minutes", "sterilization_passed", "peak_sterilization_temp_c")},
            "sqc_violations": sqc_data["western_electric_violations"],
            "batch_compare_summary": {
                "batch_id": cand_cmp["batch_id"],
                "rmse_vs_golden": cand_cmp["rmse_vs_golden"],
                "max_abs_deviation": cand_cmp["max_abs_deviation"],
            },
        },
    )


def test_oq_15_pi_af_template_uom_digital_states_and_manual_logger(
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    URS-020: Verify PI Asset Framework Template Auto-Instantiation, Canonical UOM Conversion,
    Digital State Sets, and 21 CFR Part 11 PI Manual Logger with dual-person verification.
    """
    # 1. Canonical UOM Catalog & Conversion
    uom_cat = api_client.get("/api/v1/af/uom")
    assert uom_cat.status_code == 200
    assert "temperature" in uom_cat.json()["uom_classes"]

    conv_temp = api_client.post(
        "/api/v1/af/uom/convert",
        json={"value": 100.0, "from_uom": "degC", "to_uom": "degF"},
    )
    assert conv_temp.status_code == 200
    assert conv_temp.json()["converted_value"] == 212.0

    conv_bad = api_client.post(
        "/api/v1/af/uom/convert",
        json={"value": 100.0, "from_uom": "degC", "to_uom": "psi"},
    )
    assert conv_bad.status_code == 400

    # 2. Digital State Sets Catalog & Creation
    headers = {
        "X-Actor-Id": "operator_01",
        "X-Change-Reason": "OQ Qualification AF Template & Digital State Provisioning",
    }
    ds_resp = api_client.post(
        "/api/v1/af/digital-state-sets",
        headers=headers,
        json={
            "state_set_name": "AUTOCLAVE_DOOR_INTERLOCK",
            "description": "GMP Steam Autoclave Door Safety Interlock States",
            "states_map": {"0": "UNLOCKED", "1": "SEALED_PRESSURIZED", "2": "FAULT_AJAR"},
        },
    )
    assert ds_resp.status_code in (200, 201)
    assert ds_resp.json()["digital_state_set"]["state_set_name"] == "AUTOCLAVE_DOOR_INTERLOCK"

    ds_list = api_client.get("/api/v1/af/digital-state-sets")
    assert ds_list.status_code == 200
    assert ds_list.json()["count"] >= 2

    # 3. PI AF Template Auto-Instantiation
    inst_resp = api_client.post(
        "/api/v1/assets/instantiate-template",
        headers=headers,
        json={
            "template_id": 1,
            "asset_name": "Bioreactor_202",
            "asset_path": "BioCorp.Fremont.USP.Bioreactor_202",
            "tag_prefix": "BR202",
            "source_protocol": "OPC_UA",
            "metadata": {"vessel_volume_L": 2000, "location_room": "Suite-B2"},
        },
    )
    assert inst_resp.status_code in (200, 201)
    inst_data = inst_resp.json()
    assert inst_data["instantiated_tag_count"] == 4
    provisioned_names = {t["tag_name"] for t in inst_data["tags"]}
    assert {"BR202_TEMP_PV", "BR202_PH_PV", "BR202_AGIT_STATE", "BR202_UV280_PV"} == provisioned_names

    # 4. PI Manual Logger — Negative Test (out-of-spec value without dual verifier must fail HTTP 400)
    neg_manual = api_client.post(
        "/api/v1/manual-logger/entries",
        headers={
            "X-Actor-Id": "operator_01",
            "X-Change-Reason": "Offline Mettler Toledo SevenExcellence Benchtop pH Grab Sample",
        },
        json={
            "tag_name": "BR201_PH_PV",
            "sample_ts": "2026-01-16T11:30:00Z",
            "val": 8.25,  # Exceeds high_limit=7.4 without verifier credentials
            "sample_barcode": "VIAL-2026-0042-A",
        },
    )
    assert neg_manual.status_code == 400

    # 5. PI Manual Logger — Positive Test with Dual-Person Electronic Verification
    pos_manual = api_client.post(
        "/api/v1/manual-logger/entries",
        headers={
            "X-Actor-Id": "operator_01",
            "X-Change-Reason": "Offline Benchtop pH Verification Grab Sample for BATCH-2026-0042",
        },
        json={
            "tag_name": "BR201_PH_PV",
            "sample_ts": "2026-01-16T11:30:00Z",
            "val": 7.06,
            "str_val": "BENCHTOP_PH_VERIFIED",
            "sample_barcode": "VIAL-2026-0042-B",
            "verifier_user_id": "qa_approver_01",
            "verifier_password": "QA_Approver_2026!",
            "notes": "Verified against NIST pH 7.00 buffer standard",
        },
    )
    assert pos_manual.status_code in (200, 201)
    manual_data = pos_manual.json()
    assert manual_data["dual_verified"] is True
    assert manual_data["verifier_id"] == "qa_approver_01"
    assert manual_data["clickhouse_status_code"] == 5

    list_manual = api_client.get("/api/v1/manual-logger/entries", params={"tag_name": "BR201_PH_PV"})
    assert list_manual.status_code == 200
    assert list_manual.json()["count"] >= 1

    evidence.record(
        assertion_summary=(
            "Verified UOM conversion (100 °C -> 212 °F), Digital State Set creation & catalog, "
            "PI AF Template auto-instantiation of Bioreactor_202 (4 standard tags), and Part 11 PI Manual Logger "
            "with dual-person verification and ClickHouse archival (status_code=5)."
        ),
        input_payload={"template_id": 1, "asset_path": "BioCorp.Fremont.USP.Bioreactor_202"},
        output_payload={
            "uom_conversion": conv_temp.json(),
            "instantiated_asset": {
                "asset": inst_data["asset"],
                "instantiated_tag_count": inst_data["instantiated_tag_count"],
                "tag_names": sorted(list(provisioned_names)),
            },
            "manual_logger_entry": manual_data,
        },
    )


def test_oq_16_swinging_door_truefor_backfill_multisig_and_notifications(
    ch_client: Any,
    api_client: httpx.Client,
    evidence: EvidenceTracker,
) -> None:
    """
    URS-021: Verify Stage 2 Swinging Door Trending (SDT) slope compression, Event Frame historical
    backfill with TrueFor duration debounce, Multi-Stage Electronic Signatures, and PI Notifications.
    """
    _ensure_pi_parity_oq_dataset(ch_client)

    # 1. Stage 2 Swinging Door Trending (SDT) Compression Evaluation
    base_sdt = dt.datetime(2026, 1, 16, 19, 0, 0, tzinfo=dt.timezone.utc).timestamp()
    sdt_samples = []
    for i in range(20):
        # Collinear temperature ramp 37.0 -> 38.9 °C (slope = 0.1 °C/s)
        sdt_samples.append(
            {
                "ts": base_sdt + float(i),
                "val": round(37.0 + 0.1 * i, 4),
                "quality": 192,
                "status_code": 0,
            }
        )
    # Add a sharp inflection spike at i=20 and return at i=21
    sdt_samples.append({"ts": base_sdt + 20.0, "val": 42.5, "quality": 192, "status_code": 0})
    sdt_samples.append({"ts": base_sdt + 21.0, "val": 38.0, "quality": 192, "status_code": 0})

    sdt_resp = api_client.post(
        "/api/v1/compression/swinging-door-evaluate",
        json={
            "tag_id": 101,
            "exc_dev": 0.02,
            "exc_max": 60.0,
            "comp_dev": 0.15,
            "comp_max": 300.0,
            "is_step_tag": False,
            "samples": sdt_samples,
        },
    )
    assert sdt_resp.status_code == 200
    sdt_data = sdt_resp.json()
    assert sdt_data["raw_sample_count"] == 22
    assert sdt_data["stage2_swinging_door_count"] <= 6
    assert sdt_data["compression_ratio_pct"] >= 70.0
    archived_vals = [p["val"] for p in sdt_data["archived_points"]]
    assert 42.5 in archived_vals  # Exact inflection peak preserved

    # 2. Event Frame Historical Backfill with TrueFor Debounce (suppresses 15s spike, captures 120s excursion)
    headers = {
        "X-Actor-Id": "operator_01",
        "X-Change-Reason": "OQ Qualification Historical Event Frame Backfill with TrueFor=60s",
    }
    bf_resp = api_client.post(
        "/api/v1/event-frames/backfill",
        headers=headers,
        json={
            "tag_name": "BR201_TEMP_PV",
            "template_name": "Temp_Excursion_TrueFor_30s",
            "start_time": "2026-01-16T18:00:00Z",
            "end_time": "2026-01-16T18:10:00Z",
            "trigger_operator": ">",
            "trigger_threshold": 39.5,
            "true_for_seconds": 60,
            "close_hysteresis": 0.3,
            "severity": "CRITICAL",
        },
    )
    assert bf_resp.status_code == 200
    bf_data = bf_resp.json()
    assert bf_data["suppressed_transient_spikes"] >= 1
    assert bf_data["created_event_count"] >= 1
    backfilled_event_id = bf_data["created_event_ids"][0]

    # 3. Multi-Channel PI Notifications (Email, SMS, Mobile Push, Webhook/Teams),
    #    Escalation Teams, Two-Way SMS Acknowledgment & Send-on-Close Recovery
    chan_resp = api_client.get("/api/v1/notifications/channels")
    assert chan_resp.status_code == 200
    chan_catalog = chan_resp.json()
    supported_types = {c["channel_type"] for c in chan_catalog["supported_channels"]}
    assert {"EMAIL", "SMS", "MOBILE_PUSH", "WEBHOOK", "TEAMS_ADAPTIVE_CARD"} <= supported_types
    assert "%Element%" in chan_catalog["substitution_parameters"]
    assert "%TrendUrl%" in chan_catalog["substitution_parameters"]

    rules_resp = api_client.get("/api/v1/notifications/rules")
    assert rules_resp.status_code == 200
    assert rules_resp.json()["count"] >= 4

    # Negative check: PI Notifications requires resend_interval_minutes >= non_repetition_minutes
    bad_rule_resp = api_client.post(
        "/api/v1/notifications/rules",
        headers=headers,
        json={
            "rule_name": "Invalid_Interval_Rule",
            "channel_type": "SMS",
            "target_endpoint": "+14155550101",
            "non_repetition_minutes": 20,
            "resend_interval_minutes": 5,
        },
    )
    assert bad_rule_resp.status_code == 400
    assert "resend_interval_minutes" in bad_rule_resp.text

    # Preview all 4 delivery formats (Email HTML+Text, 160-char GSM-7 SMS, Mobile Push APNs/FCM/PagerDuty, Teams Card)
    prev_resp = api_client.post(
        "/api/v1/notifications/preview",
        json={
            "event_id": backfilled_event_id,
            "notification_phase": "TRIGGER",
            "recipient_email": "qa-compliance@biocorp.internal",
            "recipient_phone_e164": "+14155550101",
            "recipient_mobile_uri": "fcm://device-usp-operator-01",
        },
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["channels"]["sms"]["gsm7_single_segment"] is True
    assert prev_data["channels"]["sms"]["char_count"] <= 160
    assert "Open Ad-Hoc Trend" in prev_data["channels"]["email"]["html_body"]
    assert prev_data["channels"]["mobile_push"]["apns_payload"]["aps"]["interruption-level"] == "critical"
    assert prev_data["channels"]["mobile_push"]["pagerduty_events_v2"]["event_action"] == "trigger"

    # Initial TRIGGER evaluation across WEBHOOK, SMS, MOBILE_PUSH, and EMAIL
    notif_eval = api_client.post(
        "/api/v1/notifications/evaluate",
        params={"event_id": backfilled_event_id},
    )
    assert notif_eval.status_code == 200
    notif_data = notif_eval.json()
    assert notif_data["status"] == "evaluated"
    assert notif_data["dispatched_count"] >= 4
    dispatched_channels = {d["channel_type"] for d in notif_data["deliveries"]}
    assert {"WEBHOOK", "SMS", "MOBILE_PUSH", "EMAIL"} <= dispatched_channels

    # Simulate 15 minutes elapsed without acknowledgment -> triggers Tier 2 Escalation Team dispatches
    esc_eval = api_client.post(
        "/api/v1/notifications/evaluate",
        params={"event_id": backfilled_event_id, "simulate_elapsed_minutes": 15.0},
    )
    assert esc_eval.status_code == 200
    esc_data = esc_eval.json()
    assert esc_data["dispatched_count"] >= 1
    assert all(d["notification_phase"] == "ESCALATION" and d["escalation_tier"] == 2 for d in esc_data["deliveries"])

    # Two-Way SMS Acknowledgment ('ACK <EventShortId> ...') halts further escalations
    short_id = backfilled_event_id.split("-")[0].upper()
    sms_ack_resp = api_client.post(
        "/api/v1/notifications/sms-webhook",
        json={
            "from_phone": "+14155550101",
            "message_body": f"ACK {short_id} Inspected bioreactor jacket cooling valve on floor",
            "gateway_provider": "TWILIO_SMS_WEBHOOK",
        },
    )
    assert sms_ack_resp.status_code == 200
    sms_ack_data = sms_ack_resp.json()
    assert sms_ack_data["status"] == "sms_acknowledged"
    assert sms_ack_data["escalation_halted"] is True

    # Also verify REST / Web / Mobile acknowledgment endpoint (/api/v1/notifications/acknowledge/{event_id})
    rest_ack_resp = api_client.post(
        f"/api/v1/notifications/acknowledge/{backfilled_event_id}",
        headers=headers,
        json={
            "acknowledged_by": "operator_01",
            "acknowledgment_channel": "MOBILE_PUSH",
            "comment": "Confirmed jacket cooling valve reset on mobile HMI",
        },
    )
    assert rest_ack_resp.status_code == 200
    assert rest_ack_resp.json()["status"] == "acknowledged"

    # Simulate 25 minutes elapsed after SMS ACK -> Tier 3 escalation is halted by acknowledgment
    post_ack_eval = api_client.post(
        "/api/v1/notifications/evaluate",
        params={"event_id": backfilled_event_id, "simulate_elapsed_minutes": 25.0},
    )
    assert post_ack_eval.status_code == 200
    assert post_ack_eval.json()["dispatched_count"] == 0
    assert post_ack_eval.json()["halted_by_acknowledgment_count"] >= 1

    # PI "Send on Close" (RECOVERY_CLOSE) notification when Event Frame is closed
    rec_eval = api_client.post(
        "/api/v1/notifications/evaluate",
        params={"event_id": backfilled_event_id, "dispatch_recovery_on_close": True},
    )
    assert rec_eval.status_code == 200
    rec_data = rec_eval.json()
    assert rec_data["dispatched_count"] >= 1
    assert all(d["notification_phase"] == "RECOVERY_CLOSE" for d in rec_data["deliveries"])

    notif_deliv = api_client.get(
        "/api/v1/notifications/deliveries",
        params={"event_id": backfilled_event_id},
    )
    assert notif_deliv.status_code == 200
    assert notif_deliv.json()["count"] >= 8

    # 4. Multi-Stage Electronic Signatures (Stage 1: Production Review -> Stage 2: QA Approval)
    sig1_resp = api_client.post(
        f"/api/v1/event-frames/{backfilled_event_id}/sign",
        json={
            "user_id": "operator_01",
            "password": "Operator_2026!",
            "signature_meaning": "Production Review — Confirmed Jacket Cooling Valve PID Tuning",
            "change_reason": "Stage 1 Production Operator Review of Thermal Excursion",
        },
    )
    assert sig1_resp.status_code == 200

    sig2_resp = api_client.post(
        f"/api/v1/event-frames/{backfilled_event_id}/sign",
        json={
            "user_id": "qa_approver_01",
            "password": "QA_Approver_2026!",
            "signature_meaning": "QA Final Disposition Approval — Batch Released",
            "change_reason": "Stage 2 QA Qualified Person Final Approval",
        },
    )
    assert sig2_resp.status_code == 200

    chain_resp = api_client.get(f"/api/v1/event-frames/{backfilled_event_id}/signatures")
    assert chain_resp.status_code == 200
    chain_data = chain_resp.json()
    assert chain_data["signature_count"] >= 2
    assert chain_data["multi_stage_complete"] is True
    signers = [s["user_id"] for s in chain_data["signatures"]]
    assert "operator_01" in signers
    assert "qa_approver_01" in signers

    # 5. Hybrid Cloud Deployment Blueprints, Edge Fleet Enrollment & TCO Calculator (AWS, Azure & Google Cloud)
    cloud_resp = api_client.get("/api/v1/cloud/hybrid-blueprints")
    assert cloud_resp.status_code == 200
    cloud_data = cloud_resp.json()
    assert set(cloud_data["providers"].keys()) == {"aws", "azure", "gcp"}
    assert set(cloud_data["patterns"].keys()) == {
        "pattern_a_worm_lakehouse",
        "pattern_b_cloud_core",
        "pattern_c_hub_spoke",
    }
    assert "commercial_cloud_editions" in cloud_data
    assert set(cloud_data["commercial_cloud_editions"].keys()) == {
        "cloud_lab_pd",
        "clinical_cgmp_managed",
        "commercial_enterprise_byoc",
        "edge_box_appliance",
    }
    assert "eu_annex11_qta_schedule" in cloud_data

    aws_bp = api_client.get(
        "/api/v1/cloud/hybrid-blueprints",
        params={"provider": "aws", "pattern": "pattern_b_cloud_core"},
    )
    assert aws_bp.status_code == 200
    assert "aws" in aws_bp.json()["providers"]
    assert "<cold_worm_s3>" in aws_bp.json()["providers"]["aws"]["clickhouse_worm_storage_xml"]

    # 6. Cloud Edge Fleet Heartbeat Enrollment (Part 11 Attribution + URS-005 >14-Day WAL Autonomy)
    unattr_hb = api_client.post(
        "/api/v1/cloud/edge-agents/heartbeat",
        json={"agent_id": "edge-fremont-oq-01", "site_path": "BioCorp.Fremont.USP.Bioreactor_201"},
    )
    assert unattr_hb.status_code == 422

    attr_hb = api_client.post(
        "/api/v1/cloud/edge-agents/heartbeat",
        headers={
            "X-Actor-Id": "operator_01",
            "X-Change-Reason": "OQ-16 Purdue L2.5 Edge Box Enrollment & WAL Autonomy Check",
        },
        json={
            "agent_id": "edge-fremont-oq-01",
            "site_path": "BioCorp.Fremont.USP.Bioreactor_201",
            "hardware_model": "Advantech UNO-2484G (512GB pSLC NVMe)",
            "deployment_pattern": "pattern_b_cloud_core",
            "cloud_provider": "aws",
            "wal_buffer_used_gb": 1.25,
            "wal_buffer_capacity_gb": 100.0,
            "active_tag_count": 25000,
            "mtls_cert_days_remaining": 84,
            "wan_link_status": "CONNECTED_MTLS_8443",
        },
    )
    assert attr_hb.status_code == 200
    hb_agent = attr_hb.json()["agent"]
    assert hb_agent["urs_005_14day_autonomy_compliant"] is True
    assert hb_agent["estimated_autonomy_days_remaining"] >= 14.0

    fleet_resp = api_client.get("/api/v1/cloud/edge-agents")
    assert fleet_resp.status_code == 200
    fleet_data = fleet_resp.json()
    assert fleet_data["count"] >= 1
    assert fleet_data["urs_005_all_compliant"] is True

    # 7. Cloud Commercial TCO & AVEVA PI Savings Calculator
    tco_clinical = api_client.get(
        "/api/v1/cloud/tco-calculator",
        params={"active_tags": 25000, "named_users": 50, "site_count": 1, "cloud_provider": "aws"},
    )
    assert tco_clinical.status_code == 200
    tco_c_data = tco_clinical.json()
    assert tco_c_data["recommendation"]["sku_id"] == "GXP-CLOUD-CLINICAL-25K"
    assert tco_c_data["recommendation"]["unlimited_users_included"] is True
    assert tco_c_data["tco_comparison_usd"]["net_customer_savings"]["tco_reduction_pct"] >= 60.0

    tco_byoc = api_client.get(
        "/api/v1/cloud/tco-calculator",
        params={
            "active_tags": 100000,
            "named_users": 150,
            "site_count": 3,
            "deployment_model": "byoc_marketplace",
            "cloud_provider": "azure",
        },
    )
    assert tco_byoc.status_code == 200
    assert tco_byoc.json()["recommendation"]["sku_id"] == "GXP-CLOUD-BYOC-100K"

    evidence.record(
        assertion_summary=(
            f"Verified Stage 2 Swinging Door compression ({sdt_data['compression_ratio_pct']}% reduction), "
            f"Event Frame TrueFor=60s backfill (suppressed {bf_data['suppressed_transient_spikes']} transient spike, "
            f"captured event {backfilled_event_id}), multi-channel PI Notifications (Email HTML, 160-char SMS, "
            f"Mobile Push APNs/FCM/PagerDuty, Webhook/Teams), Tier 2 Escalation Team dispatch, Two-Way SMS ACK "
            f"escalation halt, Send-on-Close recovery, and 2-stage e-signature chain."
        ),
        input_payload={"sdt_raw_samples": len(sdt_samples), "backfill_window": "2026-01-16T18:00:00Z..18:10:00Z"},
        output_payload={
            "swinging_door_summary": {
                "raw_sample_count": sdt_data["raw_sample_count"],
                "stage2_swinging_door_count": sdt_data["stage2_swinging_door_count"],
                "compression_ratio_pct": sdt_data["compression_ratio_pct"],
            },
            "backfill_result": bf_data,
            "signature_chain": chain_data,
            "notifications_multi_channel_summary": {
                "trigger_deliveries": notif_data["dispatched_count"],
                "tier2_escalation_deliveries": esc_data["dispatched_count"],
                "sms_ack_confirmation": sms_ack_data["sms_confirmation_reply"],
                "recovery_close_deliveries": rec_data["dispatched_count"],
            },
        },
    )

