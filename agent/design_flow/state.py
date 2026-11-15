"""State carried through the design workflow. Values are plain dicts so checkpoints stay JSON-like."""

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    world: str  # the studio's space id (web/worlds.json), set when the session starts
    task: str  # the user's latest request
    assessment: dict[str, Any]  # verdict, skill, reason, missing: see nodes/classify.py
    design: dict[str, Any]  # what the designer returned: the pipeline's run result, or a RobotDesign
