"""Export a finished run's robot and motion for the real-room 3D page (web/viewer/room.html), after the fact.

    python -m agent.tour_export runs/studio/<run>

A run started with --frames --walkthrough already does this, but it also renders every candidate and films
the plan, which is slow. This writes only frames/tour_robot.glb and frames/tour_frames.bin and appends the
"tour" event room.html reads, so a quick run (the studio's) can still be played inside the scanned room.
Does nothing when the run has no route (no robot fit) or its world is not a traced tour.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import observe
from .tools import viz


def export(out: Path) -> dict | None:
    out = Path(out)
    world = json.loads((out / "world.json").read_text())
    if not world.get("tour") or not (out / "route.json").exists():
        return None
    events = out / "events.jsonl"
    last_t = 0.0
    if events.exists():
        lines = [line for line in events.read_text().splitlines() if line.strip()]
        last_t = json.loads(lines[-1]).get("t", 0.0) if lines else 0.0
    (out / "frames").mkdir(exist_ok=True)
    observe._events.update(path=events, t0=time.perf_counter() - last_t, frames=out / "frames", n_frames=0)
    real = viz.tour_export((out / "robot.xml").read_text(), json.loads((out / "build.json").read_text()),
                           json.loads((out / "route.json").read_text()), json.loads((out / "trajectory.json").read_text()))
    if real:
        observe.emit("tour", **real, matterport=world["tour"].get("matterport"))
    observe._events.update(path=None, frames=None)
    return real


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    real = export(Path(argv[0]))
    print(f"tour export: {real['glb']} ({real['n']} frames)" if real else "tour export: nothing to export")
    return 0


if __name__ == "__main__":
    sys.exit(main())
