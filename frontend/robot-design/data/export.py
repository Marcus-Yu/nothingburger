#!/usr/bin/env python3
"""Export one gallery run into the JSON snapshot the Robot Design and route pages read.

    .venv/bin/python frontend/robot-design/data/export.py                       # jrr, from the pathing branch
    .venv/bin/python frontend/robot-design/data/export.py --ref HEAD --scenario clinic
    .venv/bin/python frontend/robot-design/data/export.py --run runs/studio/<id>   # any local run folder
    python3 frontend/robot-design/data/export.py --grounds                      # the outdoor lots' aerial photos, for the route view

Reads the run, the parts catalog and the planner from a git ref with `git archive`, so the
working tree is never touched and nothing has to be merged first. The output is stamped with
the ref and commit it came from.

The route search is a replay: the ref's own nav planner (nav.route.plan) is run again on the
run's world, build, requirements and standoffs, with its A* instrumented to record the order it
expanded cells and the parent tree it built. The replay is checked against the recorded
route.json; the chosen route shipped to the page is always the recorded one.

Needs numpy (the repo's .venv has it). Whitelists fields: no LLM outputs, trace links,
frames or video.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_REF = "origin/claude/workflow-design-pathing-b05d8f"
BIN_M = 0.25            # explored cells are binned to this size for the page
MAX_BRANCHES = 4        # dropped branches kept per leg
BRANCH_MIN_M = 1.5      # a branch tip must sit at least this far from the chosen path
SLOTS = ("base", "lift", "arm", "gripper", "lidar", "camera")


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def unpack(ref: str, scenario: str, into: Path) -> None:
    paths = ["nav", "catalog", f"runs/gallery/{scenario}"]
    data = git("archive", "--format=tar", ref, *paths)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(into, filter="data")


def load(p: Path):
    return json.loads(p.read_text())


def events(p: Path):
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def r(v, n=3):
    return round(float(v), n)


# ---------- catalog ----------

UNSURE = ("assumed", "unverified")


def card(c: dict) -> dict:
    conf = c.get("confidence") or {}
    keep = {k: c[k] for k in ("id", "slot", "name", "price_usd", "mass_kg") if k in c}
    by_slot = {
        "base": ("kind", "holonomic", "outline_m", "payload_kg", "step_max_m"),
        "lift": ("stroke_m", "retracted_m"),
        "arm": ("reach_m", "payload_kg", "integrated_gripper"),
        "gripper": ("stroke_m", "force_n", "payload_kg", "hold", "fits_arms", "integrated_in"),
        "lidar": ("dim", "radius_m", "height_m"),
        "camera": (),
    }
    keep.update({k: c[k] for k in by_slot.get(c.get("slot"), ()) if k in c})
    if c.get("casters"):
        keep["casters"] = [[r(a[0]), r(a[1])] for a in c["casters"].get("at", [])]
    keep["unsure"] = sorted(k for k, v in conf.items() if k in keep and any(u in str(v) for u in UNSURE))
    return keep


def catalog(src: Path) -> dict:
    out = {s: [] for s in SLOTS}
    for f in sorted((src / "catalog").glob("*/*.json")):
        c = load(f)
        if c.get("slot") in out:
            out[c["slot"]].append(card(c))
    return out


# ---------- the run ----------

def check_row(c: dict) -> dict:
    row = {k: c.get(k) for k in ("check", "task", "status", "value", "limit", "unit")}
    if c.get("why"):
        row["why"] = c["why"]
    return row


def run_files(run: Path) -> dict:
    ev = events(run / "events.jsonl")
    intake = load(run / "intake.json") if (run / "intake.json").exists() else {}
    tasks = load(run / "tasks.json")
    design, build = load(run / "design.json"), load(run / "build.json")
    funnel = next(e for e in ev if e["kind"] == "candidates")
    cands = [{"parts": e["parts"], "price_usd": e.get("price_usd"), "mass_kg": e.get("mass_kg"),
              "feasible": e.get("feasible"),
              "failed": [{k: f.get(k) for k in ("check", "task", "value", "limit", "unit")} for f in e.get("failed") or []]}
             for e in ev if e["kind"] == "candidate"]
    decisions = [{"slot": d["slot"], "chosen": d["chosen"], "alternatives": d.get("catalog_alternatives", []),
                  "checks": [check_row(c) for c in d.get("checks", [])]}
                 for d in events(run / "decisions.jsonl") if d.get("step") == "design"]
    return {
        "job": intake.get("job") or next((e.get("job") for e in ev if e["kind"] == "run_start"), None),
        "tasks": [{k: t.get(k) for k in ("id", "skill", "anchor", "object", "carries", "deliver_to")} for t in tasks["tasks"]],
        "design": {"parts": design["parts"], "price_usd": design.get("price_usd"), "mass_kg": design.get("mass_kg"),
                   "checks": [check_row(c) for c in design.get("checks", [])]},
        "decisions": decisions,
        "search": {"considered": funnel["considered"], "passed_arithmetic": funnel["passed_arithmetic"],
                   "composed_and_checked": len(cands), "eliminated_by": funnel.get("eliminated_by", {})},
        "candidates": cands,
        "build": {"footprint": build["base"]["footprint"], "inscribed_radius_m": build["base"].get("inscribed_radius_m"),
                  "circumscribed_radius_m": build["base"].get("circumscribed_radius_m"),
                  "stowed": {k: build["stowed"][k] for k in ("width_m", "length_m", "height_m")}},
    }


def world_view(w: dict) -> dict:
    return {
        "id": w.get("id"), "source": w.get("source"), "frame": w.get("frame"),
        "rooms": [{k: rm.get(k) for k in ("id", "type", "polygon", "ceiling_m")} for rm in w.get("rooms", [])],
        "doorways": [{k: d.get(k) for k in ("id", "rooms", "position", "along", "width_m", "header_m")} for d in w.get("doorways", [])],
        "obstacles": [{"id": o["id"], "room": o.get("room"), "min": o["box"]["min"], "max": o["box"]["max"]} for o in w.get("obstacles", [])],
        "anchors": [{k: a.get(k) for k in ("id", "room", "kind", "point")} for a in w.get("anchors", [])],
        "dock": w.get("dock"), "way_out": w.get("way_out"),
        **({"floors": [{"id": f.get("id"), "z": f.get("z", 0.0)} for f in w["floors"]]} if w.get("floors") else {}),
    }


def grounds() -> None:
    """Copy each outdoor lot's aerial photo beside the page and list where it lies: data/aerial/grounds.json,
    {world id: {"image": file name, "extent": [x0, y0, x1, y1] in the world's metres}}. The route view lays the
    photo on the ground under the route (place.js). Reads world/scenarios/*.json in the working tree."""
    import shutil
    out = HERE / "aerial"
    out.mkdir(exist_ok=True)
    listing = {}
    for f in sorted((ROOT / "world" / "scenarios").glob("*.json")):
        w = load(f)
        g = w.get("ground") if isinstance(w, dict) else None
        if not (isinstance(g, dict) and g.get("image") and g.get("extent")):
            continue
        src = ROOT / g["image"]
        if not src.is_file():
            continue
        shutil.copyfile(src, out / src.name)
        listing[w["id"]] = {"image": src.name, "extent": g["extent"], "source": g.get("source")}
    (out / "grounds.json").write_text(json.dumps(listing, indent=1) + "\n")
    print(f"wrote {out / 'grounds.json'}: {', '.join(listing) or 'no lots'}")


# ---------- route search replay ----------

def replay(src: Path, world: dict, build: dict, req: dict, route: dict) -> list[dict]:
    """Run the ref's own planner again, recording each A* call's expansion order and parent tree."""
    sys.path.insert(0, str(src))
    import heapq as hq
    import types
    from nav import route as R

    rec = {"on": False, "pops": []}

    def heappop(h):
        item = hq.heappop(h)
        if rec["on"]:
            rec["pops"].append(item[1])
        return item

    R.heapq = types.SimpleNamespace(heappush=hq.heappush, heappop=heappop)
    orig, calls = R._astar, []

    def astar(grid, mask, start, goal, soft):
        rec["on"], rec["pops"], got = True, [], {}

        def prof(frame, event, arg):
            if event == "return" and frame.f_code is orig.__code__:
                got["parent"] = dict(frame.f_locals.get("parent") or {})
        sys.setprofile(prof)
        try:
            path = orig(grid, mask, start, goal, soft)
        finally:
            sys.setprofile(None)
            rec["on"] = False
        calls.append({"grid": grid, "pops": rec["pops"], "parent": got.get("parent", {}), "path": path})
        return path

    R._astar = astar
    replayed = R.plan(world, build, requirements=req, standoffs=route["standoffs"])

    recorded = route["legs"]
    same = len(replayed["legs"]) == len(recorded) and all(
        abs(a["length_m"] - b["length_m"]) < 0.01 and a["waypoints"] == b["waypoints"]
        for a, b in zip(replayed["legs"], recorded))
    if not same:
        sys.exit("export: the replayed route does not match the recorded route.json; refusing to ship a replay that disagrees")
    if len(calls) != len(recorded):
        sys.exit(f"export: expected one A* call per leg, got {len(calls)} for {len(recorded)} legs")
    return [search_view(c) for c in calls]


def search_view(call: dict) -> dict:
    grid, parent, path = call["grid"], call["parent"], call["path"] or []
    xy = lambda cell: tuple(float(v) for v in grid.centre(*cell))

    # expansion order: each cell once (the heap can hold stale entries), then binned for the page
    seen, first, order, have = set(), [], [], set()
    for cell in call["pops"]:
        if cell in seen:
            continue
        seen.add(cell)
        first.append(cell)
        x, y = xy(cell)
        b = (round(x / BIN_M), round(y / BIN_M))
        if b not in have:
            have.add(b)
            order.append(list(b))

    on_path = set(path)
    pts = [xy(c) for c in path]

    def dist_to_path(p):
        return min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in pts[::4] or [p])

    # dropped branches: expanded cells far from the chosen path, traced back to where they left it
    tips = sorted(first[::25], key=lambda c: -dist_to_path(xy(c)))
    branches, ends = [], []
    for tip in tips:
        p = xy(tip)
        if dist_to_path(p) < BRANCH_MIN_M or any(math.hypot(p[0] - e[0], p[1] - e[1]) < 2.5 for e in ends):
            continue
        chain, cur = [tip], tip
        while cur in parent and cur not in on_path:
            cur = parent[cur]
            chain.append(cur)
        line = [xy(c) for c in reversed(chain)][::5] + [p]
        branches.append([[r(a, 2), r(b, 2)] for a, b in line])
        ends.append(p)
        if len(branches) >= MAX_BRANCHES:
            break
    return {"expanded": len(first), "bin_m": BIN_M, "explored": order, "dropped": branches}


def snapshot(src: Path, run: Path, source: dict) -> dict:
    """The page's snapshot of one run folder. `src` holds the nav planner and catalog to use."""
    world, route = load(run / "world.json"), load(run / "route.json")
    snap = {
        "schema": "robot-design-snapshot/1",
        "source": source,
        "catalog": catalog(src),
        **run_files(run),
        "world": world_view(world),
        "route": {"legs": [{k: leg.get(k) for k in ("from", "to", "carrying", "length_m", "waypoints", "standoff")} for leg in route["legs"]],
                  "standoffs": [{k: s.get(k) for k in ("task", "pose", "covers")} for s in route.get("standoffs", [])],
                  "door_clearances": route.get("door_clearances", []), "failures": route.get("failures", [])},
    }
    searches = replay(src, world, load(run / "build.json"), load(run / "requirements.json"), route)
    for leg, s in zip(snap["route"]["legs"], searches):
        leg["search"] = s
    snap["route"]["search_note"] = ("Replayed with this commit's nav planner on the run's own inputs; "
                                    "the replay matched the recorded route.json leg for leg.")
    return snap


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--scenario", default="jrr")
    ap.add_argument("--run", type=Path, default=None,
                    help="a run folder in this working tree; uses the working tree's nav and catalog instead of --ref")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--grounds", action="store_true", help="only refresh data/aerial/: the outdoor lots' photos and where they lie")
    a = ap.parse_args()
    if a.grounds:
        return grounds()

    if a.run:
        run = a.run.resolve()
        sha = git("rev-parse", "HEAD").decode().strip()
        out = a.out or run / "snapshot.json"
        snap = snapshot(ROOT, run, {"ref": "working tree", "commit": sha, "scenario": a.scenario, "run": str(run.relative_to(ROOT)) if run.is_relative_to(ROOT) else run.name})
        ref = "the working tree"
    else:
        sha = git("rev-parse", a.ref).decode().strip()
        out = a.out or HERE / f"{a.scenario}.json"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            unpack(a.ref, a.scenario, src)
            snap = snapshot(src, src / "runs" / "gallery" / a.scenario,
                            {"ref": a.ref, "commit": sha, "scenario": a.scenario, "run": f"runs/gallery/{a.scenario}"})
        ref = a.ref

    out.write_text(json.dumps(snap, separators=(",", ":")))
    legs = snap["route"]["legs"]
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) from {ref} @ {sha[:7]}: "
          f"{len(snap['candidates'])} candidates, {len(legs)} legs, "
          f"{sum(l['search']['expanded'] for l in legs)} cells expanded, "
          f"{sum(len(l['search']['dropped']) for l in legs)} dropped branches")

if __name__ == "__main__":
    main()
