"""The parts the design step may choose from, by slot.

Mirrors the plan's parts catalog (docs/ plan, "The parts catalog and how the agent picks").
Stream B owns catalog/; once its part cards exist, read the names from there instead.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Part:
    name: str
    label: str
    wins_when: str
    loses_when: str


BASES = (
    Part("wheeled_diff_drive", "wheeled, differential drive", "floors are flat and doors are narrow", "the route has a step"),
    Part("legged_quadruped", "legged quadruped", "the route has steps or thresholds", "cost counts: twelve actuators against two"),
)
REACHES = (
    Part("lift_slider", "column lift with telescoping slider", "targets span a large height or sit over furniture", "the tool must reach around an obstacle"),
    Part("arm_articulated", "articulated arm (the 'human arm')", "orientation matters and targets are close", "targets are high or far, because joint torque grows with reach"),
    Part("lift_arm", "column lift carrying an articulated arm", "both span and dexterity are needed", "cost counts: the most actuators and mass"),
)
GRIPPERS = (
    Part("parallel_jaw", "parallel jaw with soft fingers and pad force sensing", "objects are round or fragile and force must stay in a band", "the object must be turned inside the hand"),
    Part("claw", "claw with one moving jaw", "objects are light and rigid", "force must be regulated"),
    Part("dexterous_hand", "dexterous hand", "regrasping or tool use is needed", "cost counts: the most actuators"),
)
SLOTS = {"base": BASES, "reach": REACHES, "gripper": GRIPPERS}

# Literal[("a", "b")] is Literal["a", "b"]: the schema allows exactly the catalog's names.
BasePart = Literal[tuple(p.name for p in BASES)]
ReachPart = Literal[tuple(p.name for p in REACHES)]
GripperPart = Literal[tuple(p.name for p in GRIPPERS)]


def describe() -> str:
    """The catalog as text for the design prompt."""
    lines = []
    for slot, parts in SLOTS.items():
        lines.append(f"{slot}:")
        lines += [f"- {p.name} ({p.label}): wins when {p.wins_when}; loses when {p.loses_when}." for p in parts]
    return "\n".join(lines)
