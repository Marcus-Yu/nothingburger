# contracts/

Owner: Stream A (merges all changes). See AGENTS.md for scope and rules.

One JSON Schema (draft 2020-12) per run file, plus a worked example of each in [`examples/`](examples/). The examples are one run: removing a hallway ceiling bulb in a unit with a 0.71 m doorway and a 2.62 m ceiling, then inspecting the empty socket. They are written by [`examples/make_examples.py`](examples/make_examples.py); edit the values there and rerun it, not the JSON. Changes are posted on the board with both other owners tagged.

```bash
python contracts/validate.py
```

```bash
python contracts/validate.py runs/<run_id>
```

The validator checks each file against its schema, then the rules a schema cannot express: refs resolve, ids agree across files, array shapes match, no uncalibrated force is used to size or deploy a robot, every `design_spec` requirement has a design check, a force band copied next to its `ref` still equals its source, every inspection uses a sensor the robot has, and every value in `verdict.json` matches what `signals.json` gives when its metric is reduced with the program's `aggregate`. Refs into files not in the folder are reported as warnings.

Status: **draft 0.1**, not yet agreed by B and C. Covers planning, capture, design, pathing, programming and the simulated results. `world.json`, `decisions.jsonl` and `replay.json` are not written yet.

## Conventions (all files)

- `robot.xml` (MuJoCo MJCF) is the robot's source file. URDF, the STEP assembly and OpenUSD are generated from it.

- Every file starts with `header`: `schema_version`, `run_id`, `created_at`, `producer`.
- SI units, named in the field: `_m`, `_s`, `_N`, `_kg`, `_rad`. Frames are metres, Z up. `world` is the Matterport scan's frame.
- A derived number is `{value, source}`, where `source.provenance` says where it came from and `source.ref` points at the file and JSON Pointer it came from.
- A force is either `measured_at_home` or `simulated`, never a fact about a building. A force in `N` measured at home must name its `calibration_id`; a `raw_adc` band must name its glove and can only be replayed on that glove.
- Shared types live in [`common.schema.json`](common.schema.json).
- Each step is one primitive skill: navigate, align, reach, grasp, twist, lift, carry, place, release, press_wipe, inspect, retract. An `inspect` step carries an `inspection` (target, sensor, defects to look for, standoff, resolution, what to do on a finding), the same in `requirements.json` and `program.json`. The robot reports findings; it does not decide on its own that a finding is safe.

## The flow, by file

| Stage | File | Written by | What it holds |
| :-- | :-- | :-- | :-- |
| Plan (LLM + user) | [`requirements.json`](requirements.schema.json) | A | each task in the user's words, broken into primitive steps with success criteria; the envelope the robot must fit (`design_spec`), each number traced to the scan, the demo or a default; open questions; the user's approval |
| Capture (Quest) | [`demo.json`](demo.schema.json) | C | 25 WebXR hand joints per hand per frame, relative to the object; the demo cut into skill phases; the glove clock offset |
| | [`grip.json`](grip.schema.json) | C | raw 0–4095 readings per fingertip on the glove clock, newtons if calibrated, and the force band (hold, peak) per phase |
| | [`calibration.json`](calibration.schema.json) **new** | C | one kitchen-scale curve per fingertip sensor, with its valid range |
| Design | [`design.json`](design.schema.json) | A | the catalog card and size for each slot; every hard check with its margin |
| | [`build.json`](build.schema.json) | B | **for manufacturers:** model files, the BOM (MPN, supplier, cost, lead time, STEP file per line, fabrication for made parts), joints and actuators, sensors, mount points with transforms and interfaces, assembly order with checks, what is out of scope |
| Results (sim) | [`signals.json`](signals.schema.json) | B | every metric the program scores, per step, from MuJoCo, with the engine version, timestep, seed and scene hash; inspection findings (defect class, confidence, view, image, location), always marked synthetic in sim |
| | [`verdict.json`](verdict.schema.json) | B | each step's status and postconditions, each sim test and success criterion, scored from `signals.json`; overall pass or fail; failures, with a suggested `design_spec` bound only when the design is at fault |
| Loop | [`constraints.json`](constraints.schema.json) **new** | A | why the last design failed (no route, failed contact run), as a bound on a `design_spec` field |
| Pathing | [`route.json`](route.schema.json) | C | base waypoints, clearance at each passage, a standoff pose per contact step; or why no route exists |
| | [`trajectory.json`](trajectory.schema.json) | B | joint-space motion per step, retargeted from the demo phases, with force targets |
| Program | [`program.json`](program.schema.json) | A | **for deployment (FDE):** each task as skill calls with pre/postconditions (action done vs outcome confirmed) and failure handling; controllers with sim gains and what to retune; safety limits and refusals; sim, bench and site acceptance tests |

How they connect:

```
requirements ──► design ──► build ──► route ──► trajectory ──► program ──► sim (signals, verdict)
     ▲  ▲                               │                                      │
     │  └──── demo + grip (+calibration)│                                      │
     └─────────── constraints ◄─────────┴──────── no route / failed run ◄──────┘
```

Each test and condition in `program.json` names an `aggregate` (max, min, final, mean, count, any) over its step, or over the whole task when no step is given. That is how a verdict value is computed from the signals.

## Deployment report

```bash
python tools/report/deploy_report.py runs/<run_id>
```

This writes `<run>/export/DEPLOY.md` for the engineer programming the robot. It covers the robot's joints and sensors, each task step by step (where it runs, its controller, force band, done and confirmed conditions, timeout and sim result), inspections, forces with where they came from, controllers to retune, safety limits, the acceptance tests with their sim results, bench and site checklists, what is still open, and the sha256 of every contract file. The validator also checks every file a contract names (robot.xml, CAD, map, scene) against its sha256; missing ones are a warning, a wrong hash is an error. Every number comes from a run file. It refuses to write the report for a run that fails validation unless given `--force`, and then opens with the errors. The example is [`examples/export/DEPLOY.md`](examples/export/DEPLOY.md).

When a design is sent back, the failing files are moved to `iterations/<n>/` in the run folder and `constraints.json` points at them.

## Open

- **Example results are made up.** `examples/signals.json` and `verdict.json` are hand-set values, not a MuJoCo run; `sim.api.run` has to produce them for real.
- **BOM sourcing.** Every BOM line in the example is `placeholder`. A line becomes `verified` only with manufacturer, MPN, supplier, price, lead time and date checked; the catalog cards should carry these.
- **`world.json` shape.** It has no schema yet. The examples' refs assume `/rooms/<id>/width_m`, `/rooms/<id>/height_m`, `/passages/narrowest/{width_m,height_m}`, `/floors/<i>/max_step_m` and `/fixtures/<i>/position_m`. Stream C should agree or change them.
- **Demo size.** At 60 Hz a 10 s demo is about 2 MB inline. `hands.frames_file` allows a binary sidecar if that is too big.
- **Inspection sensors in design.** `design_spec` has no sensor field, so `composer.check` must also read the sensors that inspect steps need. The validator already fails a build that lacks one.
- Wiring, fasteners and firmware stay out of scope, as the plan says, and are listed in `build.json.out_of_scope`.
