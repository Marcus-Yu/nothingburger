# motion/

Inverse kinematics at a parked base pose, and arm trajectories for a task. Exposes `api.py`:

- `reachable(robot_xml, pose, targets, *, build, payload_kg=0.0, tool_force_z_n=0.0)`: IK over `build["arm_joints"]` with the base fixed at `pose`, the self-collision test, and the static tip-over ratio. `tool_force_z_n` is the world's vertical force on the tool, positive up.
- `retarget(demo, robot, *, build, task, standoff, requirements)`: one entry of `trajectory.json`'s `tasks`: approach, work, retreat. `q` is ordered as `build["arm_joints"]`.

Files: `ik.py` (damped-least-squares solver, collision test, tip-over), `trajectory.py` (segments by skill). The solver is our own on MuJoCo's Jacobian; mink is not used.

Beyond the schema, a segment may carry `events` (`[{"t", "gripper": "open" | "close"}]`), `transit: "joint"` (the stowed end of the segment is a joint-space move), and per kind: `turns`, `regrasps`, `direction`, `roll_joint` (twist); `strokes`, `press_force_n` (wipe); `lift_m` (pick).

Tests: `python -m pytest motion -q`. The two robots in `tests/fixtures/` were composed by the prototype kit and baked by `tests/fixtures/make_fixtures.py`, which replaces each mesh with its convex hull inline so the MJCF needs no asset files.
