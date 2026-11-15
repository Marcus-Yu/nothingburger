"""motion.api, traced. Pass-throughs only."""
from __future__ import annotations

import motion.api as _api

from .trace import traced


def _retarget_summary(r):
    n = sum(len(s["samples"]) for s in r["segments"])
    if r.get("failure"):
        return f"{r['task']}: failed in {r['failure']['segment']}: {r['failure']['why']}"
    return f"{r['task']}: {len(r['segments'])} segments, {n} samples, max error {r.get('max_position_error_m')} m"


@traced("motion.reachable", lambda r: f"ok={r['ok']} tip {r['tip_ratio']} missed {r['missed']}")
def reachable(robot_xml, pose, targets, *, build, payload_kg=0.0, tool_force_z_n=0.0, obstacles=None) -> dict:
    return _api.reachable(robot_xml, pose, targets, build=build, payload_kg=payload_kg, tool_force_z_n=tool_force_z_n, obstacles=obstacles)


@traced("motion.retarget", _retarget_summary)
def retarget(demo, robot, *, build, task, standoff, requirements, obstacles=None) -> dict:
    return _api.retarget(demo, robot, build=build, task=task, standoff=standoff, requirements=requirements, obstacles=obstacles)
