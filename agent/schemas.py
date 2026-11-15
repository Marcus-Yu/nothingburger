"""Structured outputs of the two LLM steps."""

from pydantic import BaseModel, Field

from agent.catalog import BasePart, GripperPart, ReachPart


class TaskAssessment(BaseModel):
    """Whether a request is a robot chore, and which skill it is. Completeness is decided from data, not here."""

    valid: bool = Field(description="True when a household robot could physically do this chore.")
    skill: str = Field(description="snake_case name of the chore, reusing a known skill's name when it is the same chore. Empty when invalid.")
    reason: str = Field(description="One or two sentences for the user: why it can't be done, or the chore restated.")


class BaseChoice(BaseModel):
    part: BasePart
    because: str = Field(description="Why this part fits the task, citing demonstration numbers when given.")
    runner_up: BasePart = Field(description="The best other part for this slot.")


class ReachChoice(BaseModel):
    part: ReachPart
    because: str = Field(description="Why this part fits the task, citing demonstration numbers when given.")
    runner_up: ReachPart = Field(description="The best other part for this slot.")


class GripperChoice(BaseModel):
    part: GripperPart
    because: str = Field(description="Why this part fits the task, citing demonstration numbers when given.")
    runner_up: GripperPart = Field(description="The best other part for this slot.")


class RobotDesign(BaseModel):
    """A proposed robot: one part per slot. Not yet run through the hard checks."""

    base: BaseChoice
    reach: ReachChoice
    gripper: GripperChoice
    summary: str = Field(description="Two or three sentences describing the robot as a whole.")
