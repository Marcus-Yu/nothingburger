# web/

Owner: Stream C. See AGENTS.md for scope and rules.

The demo flow as one page: pick a space, state a job, get a plan, film the demonstrations it
asks for, then see the robot and watch it work.

## Run it

The Pathfinder backend serves this folder:

```bash
cd world/pathfinder/backend
uv run python -m uvicorn server.app:app --host 0.0.0.0 --port 8004
```

Open http://localhost:8004/web/. For the demonstration step the headset must reach the same
server: `adb reverse tcp:8004 tcp:8004` over USB.

## The steps

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
