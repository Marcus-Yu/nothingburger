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


def make_classify(classifier: Runnable, store: SkillStore):
    """Build the node around a runnable that maps {"task", "known_skills"} to a TaskAssessment."""

    def classify(state: WorkflowState) -> WorkflowState:
        task = state.get("task", "")
        if not task:
            return {"assessment": invalid(NO_TASK)}
        result = classifier.invoke({"task": task, "known_skills": store.names()})
        if not result.valid:
            return {"assessment": invalid(result.reason)}
        try:
            skill = slug(result.skill)
        except ValueError:  # valid but unnamed: treat as unusable rather than guess a folder
            return {"assessment": invalid(result.reason)}
        missing = store.missing(skill)
        verdict = "incomplete" if missing else "complete"
        return {"assessment": {"verdict": verdict, "skill": skill, "reason": result.reason, "missing": missing}}

    return classify


def route(state: WorkflowState) -> Literal["ask_task", "design", "request_demo"]:
    return NEXT_STEP[state["assessment"]["verdict"]]
