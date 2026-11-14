"""Steps 3 and 4: design (enumerate, check, rank: all inside composer) and compose."""
from __future__ import annotations

from .. import observe
from ..tools import composer, viz

SLOTS = ["base", "lift", "arm", "gripper", "lidar", "lidar_mount", "wrist_cam", "ego_cam"]
SLOT_CHECKS = {
    "base": ["doorway", "turn", "steps", "base payload", "tip-over"],
    "lift": ["reach", "door header"],
    "arm": ["reach", "payload", "press", "twist", "tip-over"],
    "gripper": ["opening", "force", "payload"],
    "lidar": ["lidar present"],
    "lidar_mount": ["lidar view"],
    "wrist_cam": ["wrist camera"],
    "ego_cam": ["ego camera"],
}
NOTE = ("composer.api.design returns only the winner: the cheapest candidate that passes every check (price, then "
        "mass). It does not give a price per part or why each other option lost, so price_usd is the whole "
        "robot's and catalog_alternatives lists the slot's other values in composer.api.candidates(), not ranked.")


def decisions(design: dict, candidates: list) -> list:
    """One line per slot for decisions.jsonl."""
    counts = {k: design[k] for k in ("considered", "passed_arithmetic", "composed_and_checked", "feasible") if k in design}
    if design.get("parts") is None:
        inf = design.get("infeasible") or {}
        return [{"step": "design", "slot": None, "chosen": None, "price_usd": None, "infeasible": True,
                 "binding_checks": inf.get("binding_checks", []), "closest_parts": inf.get("closest_parts"),
                 "closest_price_usd": inf.get("closest_price_usd"), "search": counts,
                 "revisit_if": "a requirement behind a binding check changes, or the catalog gains a part that passes it"}]
    parts, out = design["parts"], []
    for slot in SLOTS:
        others = sorted({c[slot] for c in candidates if c[slot] != parts[slot]}, key=str)
        mine = [c for c in design["checks"] if c["check"] in SLOT_CHECKS[slot]]
        reqs = sorted({r for c in mine for r in c.get("requirements", [])})
        out.append({"step": "design", "slot": slot, "chosen": parts[slot], "price_usd": design["price_usd"],
                    "price_scope": "whole robot", "beat": None, "catalog_alternatives": others,
                    "checks": [{k: c.get(k) for k in ("check", "task", "status", "value", "limit", "unit")} for c in mine],
                    "requirements": reqs, "search": counts, "note": NOTE,
                    "revisit_if": ("any of " + ", ".join(reqs) + " changes") if reqs else "the catalog changes"})
    return out


def step(state: dict) -> dict:
    """Reads state["requirements"]. Writes state["design"], ["decisions"], ["infeasible"], and when feasible
    ["robot_xml"] and ["build"]."""
    requirements = state["requirements"]
    shown = set()

    def progress(p: dict) -> None:
        """Each candidate the composer checks becomes an event; one render per distinct carrier."""
        if p["stage"] == "arithmetic":
            observe.emit("candidates", considered=p["considered"], passed_arithmetic=p["passed"], eliminated_by=p["eliminated_by"])
            return
        parts = p["parts"]
        frame, key = None, (parts["base"], parts["lift"], parts["arm"], parts["gripper"])
        if key not in shown and len(shown) < 12 and observe.frame_path.__call__ and observe._events["frames"] is not None:
            shown.add(key)
            try:
                made = composer.compose({"parts": parts, "checks": p["checks"]}, requirements=requirements)
                frame = viz.render(made["robot_xml"], made["build"]["stowed"]["qpos"], "candidate-" + "-".join(key))
            except Exception as e:
                observe.emit("note", text=f"could not draw candidate {key}: {type(e).__name__}: {e}")
        fails = [{"check": c["check"], "task": c.get("task"), "value": c.get("value"), "limit": c.get("limit"), "unit": c.get("unit"),
                  "why": c.get("why")} for c in p["checks"] if c["status"] == "fail"]
        observe.emit("candidate", parts=parts, price_usd=p["price_usd"], mass_kg=p["mass_kg"], feasible=p["feasible"],
                     failed=fails, frame=frame)

    design = composer.design(requirements, on_candidate=progress)
    out = {**state, "design": design, "infeasible": design.get("parts") is None}
    out["decisions"] = decisions(design, [] if out["infeasible"] else composer.candidates())
    if not out["infeasible"]:
        made = composer.compose(design, requirements=requirements)
        out["robot_xml"], out["build"] = made["robot_xml"], made["build"]
        b = made["build"]
        observe.emit("design", parts=design["parts"], price_usd=design["price_usd"], mass_kg=design["mass_kg"],
                     stowed=b["stowed"] | {"qpos": None}, labels=design.get("labels", []),
                     checks=[{k: c.get(k) for k in ("check", "task", "status", "value", "limit", "unit", "why")} for c in design["checks"]],
                     frame=viz.render(made["robot_xml"], b["stowed"]["qpos"], "design-stowed"))
    else:
        observe.emit("infeasible", **(design.get("infeasible") or {}))
    return out
