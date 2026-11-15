# web/

The live run view: watch a design and pathing run as it happens, or replay a finished one.

```bash
python -m web.serve        # then open http://127.0.0.1:8010
```

- **Run** starts the agent as a separate process on the example world, with the job typed in the box (or the example task list when "model steps" is off).
- The page shows the robot being designed (a render of each candidate the composer checks, with why it was rejected, then the chosen one, then its reach pose at every standoff), the floor plan with corridors, standoffs and the route, the requirements ledger, the program, and the agent's trace: each step, each tool call, and what the model said.
- A finished run can be replayed or scrubbed with the bar at the bottom. Past runs are in the drop-down.
- `/story.html?run=<run folder>` tells the same run in the order a building's owner asks: what was understood, what the agent needs from them, what the building demands, which robot and why not a cheaper one, each job with where the robot parks, and what is not proven. When a run has stopped for answers, the questions are a form there: sending it starts a new run of the same job in the same building with the answers (`POST /api/run` with `resume`, `answers` and `proceed`), and the stopped run stays as the record of what was asked.
- With LangSmith tracing on, the header links to the same run's trace there.

It reads only a run folder: `events.jsonl` (written by the agent as the run goes; shape in `contracts/events.example.jsonl`) and the PNGs under `frames/` (written when the run is started with `--frames`). `serve.py` binds to 127.0.0.1 only.

