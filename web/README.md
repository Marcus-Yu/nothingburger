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

With the mesh on disk, a world that names it (`scan` in `world.json`) is drawn with the real room in the top view and the film, and `room.html?run=...` plays the job inside it: drag to look around, scroll to move, and Enter VR on a headset. Without it everything falls back to drawn boxes. The mesh is for looks only; planning uses the world's `obstacles`. `world/_scans/` is not committed: the mesh is Matterport's, taken from the public tour for this demo, and is not theirs to hand on. The sanctioned source is the scan's MatterPak or splat from its owner.

## Kept runs

`runs/gallery/` holds five finished runs, one per scenario in `world/scenarios/` (data centre, factory cell, senior apartment, clinic, pump house). They are listed first in the page's drop-down and replay without a model or a key, for example `http://127.0.0.1:8010/?run=runs/gallery/datacenter`. To make one again:

```bash
PYTHONPATH=. python -m agent.run --world world/scenarios/clinic.json --job "$(cat world/scenarios/clinic.job.txt)" --frames --out runs/gallery/clinic
```

## The demo flow site

A second site lives in this folder, served by the Pathfinder backend, not by `web.serve`.

The demo flow as one page: pick a space, state a job, get a plan, film the demonstrations it
asks for, then see the robot and watch it work.

### Run it

The Pathfinder backend serves this folder:

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
| 6. Parts that fit | works with shop keys | `POST /parts/search` (Pathfinder's part search and fit check) |

The default space is Rabinowitz Hall. It is a web tour only: our API key cannot read that model,
so there is no mesh of it for the headset. Add a space by adding an entry to `worlds.json`
(`matterport` is the model id; `site` is the scene package name when one exists).
