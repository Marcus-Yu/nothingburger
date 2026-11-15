# web/

The live run view: watch a design and pathing run as it happens, or replay a finished one.

```bash
python -m web.serve        # then open http://127.0.0.1:8010
```

- **Run** starts the agent as a separate process on the example world, with the job typed in the box (or the example task list when "model steps" is off).
- The page shows the robot being designed (a render of each candidate the composer checks, with why it was rejected, then the chosen one, then its reach pose at every standoff), the floor plan with corridors, standoffs and the route, the requirements ledger, the program, and the agent's trace: each step, each tool call, and what the model said.
- A finished run can be replayed or scrubbed with the bar at the bottom. Past runs are in the drop-down.
- With LangSmith tracing on, the header links to the same run's trace there.

It reads only a run folder: `events.jsonl` (written by the agent as the run goes; shape in `contracts/events.example.jsonl`) and the PNGs under `frames/` (written when the run is started with `--frames`). `serve.py` binds to 127.0.0.1 only.

The building panel is a picture, not a diagram: with `--frames` the run renders the world file from straight above (`room_view`: walls cut off at 1.1 m, furniture as the world's boxes) and the robot at the dock and at every stop in its reaching pose (`top` on the `design` and `standoff` events). The route, doors and labels are drawn over it in the same floor coordinates. Without frames the panel falls back to the line drawing.

**Watch it work.** With `--frames --walkthrough` the run also writes `frames/walkthrough.mp4`: the robot drives the planned route through the rendered rooms and plays each stop's arm samples from `trajectory.json`, with the camera following and a chapter per leg and motion. It plays positions back; nothing is simulated (no contact, no forces), and it needs `ffmpeg` on the PATH.

**In the real room.** When the world file has a `tour` (a Matterport model id and `to_model`, the 3 x 4 matrix from the world's frame to the scan's), the same run also writes `frames/tour_robot.glb` and `frames/tour_frames.bin`, and the panel links to `tour.html`. That page loads Matterport's SDK bundle from `web/_vendor/matterport` (`python web/fetch_sdk.py`; not committed), adds the robot to the scan's own scene and plays the plan inside the textured scan, with the viewpoint following the robot between the positions the scanner stood at. It needs `MATTERPORT_SDK_KEY` in `.env` and must be opened on `localhost` (the key is refused on `127.0.0.1`). Keys I J K L shift the robot 5 cm and U O turn it 1 degree, to line a traced world up with the scan; the offsets are kept in the address bar.

## Kept runs

`runs/gallery/` holds five finished runs, one per scenario in `world/scenarios/` (data centre, factory cell, senior apartment, clinic, pump house). They are listed first in the page's drop-down and replay without a model or a key, for example `http://127.0.0.1:8010/?run=runs/gallery/datacenter`. To make one again:

```bash
PYTHONPATH=. python -m agent.run --world world/scenarios/clinic.json --job "$(cat world/scenarios/clinic.job.txt)" --frames --out runs/gallery/clinic
```

## Demo flow page (`index.html`)

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
