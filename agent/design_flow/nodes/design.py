"""Design the robot for the task from the skill's recorded motion and force.

The designer is a runnable that maps {"task", "demo", "world"?} to a design. By default it is the
design and pathing pipeline (agent/design_flow/pipeline.py), which returns a plain dict; the
one-call Claude designer (llm.make_designer) returns a RobotDesign. Either is stored as a dict.
"""

from langchain_core.runnables import Runnable

from agent.design_flow.skills import SkillStore
from agent.design_flow.state import WorkflowState


def make_design(designer: Runnable, store: SkillStore):
    def design(state: WorkflowState) -> WorkflowState:
        recordings = store.load(state["assessment"]["skill"])
        request = {"task": state["task"], "demo": recordings}
        if state.get("assessment", {}).get("skill"):
            request["skill"] = state["assessment"]["skill"]
        if state.get("world"):
            request["world"] = state["world"]
        proposal = designer.invoke(request)
        return {"design": proposal if isinstance(proposal, dict) else proposal.model_dump()}

    return design
