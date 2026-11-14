# composer/

A design to `robot.xml` and `build.json`; choosing sizes; the hard checks. One door: `api.py`.

| Call | Does |
| :-- | :-- |
| `candidates()` | every valid combination of the cards in `catalog/` (2550 today) |
| `check(candidate, requirements)` | every check on one candidate; each is `pass`, `fail` or `not_assessable` with its number, its limit and the requirement ids it read |
| `design(requirements, *, exhaustive=False)` | the cheapest candidate that passes (price, then mass), or the infeasible form with the binding checks |
| `compose(design, *, requirements=None)` | MJCF text with absolute mesh paths, and the `build.json` dict |

Needs `catalog/_assets` (`python catalog/fetch_assets.py`). Tests: `PYTHONPATH=. python -m pytest composer -q`.

## Files

| File | Holds |
| :-- | :-- |
| `parts.py` | reads the cards; valid combinations; price; mass; a legged base's outline and feet, read from its model |
| `model.py` | composition with MuJoCo's `MjSpec`; the stowed pose; the reach envelope; static tip-over; the lidar's view |
| `checks.py` | the checks: `arithmetic` (cards only) and `measured` (on the composed model) |
| `design.py` | enumerate, drop on the arithmetic, compose cheapest first, stop at the first that passes |
| `build.py` | the `build.json` dict and the MJCF text |

## What the checks do

Limits come only from the ledger, which already holds the margins (0.05 m a side, 0.05 m under the header), so none is added here. Building checks have `task: null`; the rest run once per task.

| Check | Number | Limit (ledger quantity) |
| :-- | :-- | :-- |
| doorway | width of the robot with the arm stowed | `base_width_max` |
| turn | stowed length; a holonomic base passes and says so | `base_length_max` |
| door header | height with the lift down and the arm stowed | `stowed_height_max` |
| steps | the base's step limit | `step_max` |
| base payload | everything the base carries plus the heaviest object | the base card's rating |
| lidar present | present, and 3D when `step_max` > 0.02 m | |
| lidar view | share of the circle seen past the robot's own body, by ray casting | 0.75 |
| wrist camera | present when any task grasps | |
| ego camera | present | |
| reach | farthest the tool gets at the target's height, from the envelope | the nearest the base can stand (`free_floor` + half the base) |
| tip-over | holding moment over tipping moment, worst support edge, with `payload` and `press_force` | 1.5 |
| payload | object + gripper + wrist camera on the arm; object on the gripper | card ratings |
| opening | gripper stroke | `gripper_opening_min` |
| force | the gripper's force range must overlap `force_band`; `not_assessable` unless `grip_source` is `glove` | |
| press | `not_assessable` while the row's source is `assumed`; otherwise arm payload rating × g (assumed) | `press_force` + tolerance |
| twist | the last joint's range in turns; passes with a regrasp count when shorter; fails only with no roll joint along the tool | `wrist_roll_turns` |

A per-task check appears when its row is in the ledger. When a task's skill calls for a row that is missing (a pick with no payload), the check is `not_assessable` and says which row; nothing is filled in from object cards. `not_assessable` never rejects a candidate; it becomes a label such as `force not verified: t3`.

**Reach is an envelope lookup, not inverse kinematics.** The envelope is sampled from the composed model: draw joint values, turn the wrist until the tool points straight up (or down), drop poses with the arm in the floor, the base or the lift, and record the tool's height and distance from the base centre on a 0.05 m grid. A target passes when the tool can be at its height at a distance the free floor allows. Targets whose tool axis is more than 30° from vertical are `not_assessable`. Floors are taken to be at z = 0.

**Tip-over** is run at the envelope pose nearest the base for each target, and in the stowed pose when the task carries something or has no target. Static only: no braking term.

## Assumed or simplified

- Lift geometry is two boxes; lidars are cylinders.
- A legged base stands still in its `home` stance and is treated as non-holonomic.
- The envelope is sampled, so it is slightly smaller than the truth at its edges, and it assumes no hole between its nearest and farthest distance.
- The gripper's force resolution and the arm's push force are not on any card.
- `design` stops at the first survivor that passes, so it reports `composed_and_checked`, not how many are feasible. `exhaustive=True` checks every survivor and adds `feasible` (about 30 s for the example).
