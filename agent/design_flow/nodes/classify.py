"""Sort a task into invalid, complete or incomplete, and route on the verdict.

Claude decides whether the request is a robot chore and which skill it is. Whether the skill is
complete is a lookup: it is complete once the store has every recording for it.
"""

from typing import Literal

from langchain_core.runnables import Runnable

from agent.design_flow.skills import SkillStore, slug
from agent.design_flow.state import WorkflowState

NO_TASK = "I didn't get a task. Tell me what you need done."
NEXT_STEP = {"invalid": "ask_task", "complete": "design", "incomplete": "request_demo"}


def invalid(reason: str) -> dict:
    return {"verdict": "invalid", "skill": "", "reason": reason, "missing": []}


def make_classify(classifier: Runnable, store: SkillStore, can_plan=None):
    """`can_plan(skill, task, world) -> reason | None`, when given, turns a chore down before any demo is
    asked for if it can't be planned in this space (no fixture to work on, a skill the robot lacks)."""
    """Build the node around a runnable that maps {"task", "known_skills"} to a TaskAssessment."""

    def classify(state: WorkflowState) -> WorkflowState:
        task = state.get("task", "")
        if not task:
            return {"assessment": invalid(NO_TASK)}
        result = classifier.invoke({"task": task, "known_skills": store.names()})
        if not result.valid:
            return {"assessment": invalid(result.reason) | ({"decided_by": result._decided_by} if getattr(result, "_decided_by", "") else {})}
        try:
            skill = slug(result.skill)
        except ValueError:  # valid but unnamed: treat as unusable rather than guess a folder
            return {"assessment": invalid(result.reason)}
        why_not = can_plan(skill, task, state.get("world")) if can_plan else None
        if why_not:
            return {"assessment": invalid(why_not) | ({"decided_by": result._decided_by} if getattr(result, "_decided_by", "") else {})}
        missing = store.missing(skill)
        verdict = "incomplete" if missing else "complete"
        assessment = {"verdict": verdict, "skill": skill, "reason": result.reason, "missing": missing}
        if getattr(result, "_decided_by", ""):
            assessment["decided_by"] = result._decided_by
        return {"assessment": assessment}

    return classify


def route(state: WorkflowState) -> Literal["ask_task", "design", "request_demo"]:
    return NEXT_STEP[state["assessment"]["verdict"]]
