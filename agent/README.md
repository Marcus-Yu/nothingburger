# agent/

Runs the design and pathing workflows ([`docs/WORKFLOWS_DESIGN_PATHING.md`](../docs/WORKFLOWS_DESIGN_PATHING.md)) end to end: it calls `composer`, `nav` and `motion` and writes a run folder.

```
PYTHONPATH=. python -m agent.run --world contracts/world.example.json --tasks agent/tasks.example.json \
    --demo contracts/demo.example.json --grip contracts/grip.example.json --demo-task t1 --out runs/scratch/example
```

It writes `world.json`, `tasks.json`, `demo.json` and `grip.json` (when given), `requirements.json`, `design.json`, `decisions.jsonl`, `robot.xml`, `build.json`, `route.json`, `trajectory.json`, `program.json`, `intake.json` and `trace.json`, and keeps the model's own plan and notes in `workspace/` (see [the workspace](#the-workspace-a-virtual-file-system)), validates the folder with `contracts/validate.py`, and prints the design, each task's standoff and whether its arm path was built, every `not_assessable` check, and every failure. The exit code is 0 when every file fits its schema. A task that cannot be done is recorded and printed; it does not change the exit code. Tests: `PYTHONPATH=. python -m pytest agent -q`.

## Questions stop the run

With `--job`, intake may have questions for the person (a drop-off place nobody located, an object with no card). The run then stops before anything is designed: it writes `world.json`, `tasks.json` and `intake.json` (with `questions`), emits `awaiting_answers` and a `run_end` with `waiting: true`, prints the questions and exits with code 3. To go on, run the same command again with one of:

- `--answers answers.json`, a list of `{"question", "answer"}`. Intake reads the job again with the answers and may ask something new, which stops the run again.
- `--proceed`. The questions stay in `intake.json` with `proceeded_without_answers: true`.

`intake.json` also has `unmet`: what the person asked for, in the job or in an answer, that the tasks do not do. The planner can only carry an object to the way out, so "put it on the bedside table" lands here, not in a task. The demonstration requests do not stop the run yet.

## Files

| File | Holds |
| :-- | :-- |
| `run.py` | the runner: the steps in order, the run folder, validation, the summary |
| `nodes/intake.py` | step 0: with `--job`, the model turns the words into tasks, demonstrations to ask for and questions; with `--tasks`, the tasks come from a JSON file |
| `nodes/prepass.py` | step 1: corridors, building demands, free floor near each anchor |
| `nodes/ledger.py` | step 2: `requirements.json` |
| `nodes/design.py` | steps 3 and 4: design, compose, `decisions.jsonl` |
| `nodes/pathing.py` | step 5: standoffs, route, arm paths |
| `nodes/program.py` | step 5d: `program.json`, written by the model in the workspace and checked by code, or built by rule |
| `llm.py` | the one door to Claude: `ask_json`, one request or a loop of tool calls and checked revisions |
| `workspace.py` | the virtual file system a model step plans through, and its save and load |
| `observe.py` | the live event log (`events.jsonl`) and LangSmith tracing |
| `tools/composer.py`, `nav.py`, `motion.py` | pass-through wrappers around each module's `api.py`; each call adds `{n, name, seconds, summary}` to the trace in `tools/trace.py` |
| `tasks.example.json` | three jobs on the example world, the bag stated as 1.0 kg |
| `tasks.heavy_bag.json`, `grip.glove.example.json` | the same jobs with the bag at its card mass of 4 kg, and a grip file whose source is `glove`: together they end in an infeasible design |

Nothing outside `tools/` imports `composer`, `nav` or `motion` (a test checks it).

## How the agent works

This is a harness, not a free-running agent. Code owns the order of the steps, every number and every check; the model is called at two points (intake and the program) and whatever it returns is checked by code before it is used. It is not built on LangGraph or on the `deepagents` package, but it takes four of the five ideas a deep agent rests on (all but sub-agents), and this section says where each one lives.

| Idea | Here |
| :-- | :-- |
| A plan the agent keeps and updates | `plan.md` in the workspace: `- [ ]` lines the model writes first and ticks as it goes |
| A file system for context | the workspace (`workspace.py`): the run so far as read-only files, the model's notes as its own files |
| Loops | three, each with a hard stop: tool calls, checked revisions, robot fixes (below) |
| A detailed prompt per step | `SYSTEM` in `nodes/intake.py` and `nodes/program.py`, plus `workspace.GUIDE` |
| Sub-agents | none. One model, one conversation per model step |

### The steps and the shared state

Every step is a plain function `step(state: dict) -> dict` that returns a new state with its keys added; `run.pipeline` calls them in a fixed order. The state is the shared context between steps: `world`, `tasks`, `intake`, `demos` and `grips` (`{task id: file}`), `building`, `requirements`, `design`, `decisions`, `infeasible`, `excluded`, `robot_fixes`, `robot_xml`, `build`, `route`, `trajectory`, `program`, `workspace`. No step reads another step's prompt or conversation. What one model step wants a later one to know goes in the workspace; what code wants a model step to know is mounted there from the state.

Model steps are off with `--no-model`, with no `ANTHROPIC_API_KEY`, or with `AGENT_NO_MODEL` set (the tests set it). Each then takes its rule-based path: tasks from `--tasks`, the program from `program.by_rule`. The model is `AGENT_MODEL` (default `claude-opus-5-5`).

### The workspace, a virtual file system

A long job does not fit in one prompt that the model then has to hold in its head. The program step therefore gets files and four tools (`ls`, `read_file`, `write_file`, `edit_file`) instead of the plan pasted in:

| Path | Written by | Holds |
| :-- | :-- | :-- |
| `run/tasks.json`, `run/requirements.json`, `run/legs.json`, `run/standoffs.json` | code, read-only | the tasks, the ledger rows with their ids, the route's legs by number, each standoff with its planned arm segments |
| `run/design.json`, `run/robot_fixes.json`, `run/intake.json` | code, read-only | the chosen robot and its checks, the designs ruled out and why, how the job was read and the person's answers |
| `plan.md` | the model | what it will do, one `- [ ]` line each, ticked when done |
| `notes/...` | the model | what it worked out: an ordering, a number and where it came from |
| `notes/checker_log.md` | code | every problem the checker found in an earlier answer for this job |

Files from an earlier run can be out of date (answers can change the tasks, a robot fix changes the route), so the prompt tells the model to check them against `run/` before relying on them.

The files live in memory (`state["workspace"] = {"key", "files"}`). Paths are relative; an absolute path, `..`, a hidden name or a write under `run/` is refused, and the refusal goes back to the model as the tool's error. A file holds at most 60,000 characters, the model at most 64 files, and one read returns 400 lines (it reads on with `offset`). The disk is touched only at the end of a run, when the model's own files are written to `<run folder>/workspace/`, and at the start, when they are loaded back. They are loaded only for the same building and the same job (`workspace.key_for`), so a rerun with `--answers`, a rerun after a failure and a rerun after a robot fix all start from the earlier plan and notes, and a different job in the same folder starts empty. The `run/` files are never saved: they are rebuilt from the state each time.

`--no-workspace` (or `AGENT_NO_WORKSPACE`) sends the program step back to one request with the plan in the prompt.

### The loops

| Loop | Where | What goes round | It stops |
| :-- | :-- | :-- | :-- |
| Tool calls | `llm.ask_json(tools=...)` | the model calls workspace tools; every result of a turn goes back in one message | when it answers, or after 40 requests (the step then falls back to the rule) |
| Checked revisions | `llm.ask_json(review=...)` | code checks the answer (`program.check`); the model is shown the problems in the same conversation and answers again | after 2 revisions; the caller checks the last answer itself and uses the rule-built program if it still fails |
| Robot fixes | `run.pipeline` | a design pathing cannot use becomes an exclusion and the design step runs again | after 5; the best attempt is kept |
| Questions | `run.main`, across runs | intake's questions stop the run (exit 3); the person answers and runs again | when intake has nothing left to ask, or with `--proceed` |
| Spare standoffs | `nodes/pathing.py` | an arm path that cannot be built is retried from the next proposed pose | when the proposals run out |

In every loop the model proposes and code decides. A model answer that fails its check is never used: `program.json` then has `source: "rule"` and keeps the model's problems under `model_rejected`. When the model worked in the workspace, `program.json` also has `planning`: `{workspace, files, tool_calls, turns, revisions}`.

### Watching it

`events.jsonl` in the run folder gets one line per event as the run goes. The model's side shows as `llm_start`, `llm_tool` (one per file operation), `llm_review` (one per checked revision), `llm` (the answer and token use) and `workspace` (the files it kept, with their contents). With LangSmith tracing on, the whole loop of a model step is one `llm` run.

### Not here yet

- The workspace loop has been run against a scripted stand-in for the model (`tests/test_workspace.py`), not yet against the live model.
- Intake does not use the workspace: it is still one request. Its result reaches the program step as `run/intake.json`.
- The design workflow in `design_flow/` (LangGraph) has no workspace and shares no state with this pipeline.
- No sub-agents, and no model step chooses a fix in the robot-fix loop; that loop is rules.

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

- The demonstration interrupts, the simulator, and the parts of the failure loop that need it. The robot fix (a design ruled out, back to the design step) runs on pathing failures only, and the only program fix done is the spare standoff.
- `task_yaw_rad` is always 0: the three jobs act on horizontal anchors and `motion` ignores the field. The wipe's stroke direction is fixed in the ledger instead of being chosen with the base pose.
- The hand-to-gripper transform (gap G12) is not applied to the re-anchored demo, and the bulb's unscrew torque is not in the force band's low end (it is on no card).
- The demo's turns are not used (the card's are), as the doc says.

## Known results on the example world

- `motion.reachable` can pass a pose from which `motion.retarget` cannot build a path: at pick poses 0.20 m from the bin (inside the envelope's nearest distance of 0.21 m) `reachable` finds a solution on a random restart, while `retarget` tries 8 single starts and reports "first target: out of reach". Ordering proposals by the envelope keeps the tries off those poses.
- The wipe fails with the cheapest robot. The counter is 0.6 m deep; its far stroke ends are 0.775 m from the nearest place the base can stand, and the arm reaches 0.70 m at that height with the tool down. `composer`'s reach check passes because it measures every target against the free floor of the anchor's own point (0.53 m). On a 0.35 m deep counter the same robot wipes all 13 strokes from 4 standoffs (see the tests).
- The 4 kg bag is infeasible only when the force check can run (`grip.glove.example.json`): the binding check is the bag's payload on the closest candidate (arm 4.9 kg against 3.5 kg; its gripper is rated 1.5 kg). With the uncalibrated example grip the force check is `not_assessable` and a $51,800 robot passes.

## The design workflow (`agent/design_flow/`)

A second LangGraph agent lives in [`design_flow/`](design_flow/README.md): ask for a task, classify it, ask for a headset and glove demonstration, then propose one part per slot on Claude Sonnet. It is what the frontend studio (`frontend/`) talks to through `DesignWorkflow` in `design_flow/api.py`. It shares no code with the pipeline above yet.
