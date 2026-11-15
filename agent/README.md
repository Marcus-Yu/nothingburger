# agent/

Runs the design and pathing workflows ([`docs/WORKFLOWS_DESIGN_PATHING.md`](../docs/WORKFLOWS_DESIGN_PATHING.md)) end to end: it calls `composer`, `nav` and `motion` and writes a run folder.

```
PYTHONPATH=. python -m agent.run --world contracts/world.example.json --tasks agent/tasks.example.json \
    --demo contracts/demo.example.json --grip contracts/grip.example.json --demo-task t1 --out runs/scratch/example
```

It writes `world.json`, `tasks.json`, `demo.json` and `grip.json` (when given), `requirements.json`, `design.json`, `decisions.jsonl`, `robot.xml`, `build.json`, `route.json`, `trajectory.json` and `trace.json`, validates the folder with `contracts/validate.py`, and prints the design, each task's standoff and whether its arm path was built, every `not_assessable` check, and every failure. The exit code is 0 when every file fits its schema. A task that cannot be done is recorded and printed; it does not change the exit code. Tests: `PYTHONPATH=. python -m pytest agent -q`.

## Questions stop the run

With `--job`, intake may have questions for the person (a drop-off place nobody located, an object with no card). The run then stops before anything is designed: it writes `world.json`, `tasks.json` and `intake.json` (with `questions`), emits `awaiting_answers` and a `run_end` with `waiting: true`, prints the questions and exits with code 3. To go on, run the same command again with one of:

- `--answers answers.json`, a list of `{"question", "answer"}`. Intake reads the job again with the answers and may ask something new, which stops the run again.
- `--proceed`. The questions stay in `intake.json` with `proceeded_without_answers: true`.

`intake.json` also has `unmet`: what the person asked for, in the job or in an answer, that the tasks do not do. The planner can only carry an object to the way out, so "put it on the bedside table" lands here, not in a task. The demonstration requests do not stop the run yet.

## Files

| File | Holds |
| :-- | :-- |
| `run.py` | the runner: the steps in order, the run folder, validation, the summary |
| `nodes/intake.py` | step 0, a stub: the tasks come from a JSON file |
| `nodes/prepass.py` | step 1: corridors, building demands, free floor near each anchor |
| `nodes/ledger.py` | step 2: `requirements.json` |
| `nodes/design.py` | steps 3 and 4: design, compose, `decisions.jsonl` |
| `nodes/pathing.py` | step 5: standoffs, route, arm paths |
| `tools/composer.py`, `nav.py`, `motion.py` | pass-through wrappers around each module's `api.py`; each call adds `{n, name, seconds, summary}` to the trace in `tools/trace.py` |
| `tasks.example.json` | three jobs on the example world, the bag stated as 1.0 kg |
| `tasks.heavy_bag.json`, `grip.glove.example.json` | the same jobs with the bag at its card mass of 4 kg, and a grip file whose source is `glove`: together they end in an infeasible design |

Nothing outside `tools/` imports `composer`, `nav` or `motion` (a test checks it).

## Not a graph yet

There is no LangGraph dependency and no model call. Every step is a plain function `step(state: dict) -> dict` that returns a new state with its keys added, so each can become a graph node as it is; `run.pipeline` is the fixed order the graph will replace. State keys: `world`, `tasks`, `demos` and `grips` (`{task id: file}`), `building`, `requirements`, `design`, `decisions`, `infeasible`, `robot_xml`, `build`, `route`, `trajectory`.

## The tasks file

`{"tasks": [{"id", "skill", "anchor", "object", "demo", "carries", "deliver_to"}]}`. Two optional fields override defaults: `object_mass_kg` (the object card's mass; the payload row's source becomes `user`) and `press_force_n` (the wipe's 10 N default; source `user` instead of `assumed`). `--demo` and `--grip` belong to the one task named by `--demo-task` (gap G7: one demo per run folder).

## What each step decides

**Pre-pass.** `nav.corridors`, then `nav.free_floor` per task anchor. The disc radius is a parameter (`--radius`, default 0.20 m) standing for half the narrowest base width in the catalog. It is not read from the cards: `composer.api` gives part names, not dimensions.

**Ledger.** Building rows (`task: null`): `base_width_max` = narrowest passage less 0.05 m a side; `base_length_max` = the hallway at the tightest turn less 0.05 m at each end; `stowed_height_max` = lowest header less 0.05 m; `step_max`, labelled `assumed` while the world has no mesh. Per task, never merged across tasks:

| Row | Rule |
| :-- | :-- |
| `reach_targets` (world frame) | twist: the anchor point moved out along its normal by half the object's width, tool axis against the normal. Wipe: stroke ends over the anchor's `extent` inset 0.05 m, lanes 0.15 m apart and centred, as a serpentine (targets 2k and 2k+1 are stroke k); lanes step along the extent's longest edge and each stroke runs across it, starting at the free-floor side. Pick: the anchor point, tool axis against the normal |
| `free_floor` | from the pre-pass |
| `gripper_opening_min` | the object's width plus 0.01 m (the demo's two-hand width when it has one) |
| `payload` | the card's mass, or the tasks file's |
| `force_band` | only when a grip file is given for the task. Low: the larger of the demo's minimum and the physics minimum (pinch: 1.5 × m × g / (2 × 0.5); hook: zero). High: the demo's peak. Carries `grip_source` |
| `press_force` | 10 N ± 2 N, `assumed`, unless the tasks file states it |
| `wrist_roll_turns` | the card's turns to remove |

