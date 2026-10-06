"""Project measured evidence for inference while retaining full stored reports."""
from copy import deepcopy


def report_facts(report):
    if not isinstance(report, dict):
        return report
    return {key:deepcopy(value) for key,value in report.items()
            if key not in {"agent", "measurement_review", "trace", "optimization"}}


def model_input(task, payload):
    return {key:deepcopy(value) for key,value in payload.items()
            if key not in {"context", "user_id", "agent", "trace", "optimization"}}


def model_context(task, context):
    result = deepcopy(context)
    for name in ("latest_report",):
        if name in result:
            result[name] = report_facts(result[name])
    if isinstance(result.get("stored_reports"), list):
        result["stored_reports"] = [report_facts(report) for report in result["stored_reports"]]
    if task != "movement" or "agent_a_observations" not in result:
        return result
    observations = result["agent_a_observations"]
    if not isinstance(observations, dict):
        return result
    kin = observations.get("kinematics")
    if isinstance(kin, dict):
        observations["kinematics"] = {key: kin[key] for key in
            ("status", "coordinate_space", "coordinate_units", "metric_calibrated", "joint_states",
             "motion_evidence", "image_world_angle_disagreement_deg", "fk_endpoint_residuals",
             "persistent_measurement_conflicts",
             "residual_units", "limitations", "tracking_summary", "set_summary") if key in kin}
        summary = observations["kinematics"].get("set_summary")
        if isinstance(summary, dict):
            observations["kinematics"]["set_summary"] = {key:summary[key] for key in
                ("exercise", "frames", "skipped_frames", "start_timestamp_ms", "end_timestamp_ms",
                 "repetitions", "partial_repetitions", "observed_closed_cycles", "counting_observation",
                 "rejected_cycle_diagnostics", "hold_seconds", "angle_range_source", "angle_range_definition",
                 "angle_ranges_deg") if key in summary}
            observations["kinematics"]["set_summary"]["uncertain_cycles"] = summary.get("uncertain_cycles",0)
    review = observations.get("perception_agent")
    if isinstance(review, dict):
        observations["perception_agent"] = {key: review[key] for key in
            ("mode", "decision", "handoff_allowed", "observation_request", "reason", "gate",
             "timestamp_ms", "cache_hit", "reused_from_timestamp_ms") if key in review}
    metrics = observations.get("metrics")
    if isinstance(metrics, dict):
        observations["metrics"] = {key: value for key, value in metrics.items()
                                   if key not in {"joint_angles", "joint_confidences"}}
    return result
