"""motion: inverse kinematics at a parked base pose, and arm trajectories for a task.

Inputs and outputs are plain dicts and strings in the shapes of `contracts/`; nothing here reads
or writes a run folder. See `ik.py` and `trajectory.py` for how.
"""
from __future__ import annotations

from . import ik, trajectory


def reachable(robot_xml, pose, targets, *, build, payload_kg=0.0, tool_force_z_n=0.0):
    """Can the arm reach every target with the base fixed at `pose` = [x, y, yaw]?

    `targets` is the value of a `reach_targets` requirement (world frame). Returns
    `{"ok", "q", "tip_ratio", "missed", "why"}`: `ok` when every target has a collision-free IK
    solution within 1 cm and 10 degrees and the static tip-over ratio is at least 1.5 at each;
    `q` is the solution for the first target; `tip_ratio` is the worst over the solved targets
    (capped at 99; 0 when none was solved). `tool_force_z_n` is the world's vertical force on the
    tool, positive up."""
    return ik.reachable(robot_xml, pose, targets, build=build, payload_kg=payload_kg, tool_force_z_n=tool_force_z_n)


def retarget(demo, robot, *, build, task, standoff, requirements):
    """One entry of `trajectory.json`'s `tasks` for `task` at `standoff` (an entry of
    `route.json`'s `standoffs`). `robot` is the MJCF string; `q` in every sample is ordered as
    `build["arm_joints"]`. `demo` may be None. A path that cannot be built comes back with a
    `failure` field (`{"segment", "why"}`) and whatever segments were finished; nothing is raised."""
    return trajectory.retarget(demo, robot, build=build, task=task, standoff=standoff, requirements=requirements)