With a demo for the task, it is re-anchored on the fixture frame (origin at the anchor, z along its normal, x horizontal, world Z up; on a horizontal anchor x is world X and the row says `yaw_free`). The row then carries the demo's approach direction in the world frame and a `demo_check` (the hand moves along the tool axis; every work-phase pose is within 0.15 m of a target), and its source is `demo:home+scan`. Without a demo the source is `assumed`. The targets themselves always come from the anchor, so that the first target is the grasp point `motion.retarget` works at.

An empty force band (physics minimum above the demo's peak) goes in `conflicts` with `ask_user` true only for a `glove` source, and no `force_band` row is written, so the design is not rejected on it.

**Design.** `composer.design`, then `composer.compose(design, requirements=...)`. `decisions.jsonl` has one line per slot. The composer returns only the winner, so each line records the chosen part, the whole robot's price (there is no price per part), the checks that slot answers to, and the slot's other catalog values from `composer.candidates()`; `beat` is null and the note says why. An infeasible design gets one line with the binding checks, and pathing is skipped.

**Pathing.** Per task: `nav.propose` (36 poses), ordered so that poses the build's reach envelope rules out go last, then `motion.reachable` on the first 8. The best passing pose by tip ratio is the standoff, the next two are spares. When no pose reaches every target of a wipe, the strokes are covered greedily in order along the surface: propose around the first uncovered stroke (a copy of the world with the anchor moved there, since `nav.propose` rings the anchor point only), take the pose that reaches the longest unbroken run of strokes, repeat; at most 80 reach checks, 3 poses per stroke. Each standoff records `covers_targets`. Then `nav.plan`, then `motion.retarget` per standoff with the ledger cut to that standoff's targets. An arm path that cannot be built is retried from each spare (the route is then planned again). Failures go into `route.json` and `trajectory.json` `failures`; nothing is raised.

## Stubbed or left out

- Intake (words to tasks), the demonstration interrupts, `program.json` (step 5d), the simulator, and the failure loop (program fix, robot fix, back to the ledger). The only program fix done is the spare standoff.
- `task_yaw_rad` is always 0: the three jobs act on horizontal anchors and `motion` ignores the field. The wipe's stroke direction is fixed in the ledger instead of being chosen with the base pose.
- The hand-to-gripper transform (gap G12) is not applied to the re-anchored demo, and the bulb's unscrew torque is not in the force band's low end (it is on no card).
- The demo's turns are not used (the card's are), as the doc says.

## Known results on the example world

- `motion.reachable` can pass a pose from which `motion.retarget` cannot build a path: at pick poses 0.20 m from the bin (inside the envelope's nearest distance of 0.21 m) `reachable` finds a solution on a random restart, while `retarget` tries 8 single starts and reports "first target: out of reach". Ordering proposals by the envelope keeps the tries off those poses.
- The wipe fails with the cheapest robot. The counter is 0.6 m deep; its far stroke ends are 0.775 m from the nearest place the base can stand, and the arm reaches 0.70 m at that height with the tool down. `composer`'s reach check passes because it measures every target against the free floor of the anchor's own point (0.53 m). On a 0.35 m deep counter the same robot wipes all 13 strokes from 4 standoffs (see the tests).
- The 4 kg bag is infeasible only when the force check can run (`grip.glove.example.json`): the binding check is the bag's payload on the closest candidate (arm 4.9 kg against 3.5 kg; its gripper is rated 1.5 kg). With the uncalibrated example grip the force check is `not_assessable` and a $51,800 robot passes.

## The design workflow (`agent/design_flow/`)

A second LangGraph agent lives in [`design_flow/`](design_flow/README.md): ask for a task, classify it, ask for a headset and glove demonstration, then propose one part per slot on Claude Sonnet. It is what the frontend studio (`frontend/`) talks to through `DesignWorkflow` in `design_flow/api.py`. It shares no code with the pipeline above yet.
