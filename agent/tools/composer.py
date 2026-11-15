"""composer.api, traced. Pass-throughs only."""
from __future__ import annotations

import composer.api as _api

from .trace import traced


def _design_summary(d):
    if d.get("parts") is None:
        names = sorted({f"{c['check']}/{c.get('task')}" for c in (d.get("infeasible") or {}).get("binding_checks", [])})
        return f"infeasible; binding: {', '.join(names)}"
    p = d["parts"]
    return f"{p['base']}+{p['lift']}+{p['arm']}+{p['gripper']} ${d['price_usd']} {d['mass_kg']} kg"


@traced("composer.candidates", lambda r: f"{len(r)} candidates")
def candidates() -> list:
    return _api.candidates()


@traced("composer.check", lambda r: f"feasible={r['feasible']} ${r['price_usd']}")
def check(candidate: dict, requirements: dict) -> dict:
    return _api.check(candidate, requirements)


@traced("composer.design", _design_summary)
def design(requirements: dict, *, exhaustive: bool = False, on_candidate=None, exclude=None) -> dict:
    return _api.design(requirements, exhaustive=exhaustive, on_candidate=on_candidate, exclude=exclude)


@traced("composer.compose", lambda r: f"robot.xml {len(r['robot_xml'])} chars; stowed {r['build']['stowed']['width_m']} m wide, "
                                      f"{r['build']['stowed']['height_m']} m tall; {len(r['build']['arm_joints'])} arm joints")
def compose(design: dict, *, requirements: dict | None = None) -> dict:
    return _api.compose(design, requirements=requirements)
