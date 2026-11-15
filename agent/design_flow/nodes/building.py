"""Which building the job is in: named in the job, chosen in the studio, or asked for.

The person may name the building in the job ("wipe the kitchen table at 917 Main St unit 506"); that wins
over the space the studio has open. Several close matches in the 3D database are settled by SubQ Snap.
With nothing named, the studio's space is used; with no space either, the step pauses and asks. A building
with no world yet is read from Matterport (world/matterport.py) before classify checks the job against it.
"""

from langgraph.types import interrupt

from agent.design_flow.state import WorkflowState


def make_find_building(resolve, load, get, space_id):
    """`resolve(text, studio_space)`, `load(sid)`, `get(sid)` and `space_id(sid)` come from buildings.py;
    tests pass stand-ins."""

    def find_building(state: WorkflowState) -> WorkflowState:
        task = state.get("task", "")
        found = resolve(task, state.get("world"))
        while "ask" in found:
            # Resume with {"sid": ...} (a candidate clicked) or text (an address or a name typed).
            reply = interrupt({"kind": "building", "task": task, "question": found["ask"], "candidates": found["candidates"]})
            if isinstance(reply, dict) and reply.get("sid") and get(reply["sid"]):
                card = get(reply["sid"])
                found = {"space": space_id(card["sid"]), "building": card, "how": "chosen by you"}
            else:
                found = resolve(str(reply or ""), None)
                if "ask" not in found:
                    found["how"] = "told by you"
        card = dict(found["building"])
        if card.get("sid") and not card.get("loaded"):  # after every pause: a resumed node reruns from the top
            card["scenario"] = load(card["sid"])
            card["loaded"] = True
        return {"world": found["space"], "building": {**card, "how": found["how"]}}

    return find_building
