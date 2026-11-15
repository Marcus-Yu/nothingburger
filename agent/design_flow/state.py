"""State carried through the design workflow. Values are plain dicts so checkpoints stay JSON-like."""

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    world: str  # the space the job is in: the studio's choice at the start, then find_building's
    building: dict[str, Any]  # the building find_building settled on: its database card and how it was found
    task: str  # the user's latest request
    assessment: dict[str, Any]  # verdict, skill, reason, missing: see nodes/classify.py
    design: dict[str, Any]  # what the designer returned: the pipeline's run result, or a RobotDesign
    options: dict[str, Any]  # how the person steered the design search: {"exclude", "require", "max_price_usd"}
