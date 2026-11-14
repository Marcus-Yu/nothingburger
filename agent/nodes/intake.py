"""Step 0, intake: words to tasks.

With a job in words (state["job"]) and a model available, Claude turns the job into the ordered task list,
the demonstrations to ask for, and any question it cannot settle from the building. Otherwise the task list
comes from a JSON file (state["tasks_file"]). Code checks the model's answer: every anchor and object it
names must exist, and a carrying task must say where the thing goes.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import llm

REPO = Path(__file__).resolve().parents[2]
SKILLS = {
    "twist_out": "unscrew something from a fixture (a bulb from its socket)",
    "twist_in": "screw something into a fixture",
    "wipe": "wipe a surface with a cloth, in strokes, pressing on it",
    "pick": "grasp an object and lift it; set carries true when it must then be taken somewhere",
}

SYSTEM = """You are the intake step of a system that designs a maintenance robot for one building and plans \
its work. A landlord or property manager describes a job in their own words. You turn it into an ordered \
list of tasks that the rest of the system, which is code, will design a robot for.

What you are given: the job as the person wrote it; the building's anchors (the fixtures and surfaces the \
scan or a person has located, each with an id, a kind and a room); the object cards (things the robot can \
handle, with mass and how they are held); and the skills the planner knows.

How to decide:
- Use only anchors, objects and skills from the lists. If the job needs something that is not there (a \
fixture nobody has located, an object with no card, a skill the planner lacks), leave that part out of the \
tasks and say so in `questions`, in plain words the person can act on. Do not stretch a skill or an anchor \
to cover it.
- One task is one skill on one anchor. Changing a bulb is only the unscrewing here (`twist_out`); screwing \
the new one in is `twist_in` on the same anchor, and belongs in the list only if the job asks for a \
replacement.
- Order the tasks the way a sensible person would do them in one visit; carrying something out of the \
building comes last.
- A task that takes its object out of the building has `carries` true and `deliver_to` "way_out".
- `object_mass_kg` is only for when the person states a weight; otherwise null and the card's mass is used.
- `demos` lists the demonstrations a person must record once at home on the real object, because a scan \
cannot say how hard to grip or how a hand moves: a "path" demo for the motion of each distinct chore, and a \
"squeeze" demo wherever grip force matters (anything that can break, slip or tear). Give each a short chore \
name such as "unscrew bulb" and one sentence on what it is for.
- `understood_as` is one sentence restating the job; `steps` is the plan in a few short lines for the \
person to read."""


def _schema(anchor_ids: list, object_ids: list) -> dict:
    task = {
        "type": "object", "additionalProperties": False,
        "required": ["skill", "anchor", "object", "carries", "deliver_to", "object_mass_kg", "demo", "why"],
        "properties": {
            "skill": {"type": "string", "enum": sorted(SKILLS)},
            "anchor": {"type": "string", "enum": anchor_ids},
            "object": {"anyOf": [{"type": "string", "enum": object_ids}, {"type": "null"}]},
            "carries": {"type": "boolean"},
            "deliver_to": {"anyOf": [{"type": "string", "enum": ["way_out"]}, {"type": "null"}]},
            "object_mass_kg": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "demo": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "why": {"type": "string"},
        },
    }
    demo = {"type": "object", "additionalProperties": False, "required": ["chore", "kind", "why"],
            "properties": {"chore": {"type": "string"}, "kind": {"type": "string", "enum": ["path", "squeeze"]},
                           "why": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False,
            "required": ["understood_as", "steps", "tasks", "demos", "questions"],
            "properties": {"understood_as": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
                           "tasks": {"type": "array", "items": task}, "demos": {"type": "array", "items": demo},
                           "questions": {"type": "array", "items": {"type": "string"}}}}


def _cards() -> list:
    out = []
    for p in sorted((REPO / "catalog" / "object").glob("*.json")):
        c = json.loads(p.read_text())
        out.append({k: c.get(k) for k in ("id", "name", "mass_kg", "width_m", "hold")})
    return out


def from_words(job: str, world: dict) -> dict:
    """The model's reading of the job: {"understood_as", "steps", "tasks", "demos", "questions"}, checked."""
    anchors = [{"id": a["id"], "kind": a.get("kind"), "room": a.get("room")} for a in world.get("anchors", [])]
    cards = _cards()
    user = ("The job, as written:\n" + job.strip() + "\n\nAnchors in this building:\n" + json.dumps(anchors, indent=1)
            + "\n\nObject cards:\n" + json.dumps(cards, indent=1) + "\n\nSkills:\n" + json.dumps(SKILLS, indent=1))
    out = llm.ask_json("intake: words to tasks", SYSTEM, user, _schema([a["id"] for a in anchors], [c["id"] for c in cards]))
    known_a, known_o = {a["id"] for a in anchors}, {c["id"] for c in cards}
    tasks = []
    for i, t in enumerate(out["tasks"], 1):
        if t["anchor"] not in known_a or (t["object"] is not None and t["object"] not in known_o) or t["skill"] not in SKILLS:
            out["questions"].append(f"dropped a task the model named with an unknown anchor, object or skill: {t}")
            continue
        task = {"id": f"t{len(tasks) + 1}", "skill": t["skill"], "anchor": t["anchor"], "object": t["object"],
                "demo": t["demo"], "carries": bool(t["carries"]), "why": t["why"]}
        if task["carries"]:
            task["deliver_to"] = t["deliver_to"] or "way_out"
        if t["object_mass_kg"] is not None:
            task["object_mass_kg"] = float(t["object_mass_kg"])
        tasks.append(task)
    return {**out, "tasks": tasks}


def step(state: dict) -> dict:
    """Reads state["job"] (words) or state["tasks_file"]. Writes state["tasks"] and state["intake"]
    ({"source": "model" | "file", and for the model: understood_as, steps, demos, questions, model})."""
    if state.get("job") and llm.available():
        out = from_words(state["job"], state["world"])
        intake = {"source": "model", "model": llm.model(), "job": state["job"],
                  **{k: out[k] for k in ("understood_as", "steps", "demos", "questions")}}
        return {**state, "tasks": out["tasks"], "intake": intake}
    if not state.get("tasks_file"):
        raise ValueError("a job in words needs a model (set ANTHROPIC_API_KEY); otherwise pass a tasks file")
    doc = json.loads(Path(state["tasks_file"]).read_text())
    tasks = doc["tasks"] if isinstance(doc, dict) else doc
    for t in tasks:
        t.setdefault("carries", False)
        t.setdefault("object", None)
    return {**state, "tasks": tasks, "intake": {"source": "file", "file": str(state["tasks_file"])}}
