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
| `replay.json` | sim | web |
| `signals.json` | sim | agent, web |
| `verdict.json` | sim | agent, web |

Entry points (signatures are part of the contract):
`world.api.load(scenario)`, `capture.api.latest(kind)`, `composer.api.check(candidate, requirements)`, `composer.api.compose(design)`, `nav.api.plan(world, build)`, `motion.api.retarget(demo, robot)`, `sim.api.run(run_dir)`.