The building panel is a picture, not a diagram: with `--frames` the run renders the world file from straight above (`room_view`: walls cut off at 1.1 m, furniture as the world's boxes) and the robot at the dock and at every stop in its reaching pose (`top` on the `design` and `standoff` events). The route, doors and labels are drawn over it in the same floor coordinates. Without frames the panel falls back to the line drawing.

**Watch it work.** With `--frames --walkthrough` the run also writes `frames/walkthrough.mp4`: the robot drives the planned route through the rendered rooms and plays each stop's arm samples from `trajectory.json`, with the camera following and a chapter per leg and motion. It plays positions back; nothing is simulated (no contact, no forces), and it needs `ffmpeg` on the PATH.

**In the real room.** When the world file has a `tour` (a Matterport model id and `to_model`, the 3 x 4 matrix from the world's frame to the scan's), the same run also writes `frames/tour_robot.glb` and `frames/tour_frames.bin`, and the panel links to `tour.html`. That page loads Matterport's SDK bundle from `web/_vendor/matterport` (`python web/fetch_sdk.py`; not committed), adds the robot to the scan's own scene and plays the plan inside the textured scan, with the viewpoint following the robot between the positions the scanner stood at. It needs `MATTERPORT_SDK_KEY` in `.env` and must be opened on `localhost` (the key is refused on `127.0.0.1`). Keys I J K L shift the robot 5 cm and U O turn it 1 degree, to line a traced world up with the scan; the offsets are kept in the address bar.

**The real room as a mesh.** The tour only lets you stand where the scanner stood, and the robot is drawn over a photo. To get a room you can move around in, and to show the real room in the top view and the film, copy the mesh the tour displays:

1. Open `http://localhost:8010/tour.html?run=runs/gallery/jrr&capture=1` and leave it for about four minutes. It flies the camera low over every room and saves each mesh tile and its texture to `world/_scans/<world id>/raw`.
2. Run `python world/scenarios/tools/stitch_scan.py jrr`. It keeps the finest tile everywhere, moves the mesh into the world's frame, writes `world/_scans/jrr/` (pieces for the pictures, `room.glb` for the 3D page) and measures the alignment and the table tops into `world/scenarios/jrr.fit.json`.
3. Run `python world/scenarios/tools/trace_jrr.py` so the world uses those measurements, then run the job again.

After measuring, the stitch cleans the mesh for showing (`world/scenarios/tools/scan_clean.py`; `--as-scanned` skips it):

- **Cleared, keeping the scan.** People, chairs, bags, equipment and things left on tables are taken out. The floor, walls and pillars (columns with scan all the way up) and the stairs stay. In a table's volume, the triangles whose texture is the cloth's colour stay, so the tables are the real draped cloths with the chairs and laptops cut away; a plain sheet in the cloth's colour sits just inside to close the cuts.
- **Dark or torn tables replaced.** A table too deep in shade to brighten cleanly, or with little cloth left, is replaced by a copy of one of the best scanned tables. They are all the same table under the same cloth.
- **Floor evened and mended.** The photos' sun and shade are divided out of the floor up to a limit. Past it (deep shade, tinted sun, marks where things stood, gaps) the boards are copied from a well-lit stretch of the same room's floor. The finished floor picture also lies just under the floor, closing gaps and the cracks between tiles, and each table gets a soft shadow where it meets the floor.
- **Cloths brightened, not flattened.** Each table gets one brightness factor, with sun patches and deep shade on the cloth pulled in, because a cloth's folds are its shading.

This changes the picture only. The planner never saw the chairs and still does not: a robot that drives where a chair stood in the scan is not shown hitting anything.

A world read from a Matterport model by `python -m world.matterport <model id> <name>` gets the same files from the model's own mesh in that one step, with nothing to capture or stitch.

With the mesh on disk, a world that names it (`scan` in `world.json`) is drawn with the real room in the top view and the film, and `room.html?run=...` plays the job inside it: drag to look around, scroll to move, and Enter VR on a headset. Without it everything falls back to drawn boxes. The mesh is for looks only; planning uses the world's `obstacles`. `world/_scans/` is not committed: the mesh is Matterport's, taken from the public tour for this demo, and is not theirs to hand on. The sanctioned source is the scan's MatterPak or splat from its owner.

## Kept runs

`runs/gallery/` holds five finished runs, one per scenario in `world/scenarios/` (data centre, factory cell, senior apartment, clinic, pump house). They are listed first in the page's drop-down and replay without a model or a key, for example `http://127.0.0.1:8010/?run=runs/gallery/datacenter`. To make one again:

```bash
PYTHONPATH=. python -m agent.run --world world/scenarios/clinic.json --job "$(cat world/scenarios/clinic.job.txt)" --proceed --frames --out runs/gallery/clinic
```

### Outdoor runs on Vexcel aerial photos

Five more kept runs happen outside, each on a real lot traced on a Vexcel aerial photo (about 6 cm a pixel):

| Run | Job | Where |
| :-- | :-- | :-- |
| `runs/gallery/lawn_palmetto` | mow a back lawn: 22 lines 0.5 m apart, five of them split round a cluttered patio | Houston |
| `runs/gallery/trash_palmetto` | kitchen trash bag out of the front door, round the parked truck, to the bins at the kerb | Houston |
| `runs/gallery/pooldeck_lakes` | wipe a sun lounger, then carry a towel from the daybed to the clubhouse door | Houston, apartment pool deck |
| `runs/gallery/parcel_eastland` | bring a parcel from the kerb up the driveway to the front door | Houston |
| `runs/gallery/lawn_sanpedro` | mow a fenced lawn, starting and finishing on the patio slab | Los Angeles |

**Planned on the survey, not on a tracing.** A sixth run, `runs/gallery/kerbside_palmetto`, needs the aerial data to plan at all: three
trash bags in front of three Houston houses go to the kerb, and nothing in its world file says where the houses, trees, fences or
parked vehicles are. `aerial_fetch.py <name> --heights` downloads Vexcel's surface model (the top of everything, from the same
flight as the photo) and terrain model; their difference is the height of what stands on the ground, one value per photo pixel
(`world/scenarios/aerial/<name>.height.npz`). A world whose `ground` names that file is planned on it: `nav/grid.py` blocks every
cell standing more than 0.15 m high and anything outside the survey. The survey sees the top of things only, so ground under a
tree's canopy counts as blocked. A pool is flat in the survey, so open water is taken from the photo's colour; that rule is a
rough threshold and has not been checked on a site with a pool in the work area. Only the base's route reads the survey: arm
motion is still checked against the world's obstacle boxes. The work area, the kerb line, the dock and the bags are set by hand
in `aerial_worlds.py`; no obstacle is.

