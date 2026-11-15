"""Ask the user to demonstrate the task with the Meta Quest headset and pressure-sensor gloves."""

from langgraph.types import interrupt

from agent.design_flow.skills import SkillStore, chore_name
from agent.design_flow.state import WorkflowState

MESSAGE = "I haven't learned this skill yet. Show me with the Meta Quest headset and the pressure-sensor gloves."

# What each recording needs from the headset: the capture kind to request, and why.
HEADSET = {
    "demo": ("path", "the hand's path: how high, how far and from which side the robot has to reach"),
    "grip": ("squeeze", "how hard to hold it, from the pressure-sensor gloves"),
}


def make_request_demo(store: SkillStore):
    def request_demo(state: WorkflowState) -> WorkflowState:
        """Pause until the missing recordings arrive, then save them so the skill is complete next time.

        Resume with Command(resume={"demo": ..., "grip": ...}) holding every recording in "needs",
        as capture.api.latest() returns them. Their schemas are not frozen, so they are stored as given.
        "demos" lists the headset requests, in the shape the website's "Ask the headset" buttons read.
        """
        assessment = state["assessment"]
        needs = assessment["missing"]
        chore = chore_name(assessment["skill"])
        recordings = interrupt({
            "kind": "demo",
            "task": state["task"],
            "skill": assessment["skill"],
            "message": MESSAGE,
            "needs": needs,
            "demos": [{"chore": chore, "kind": HEADSET[n][0], "why": HEADSET[n][1], "recording": n} for n in needs],
        })
        # Side effects only after interrupt(): a resumed node reruns from its first line.
        store.save(assessment["skill"], recordings)
        return {}

    return request_demo
