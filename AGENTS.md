# AGENTS.md: rules every agent reads

Project: agents that build and deploy robots (a compiler from a job to a robot, simulated in MuJoCo).
Current plan: [`docs/PLAN_REVISED.md`](docs/PLAN_REVISED.md). The design and pathing workflows: [`docs/WORKFLOWS_DESIGN_PATHING.md`](docs/WORKFLOWS_DESIGN_PATHING.md).

## Folders

| Folder | Holds |
| :-- | :-- |
| `agent/` | the LangGraph graph: nodes, prompts, and thin traced wrappers in `tools/` around each module's `api.py` |
| `contracts/` | one schema per run file, plus a hand-written example of each |
| `evals/` | regression scenarios, the answer key, code evaluators |
| `docs/` | plan, pitch, design notes |
| `catalog/` | part cards: spec sheet and MJCF fragment with named mount points |
| `composer/` | design to `robot.xml` and `build.json`; sizing; hard checks |
| `motion/` | demo retargeting, inverse kinematics, arm trajectories |
| `sim/` | scene, executor, force loop, recorder, run checks |
| `world/` | scan to `world.json`; scenario variants |
| `capture/` | Quest recordings to `demo.json` and `grip.json` |
| `nav/` | base route, standoff pose search |
| `web/` | build view, path view, replay, force plot, decision log |
| `runs/` | one folder per run, written by the pipeline; `runs/golden/` is committed |

## Rules

1. Each module exposes one `api.py`. Other code reaches it only through `agent/tools/` or through files in a run folder.
2. A change to a file's shape is made in `contracts/` first, schema and example together.
3. Nothing under `runs/` is edited by hand.

## Contracts

These files in a run folder are the whole interface between modules. Schemas live in `contracts/`, each with a hand-written example.

| File | Written by | Read by |
| :-- | :-- | :-- |
| `world.json` | world | agent, composer, nav, web |
| `demo.json` | capture | agent, motion |
| `grip.json` | capture | agent, composer |
| `requirements.json` | agent | agent, composer |
| `design.json` | agent | composer, web |
| `decisions.jsonl` | agent | web |
| `robot.xml` | composer | motion, sim |
| `build.json` | composer | nav, web |
| `route.json` | nav | agent, motion, sim, web |
| `trajectory.json` | motion | sim, web |
| `program.json` | agent | sim |
| `intake.json` | agent | web |
| `events.jsonl` | agent, as the run goes | web |
| `replay.json` | sim | web |
| `signals.json` | sim | agent, web |
| `verdict.json` | sim | agent, web |

Entry points (signatures are part of the contract):
`world.api.load(scenario)`, `capture.api.latest(kind)`, `composer.api.check(candidate, requirements)`, `composer.api.compose(design)`, `nav.api.plan(world, build)`, `motion.api.retarget(demo, robot)`, `sim.api.run(run_dir)`.

### What each entry point takes and returns

Every argument and return value is a plain dict or list in the shape of the matching file in `contracts/` (`world` is `world.json`, and so on). Functions do not read or write the run folder; the agent does. Extra inputs are keyword-only, so the positional signatures above still hold. Added on 2026-11-14 for the design and pathing workflows (gaps G2, G8, G13 in the workflow doc): `composer.api.candidates`, `composer.api.design`, `nav.api.corridors`, `nav.api.free_floor`, `nav.api.propose`, `motion.api.reachable`.

| Call | Returns |
| :-- | :-- |
| `composer.api.candidates()` | list of `parts` dicts (the eight keys in `design.json`'s `parts`), every valid combination in `catalog/` |
| `composer.api.check(candidate, requirements)` | `{"parts", "feasible": bool, "price_usd", "mass_kg", "checks": [check, ...], "labels": [...]}`; each check as in `contracts/check.schema.json`. Reach here is the envelope check on the composed model (tool pointing up, down or level), not inverse kinematics |
| `composer.api.design(requirements)` | a `design.json` dict: the cheapest feasible candidate, or `{"schema": "design/1", "parts": null, "infeasible": {"binding_checks": [...]}, ...}` |
| `composer.api.compose(design)` | `{"robot_xml": str, "build": dict}`; `robot_xml` is MJCF with absolute mesh paths, `build` is `build.json` |
| `nav.api.corridors(world, tasks)` | `{"corridors": [...], "demands": {"narrowest_m", "narrowest_doorway", "lowest_header_m", "tallest_step_m", "tightest_turn_m", "changes_floor"}}`; corridors as in `requirements.json` |
| `nav.api.free_floor(world, anchor_id, *, radius_m)` | `{"edge_distance_m": float, "side": [x, y], "nearest": [x, y]}`: how close a disc of `radius_m` gets to the anchor's floor projection, and from which side |
| `nav.api.propose(world, build, task, *, requirements, limit=12)` | ranked list of base poses `[x, y, yaw]` for that task: collision-free and connected to the dock |
| `nav.api.plan(world, build, *, requirements, standoffs)` | a `route.json` dict; `standoffs` is the list the agent picked, in `route.json`'s `standoffs` shape |
| `motion.api.reachable(robot_xml, pose, targets, *, build, payload_kg=0.0, tool_force_z_n=0.0, obstacles=None)` | `{"ok": bool, "q": {joint: value}, "tip_ratio": float, "missed": [target index, ...], "why": str}` with the base fixed at `pose`; `targets` as in a `reach_targets` requirement. `obstacles` is `world.json`'s list: no arm link may be inside one (the hand may) |
| `motion.api.retarget(demo, robot, *, build, task, standoff, requirements, obstacles=None)` | one entry of `trajectory.json`'s `tasks`; `robot` is the `robot_xml` string |

Model steps (intake from words, the program) call Claude through `agent/llm.py`; they are off with `--no-model` or no `ANTHROPIC_API_KEY`, and tests never call a model. `python -m web.serve` opens the live run view (see `web/README.md`). `composer.api.design` also takes `on_candidate=`, a progress callback.

Assets (meshes, simulator models) live in `catalog/_assets/`, which is not committed; `catalog/fetch_assets.py` fills it. Validate any run folder with `python contracts/validate.py <run dir>`.