Planned again with the survey taken away, the same stops give a 91.7 m route of which 13.7 m passes through the tree and the
parked vehicles; with it the route is 119.9 m and none does. The film draws the same heights as a surface with the photo over
it, and shows each bag being carried off. One video tells the whole run, from the photo to the robot at the kerb (the height
download needs `tifffile` and `imagecodecs`, which are not project dependencies):

```bash
PYTHONPATH=. python world/scenarios/tools/aerial_story.py runs/gallery/kerbside_palmetto --out docs/media/aerial/kerbside_palmetto-full.mp4
```

Replay one at `http://127.0.0.1:8010/?run=runs/gallery/lawn_palmetto`; the film is `frames/walkthrough.mp4` in each folder
(copies in `docs/media/aerial/`). To make them again:

```bash
python world/scenarios/tools/aerial_worlds.py
```

```bash
for s in lawn_palmetto trash_palmetto pooldeck_lakes parcel_eastland lawn_sanpedro; do PYTHONPATH=. python -m agent.run --world world/scenarios/$s.json --tasks world/scenarios/$s.tasks.json --no-model --frames --walkthrough --out runs/gallery/$s; done
```

How they are built:

- `world/scenarios/tools/aerial_fetch.py <name> <lat> <lon>` downloads the photo and Vexcel's building footprints for a 60 m square
  into `world/scenarios/aerial/` (needs `VEXCEL_API_KEY`; Houston and Los Angeles are covered).
- `world/scenarios/tools/aerial_worlds.py` holds what was read off each photo by eye against a one-metre grid (the lawn's edge, the
  driveway, parked vehicles, loungers) and writes the world, task and job files. A world that has `ground` (the photo and the square
  it covers) is drawn on the photo in the top view and the film; an obstacle marked `"seen": "photo"` is drawn as a faint box, since
  the photo already shows it.
- The photo gives plan positions only. Heights, doors and anything under a roof are assumed, and each world's `source` lists them.
- Mowing is a `navigate` task that carries its own `waypoints` (the ends of each pass, from `nav.api.cover` over a lawn listed in
  the world's `areas`); the route drives them in order and the film marks the ground covered. The catalog has no mowing deck, so
  these runs plan where the base drives and assume the deck.
- The same five lots are spaces in the studio (`frontend/`): `web/worlds.json` lists them, `WORLDS` in
  `agent/design_flow/pipeline.py` maps each to its world file, and `agent/design_flow/jobs.py` turns "mow the lawn" into the
  navigate task. The 3D room page and the route page's floor do not show the photo yet.

## The demo flow site

A second site lives in this folder, served by the Nothingburger backend, not by `web.serve`.

The demo flow as one page: pick a space, state a job, get a plan, film the demonstrations it
asks for, then see the robot and watch it work.

### Run it

The Nothingburger backend serves this folder:

```bash
cd world/pathfinder/backend
uv run python -m uvicorn server.app:app --host 0.0.0.0 --port 8004
```

Open http://localhost:8004/web/. For the demonstration step the headset must reach the same
server: `adb reverse tcp:8004 tcp:8004` over USB.

### The steps

| Step | State | Backed by |
| :-- | :-- | :-- |
| Space selector and 3D tour | works | `worlds.json`, served as `GET /worlds`; the tour is Matterport's public embed |
| 1. The job: repeated-task list, free text, Create plan | works | `POST /plan` |
| 2. The plan | **stand-in** | `make_plan` in `world/pathfinder/backend/server/flow.py` is a lookup table |
| 3. Show it once | works | `POST /demos/request`, then `GET /demos/{id}/read` until the headset uploads |
| 4. The robot | **placeholder** | to read `build.json` and `decisions.jsonl` from a run folder |
| 5. Watch it work | **placeholder** | to replay `replay.json`; in the headset, inside the scan |
| 6. Parts that fit | works with shop keys | `POST /parts/search` (Nothingburger's part search and fit check) |

The default space is Rabinowitz Hall. It is a web tour only: our API key cannot read that model,
so there is no mesh of it for the headset. Add a space by adding an entry to `worlds.json`
(`matterport` is the model id; `site` is the scene package name when one exists).
