"""Ask the user what they need done."""

from langgraph.types import interrupt

from agent.state import WorkflowState

QUESTION = "What do you need me to do?"


def ask_task(state: WorkflowState) -> WorkflowState:
    """Pause until the user types a task. After an invalid task, say why it was turned down.

    A resumed node reruns from its first line, so nothing before interrupt() may have side effects.
    """
    prompt = {"kind": "task", "question": QUESTION}
    previous = state.get("assessment")
    if previous and previous["verdict"] == "invalid":
        prompt["rejected"] = {"task": state["task"], "reason": previous["reason"]}
    task = interrupt(prompt)
    return {"task": str(task).strip()}
