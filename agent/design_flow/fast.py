"""The classify step on two models: SubQ Snap 1.2 decides fast, Claude Sonnet handles what Snap can't.

Snap is a decision model (POST https://api.subq.ai/v1/systemone): it answers yes/no and choice questions
in about 0.2 s and writes no text. It answers two questions about the task:

    is_chore  (yes/no)  is this a physical chore the robot could do in a building?
    skill     (choice)  which skill is it: one already learned, a common chore, or "other"?

    clearly not a chore          -> rejected by Snap
    a chore and a confident pick -> that skill, by Snap
    anything else                -> Sonnet (the slow classifier), which can also name a new skill

Without SUBQ_API_KEY, or when Snap errors, every task goes to Sonnet. Without a slow classifier, what
Snap can't settle is turned down with a reason instead of guessed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from langchain_core.runnables import Runnable, RunnableLambda

from agent.design_flow.schemas import TaskAssessment

SNAP_URL = "https://api.subq.ai/v1/systemone"
SNAP_MODEL = "subq-snap-1.2"
ACCEPT = 0.8   # is_chore probability and skill confidence Snap needs to decide on its own
REJECT = 0.2   # below this is_chore probability Snap turns the task down

# Common chores Snap can pick even before they are learned: skill name -> what it means.
SEED_SKILLS = {
    "wipe_table": "Wipe or clean a table, desk or counter",
    "move_bin": "Pick something up and carry it somewhere else",
    "take_out_garbage": "Take a trash bag or bin out",
    "change_bulb": "Change or check a light bulb",
    "open_box": "Open a box, lid, drawer or door",
    "mow_lawn": "Mow a lawn or cut grass",
}
OTHER = "other"
NOT_A_CHORE = "That doesn't sound like a physical chore a robot could do here."
NOT_KNOWN = "It sounds like a chore, but not one I know yet."


class SnapError(RuntimeError):
    pass


def snap_decide(task: str, options: dict[str, str | None], timeout: float = 15.0) -> dict:
    """Ask Snap the two questions; returns {"chore": p, "skill": name, "confidence": c, "seconds": s}."""
    key = os.environ.get("SUBQ_API_KEY")
    if not key:
        raise SnapError("SUBQ_API_KEY is not set")
    body = {"model": SNAP_MODEL, "state": task, "questions": {
        "is_chore": {"type": "noul",
                     "instructions": "Is this a physical chore a mobile robot with one arm and a gripper could do inside a building "
                                     "or outside on its grounds (a lawn, a driveway, a pool deck)?",
                     "criteria": {"true": "A physical task on objects, surfaces or ground, in a building or on its grounds",
                                  "false": "Not physical, not a chore, or unsafe"}},
        "skill": {"type": "choice", "instructions": "Which skill is this chore?", "criteria": options},
    }}
    req = urllib.request.Request(SNAP_URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise SnapError(f"Snap answered HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SnapError(f"Snap could not be reached: {e}") from e
    a = out["answers"]
    return {"chore": a["is_chore"]["noul"], "skill": a["skill"]["choice"], "confidence": a["skill"]["confidence"],
            "seconds": round(time.perf_counter() - t0, 2)}


def _options(known: list[str]) -> dict[str, str | None]:
    options = {s: SEED_SKILLS.get(s) for s in known}
    for s, d in SEED_SKILLS.items():
        options.setdefault(s, d)
    options[OTHER] = "None of these"
    return dict(list(options.items())[-254:])  # Snap takes at most 255 options


def _mark(result: TaskAssessment, by: str) -> TaskAssessment:
    result._decided_by = by
    return result


def make_mixed_classifier(slow: Runnable | None, decide=snap_decide, slow_label: str = "Claude Sonnet") -> Runnable:
    """{"task", "known_skills"} -> TaskAssessment, Snap first and `slow` (Sonnet) when Snap can't settle it."""

    def classify(request: dict) -> TaskAssessment:
        task = request["task"]
        try:
            d = decide(task, _options(request.get("known_skills") or []))
        except SnapError as e:
            if slow is None:
                raise
            return _mark(slow.invoke(request), f"{slow_label} (Snap unavailable: {e})")
        snap = f"SubQ Snap 1.2 in {d['seconds']} s"
        if d["chore"] < REJECT:
            return _mark(TaskAssessment(valid=False, skill="", reason=NOT_A_CHORE), snap)
        if d["chore"] >= ACCEPT and d["skill"] != OTHER and d["confidence"] >= ACCEPT:
            reason = SEED_SKILLS.get(d["skill"]) or d["skill"].replace("_", " ").capitalize()
            return _mark(TaskAssessment(valid=True, skill=d["skill"], reason=f"{reason}."), snap)
        if slow is None:
            return _mark(TaskAssessment(valid=False, skill="", reason=NOT_KNOWN), snap)
        return _mark(slow.invoke(request), f"{slow_label} (Snap unsure: chore {d['chore']:.2f}, {d['skill']} {d['confidence']:.2f})")

    return RunnableLambda(classify, name="classify: SubQ Snap then Claude Sonnet")
