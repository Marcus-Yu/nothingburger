"""State carried through the design workflow. Values are plain dicts so checkpoints stay JSON-like."""

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    task: str  # the user's latest request
    assessment: dict[str, Any]  # verdict, skill, reason, missing: see nodes/classify.py
    design: dict[str, Any]  # RobotDesign: a proposal, not yet run through the hard checks
