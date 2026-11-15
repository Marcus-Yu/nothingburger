"""Step 5d, the program: ordered primitives the simulator will run, each citing the requirements it serves.

Claude writes it from the tasks, the route and the arm paths when a model is available; code then checks
it (every leg driven once and in order, every planned piece of arm work present, every cited requirement
real, every force inside its band). A program that fails the check is not used: the rule-built program
takes its place and the model's problems are kept alongside. With no model, the rule-built program is used.
"""
from __future__ import annotations

import json

from .. import llm

PRIMITIVES = {
    "move_base": "drive one leg of the route (set `leg`)",
    "approach": "move the arm from stowed to the start of the work at a standoff",
    "grasp": "close the gripper on the object, holding a force inside `force_n`",
    "twist": "roll the wrist by `turns`, regrasping as planned",
    "wipe": "run the planned strokes, pressing with `press_n`",
    "lift": "raise the held object clear",
    "retreat": "fold the arm back to stowed",
    "place": "set the held object down at the destination",
    "release": "open the gripper",
}

SYSTEM = """You are the program step of a system that has already designed a robot for a building and planned \
its route and arm motions. You write the task program: the ordered list of primitives a simulator will \
execute. Code has done the geometry; your job is to sequence it correctly and say which requirement each \
step serves, so a deployment engineer can read why every step is there.

You are given the tasks, the requirements ledger (each row has an id), the route (numbered legs, numbered \
standoffs) and, for each standoff, the planned arm segments.

Rules the checker enforces, so follow them exactly:
- Drive every leg exactly once, in the order given, with a `move_base` step naming its `leg` number.
- After the leg that arrives at a standoff, emit that standoff's arm work before the next `move_base`: an \
`approach`, then the work, then a `retreat`, each naming the `task` and `standoff` number. Twist work is a \
`grasp` then a `twist` with the planned `turns`. Wipe work is a `wipe` with `press_n`. Pick work is a \
`grasp` then a `lift`.
- A task that carries its object keeps hold of it through the following legs; after the leg that reaches \
the destination, emit `place` then `release` for that task.
- `force_n` on a `grasp` is [low, high] in newtons and must lie inside that task's force_band requirement \
when the ledger has one; when it has none, set `force_n` to null and say in `note` that the grip force is \
not established.
- `requirements` lists ledger ids that the step serves; cite only ids that exist. A `move_base` cites the \
building rows that constrain the base (width, header, step). Use an empty list when nothing applies.
- Fields that do not apply to a primitive are null.
- `note` is one short sentence a field engineer would want at that step: what could go wrong or what the \
number is based on (for instance that a force band was measured at home, or is uncalibrated)."""


