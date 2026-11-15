# Robot Design and route view

Two full-screen pages that open after **Design robot**:

1. **Robot Design**: replays how the design agent picked the robot in a recorded run. The catalog's combinations are narrowed by arithmetic, real candidates are built and fail named checks, and the cheapest one with no failed check is assembled stage by stage (Body, Torso, Arm, Hand, Sensors) on a turntable. Drag or arrow keys turn and tilt it. **Deploy** opens the route view.
2. **Route view**: a bird's-eye toy model of the run's building. Each drive replays the planner's search (the cells it expanded, the branches it dropped), then draws the recorded route in gold and drives the robot along it.

Everything shown comes from one run snapshot, `data/<scenario>.json`. Nothing is invented: when the run doesn't record something (a runner-up per slot, alternative routes), the page doesn't show it.

## Run it

```
cd frontend && python3 -m http.server 8001
open http://localhost:8001/robot-design/          # ?scenario=jrr (default)
node --test robot-design/*.test.mjs               # from frontend/
```

## Wiring it into the studio

```js
import { openRobotDesign } from './robot-design/robot-design.js';
openRobotDesign({ scenario: 'jrr', onDeploy: (snap) => {}, onClose: () => {} });
```

Pass `snapshot` instead of `scenario` to hand it a snapshot object directly.

## The data

`data/export.py` writes a snapshot from a gallery run in shaoming's design and pathing workflow. It reads the run, the parts catalog and the planner straight from a git ref with `git archive`, so nothing has to be merged first.

```
.venv/bin/python frontend/robot-design/data/export.py                  # jrr, from origin/claude/workflow-design-pathing-b05d8f
.venv/bin/python frontend/robot-design/data/export.py --ref HEAD --scenario clinic
```

- **Fields:** they are whitelisted, so no LLM outputs, trace links, frames or video make it into the snapshot. The snapshot is stamped with the ref and commit it came from.
- **The route search:** the exporter reruns the ref's own `nav.route.plan` on the run's inputs, with its A* instrumented to record the expansion order and parent tree. If the replay doesn't match the recorded `route.json` leg for leg, it refuses to write. The route the page draws is always the recorded one.
- **Shapes:** the parts are toy shapes sized from the catalog cards (`outline_m`, `retracted_m`, `reach_m`, …). The card meshes aren't committed, and Go2 and Spot use toy proportions.

## Files

| File | What it does |
| :-- | :-- |
| `robot-design.js` | The design page: DOM, timeline, Skip, Deploy |
| `stage.js` | The turntable scene: candidates, failed-part flags, stage-by-stage assembly, 360 finale |
| `parts.js` | The toy robot built from catalog cards, one outline material per stage |
| `plan.js` | Snapshot to stages, recorded checks, funnel, showcase of failed candidates |
| `route.js` | The route view: DOM and timeline |
| `route-stage.js` | The bird's-eye scene: building, search replay, route, robot, north arrow and scale bar |
| `route-plan.js` | Legs grouped into trips, place names, door clearances |
| `drafting.js`, `ui.js` | Shared scene and DOM helpers |
| `robot-design.css` | Styles for both pages, scoped under `.rd` |
| `data/` | `export.py` and the snapshots it writes |
