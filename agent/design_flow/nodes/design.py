"""Propose a robot for the task from the skill's recorded motion and force: one part per slot."""

from langchain_core.runnables import Runnable

from agent.design_flow.skills import SkillStore
from agent.design_flow.state import WorkflowState


def make_design(designer: Runnable, store: SkillStore):
    """Build the node around a runnable that maps {"task": str, "demo": dict} to a RobotDesign."""

    def design(state: WorkflowState) -> WorkflowState:
        recordings = store.load(state["assessment"]["skill"])
        proposal = designer.invoke({"task": state["task"], "demo": recordings})
        return {"design": proposal.model_dump()}

    return design
