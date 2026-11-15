# Quick demo: a robot that wipes a table

One job, typed in the studio: **Wipe a surface**. The agent reads it, asks the headset for one wipe and one
squeeze, designs the robot, plans where it stands and drives in Rabinowitz Hall, then opens the Robot Design
page, the route view and the robot inside the scanned room in 3D. About **15 s** of generation once rehearsed (below).

## Once per machine (about 5 min, unattended)

```bash
python catalog/fetch_assets.py
```

```bash
PYTHONPATH=. uv run python -m composer.warm --workers 10
```

This samples every arm's reach envelope (560 carriers). It is a pure function of the catalog and the code,
cached in `catalog/_cache/` (git-ignored); a changed card or sampler recomputes on its own.

## Before the demo

Keys in `.env`: `SUBQ_API_KEY` (classify on SubQ Snap 1.2) and, for the job to be read by Claude rather
than by rule, `ANTHROPIC_API_KEY`. Start three servers:

```bash
uv run --env-file .env python -m agent.design_flow.serve
```

```bash
cd world/pathfinder/backend && uv run python -m uvicorn server.app:app --host 0.0.0.0 --port 8004
```

```bash
python3 -m http.server 8000 -d frontend
```

Without `ANTHROPIC_API_KEY`, add `--standin` to the first command: Snap still classifies, and the job's words are
matched to the hall's tables and items by rule (`agent/design_flow/jobs.py`).

**Rehearse once.** Run the exact job you will show, end to end, filming the wipe and the squeeze in the
headset. That teaches the skill (its takes are kept in `agent/design_flow/skill_data/`) and caches every robot
check for that job. The first run takes one to two minutes.

## On stage (about 15 s)

1. Open http://localhost:8000/#studio. The space is Rabinowitz Hall.
2. Type **Wipe a surface** (or tap it under the prompt) and press **Design robot**.
   The outline says *Decided by SubQ Snap 1.2 in 0.2 s* and *Already learned from an earlier demonstration*.
3. The agent trace opens by itself: the six steps, the robots tried cheapest first and why each fails, then
   where it stands. **Show trace** lists every call.
4. **Open Robot Design** → watch it assemble → **Deploy** → the route view.
5. **See it in the real room (3D)** (on the trace page or in the plan panel) opens the plan played inside the
   Matterport mesh of the atrium. It needs the stitched mesh at `world/_scans/jrr/room.glb` (not committed; see
   `web/README.md`, "The real room as a mesh"). Without it the button still opens, over a plain floor.

**To film the demonstration live instead**, delete `agent/design_flow/skill_data/wipe_table/` first. The plan
then asks for the takes (**Ask the headset** for the motion and the squeeze, then **Use these takes → design the
robot**). A new take changes the job's numbers, so its checks are not cached: allow one to two minutes.

No headset? Start the workflow server with `CAPTURE_INBOX=<folder>` holding recordings stamped with the chore
the request shows (`wipe table`).

## What the prompt bar does in this space

| Job | Result |
| :-- | :-- |
| Wipe a surface | one table: demo, then a robot in about 15 s rehearsed |
| Wipe down the tables | both tables, about 25 s rehearsed |
| Carry a container outside | the sample bottle, out the south door: about 10 s |
| Take out a trash bag | refused: no trash bag in the hall's world file (the sample bottle is) |
| Change a light bulb | refused: no light fixture in the hall's world file |
| Open a box, caretaker jobs | refused: not a skill the pipeline has yet |
| Replace … | the parts search, as before |

Measured on this machine, 2026-11-15, with warm caches: rehearsal 56 s, on stage 15 s including the 3D export.
The design step can still loop once ("redesign") when pathing cannot use the first robot.