def _schema(req_ids: list) -> dict:
    n = lambda t: {"anyOf": [t, {"type": "null"}]}  # noqa: E731
    step = {"type": "object", "additionalProperties": False,
            "required": ["primitive", "task", "leg", "standoff", "force_n", "press_n", "turns", "requirements", "note"],
            "properties": {
                "primitive": {"type": "string", "enum": sorted(PRIMITIVES)},
                "task": n({"type": "string"}), "leg": n({"type": "integer"}), "standoff": n({"type": "integer"}),
                "force_n": n({"type": "array", "items": {"type": "number"}}),
                "press_n": n({"type": "number"}), "turns": n({"type": "number"}),
                "requirements": {"type": "array", "items": {"type": "string", "enum": req_ids} if req_ids else {"type": "string"}},
                "note": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["steps"],
            "properties": {"steps": {"type": "array", "items": step}}}


def _plan(state: dict) -> dict:
    """What both the model and the rule builder work from: legs, standoffs and their arm work, by number."""
    route, traj, reqs = state["route"], state["trajectory"], state["requirements"]["requirements"]
    tasks = {t["id"]: t for t in state["tasks"]}
    rows = {}
    for r in reqs:
        rows.setdefault(r["task"], {})[r["quantity"]] = r
    standoffs = []
    for k, s in enumerate(route["standoffs"]):
        e = next((x for x in traj["tasks"] if x["task"] == s["task"] and x["standoff"] == s["pose"]), None)
        segs = []
        for g in (e or {}).get("segments", []):
            segs.append({k2: v for k2, v in g.items() if k2 != "samples"} | {"seconds": round(g["samples"][-1]["t"] - g["samples"][0]["t"], 1) if g.get("samples") else 0})
        standoffs.append({"standoff": k, "task": s["task"], "skill": tasks[s["task"]]["skill"], "pose": s["pose"],
                          "covers": s.get("covers"), "trajectory": "ok" if e and not e.get("failure") else "missing or failed",
                          "segments": segs})
    legs, nxt = [], {}
    for i, leg in enumerate(route["legs"]):
        arrives = None
        if leg["to"] in tasks:  # the k-th leg to a task arrives at that task's k-th standoff
            mine = [s["standoff"] for s in standoffs if s["task"] == leg["to"]]
            j = nxt.get(leg["to"], 0)
            arrives = mine[j] if j < len(mine) else None
            nxt[leg["to"]] = j + 1
        legs.append({"leg": i, "from": leg["from"], "to": leg["to"], "carrying": bool(leg.get("carrying")),
                     "length_m": leg.get("length_m"), "arrives_at_standoff": arrives})
    return {"tasks": list(tasks.values()), "legs": legs, "standoffs": standoffs, "rows": rows,
            "ledger": [{k: r.get(k) for k in ("id", "task", "quantity", "unit", "source")}
                       | {"value": r["value"] if not isinstance(r["value"], list) or len(r["value"]) <= 2 else f"{len(r['value'])} entries"}
                       for r in reqs]}


def by_rule(plan: dict) -> list:
    """The program built from the plan with no model: correct order, requirement ids from the ledger."""
    rows, steps, held = plan["rows"], [], None
    base = [r["id"] for q, r in rows.get(None, {}).items() if q in ("base_width_max", "stowed_height_max", "step_max")]

    def cite(task, *quantities):
        return [rows[task][q]["id"] for q in quantities if q in rows.get(task, {})]

    def add(primitive, task=None, leg=None, standoff=None, force_n=None, press_n=None, turns=None, requirements=(), note=""):
        steps.append({"primitive": primitive, "task": task, "leg": leg, "standoff": standoff, "force_n": force_n,
                      "press_n": press_n, "turns": turns, "requirements": list(requirements), "note": note})

    for leg in plan["legs"]:
        add("move_base", leg=leg["leg"], requirements=base,
            note=f"{leg['from']} to {leg['to']}" + (", carrying" if leg["carrying"] else ""))
        if held and leg["to"] == "way_out":
            add("place", task=held, note="at the way out")
            add("release", task=held)
            held = None
        k = leg["arrives_at_standoff"]
        if k is None:
            continue
        s = plan["standoffs"][k]
        t, mine = s["task"], rows.get(s["task"], {})
        if s["trajectory"] != "ok":
            continue
        band = mine.get("force_band")
        force = [float(band["value"][0]), float(band["value"][1])] if band else None
        fnote = (f"band from {band['source']}" + ("" if band.get("grip_source") == "glove" else ", uncalibrated")) if band else "grip force not established"
        add("approach", task=t, standoff=k, requirements=cite(t, "reach_targets", "free_floor"))
        work = next((g for g in s["segments"] if g["phase"] == "work"), {})
        if s["skill"] in ("twist_out", "twist_in"):
            add("grasp", task=t, standoff=k, force_n=force, requirements=cite(t, "force_band", "gripper_opening_min"), note=fnote)
            add("twist", task=t, standoff=k, turns=work.get("turns"), requirements=cite(t, "wrist_roll_turns"),
                note=f"{work.get('regrasps', 0)} regrasps planned")
        elif s["skill"] == "wipe":
            press = mine.get("press_force")
            add("wipe", task=t, standoff=k, press_n=float(press["value"]) if press else None, requirements=cite(t, "press_force", "reach_targets"),
                note=(s.get("covers") or "") + (f"; press force is {press['source']}" if press else ""))
        else:
            add("grasp", task=t, standoff=k, force_n=force, requirements=cite(t, "force_band", "gripper_opening_min", "payload"), note=fnote)
            add("lift", task=t, standoff=k, requirements=cite(t, "payload"))
            if next((x for x in plan["tasks"] if x["id"] == t), {}).get("carries"):
                held = t
        add("retreat", task=t, standoff=k)
    return steps


def check(steps: list, plan: dict) -> list:
    """Problems with a program; empty when it is usable."""
    problems, rows = [], plan["rows"]
    ids = {r["id"] for r in plan["ledger"]}
    legs = [s["leg"] for s in steps if s["primitive"] == "move_base"]
    if legs != [leg["leg"] for leg in plan["legs"]]:
        problems.append(f"legs driven {legs}, the route has {[leg['leg'] for leg in plan['legs']]} in that order")
    work_of = {"twist_out": "twist", "twist_in": "twist", "wipe": "wipe"}
    at_leg, seen = -1, {}
    for s in steps:
        if s["primitive"] == "move_base":
            at_leg = s["leg"]
            continue
        for rid in s["requirements"]:
            if rid not in ids:
                problems.append(f"{s['primitive']} cites {rid}, which is not in the ledger")
        k = s["standoff"]
        if k is not None:
            if not (isinstance(k, int) and 0 <= k < len(plan["standoffs"])):
                problems.append(f"{s['primitive']} names standoff {k}, which does not exist")
                continue
            arrived = next((leg["leg"] for leg in plan["legs"] if leg["arrives_at_standoff"] == k), None)
            if arrived != at_leg:
                problems.append(f"{s['primitive']} at standoff {k} comes after leg {at_leg}, but leg {arrived} is the one that arrives there")
            seen.setdefault(k, []).append(s["primitive"])
        if s["primitive"] == "grasp" and s["force_n"] is not None:
            band = rows.get(s["task"], {}).get("force_band")
            lo, hi = (s["force_n"] + [None, None])[:2]
            if band is None:
                problems.append(f"grasp for {s['task']} sets a force, but the ledger has no force_band for it")
            elif lo is None or hi is None or lo > hi or lo < band["value"][0] - 1e-9 or hi > band["value"][1] + 1e-9:
                problems.append(f"grasp for {s['task']} uses {s['force_n']} N, outside the band {band['value']}")
    for st in plan["standoffs"]:
        if st["trajectory"] != "ok":
            continue
        got = seen.get(st["standoff"], [])
        need = ["approach", work_of.get(st["skill"], "grasp"), "retreat"]
        if [p for p in got if p in need] != need:
            problems.append(f"standoff {st['standoff']} ({st['task']}) needs {need} in order, has {got}")
    return problems


def step(state: dict) -> dict:
    """Reads tasks, requirements, route, trajectory. Writes state["program"] (the program.json dict)."""
    plan = _plan(state)
    rule = by_rule(plan)
    program = {"schema": "program/1", "source": "rule", "steps": rule}
    if state.get("use_model") and llm.available():
        try:
            user = json.dumps({k: plan[k] for k in ("tasks", "ledger", "legs", "standoffs")}, indent=1)
            out = llm.ask_json("program: sequence the primitives", SYSTEM, "The plan:\n" + user,
                               _schema(sorted(r["id"] for r in plan["ledger"])))
            problems = check(out["steps"], plan)
            if problems:
                program["model_rejected"] = {"model": llm.model(), "problems": problems}
            else:
                program = {"schema": "program/1", "source": "model", "model": llm.model(), "steps": out["steps"]}
        except llm.ModelStepError as e:
            program["model_rejected"] = {"model": llm.model(), "problems": [str(e)]}
    for n, s in enumerate(program["steps"]):
        s["n"] = n
    return {**state, "program": program}
