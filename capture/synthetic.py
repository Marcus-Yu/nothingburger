"""Recordings made by formula, in the headset's format: stand-ins until real ones are filmed,
and the ground truth the processing is tested against. Each returns a `capture.recording/1`
dict for a person standing at a table whose top is 0.75 m above the floor.

    python -m capture.synthetic <out dir>     # writes one file per chore
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RATE = 30.0
FLOOR_Y = 0.0
TABLE_Y = 0.75
IDENT = [0.0, 0.0, 0.0, 1.0]


def _quat_about(axis, angle) -> list[float]:
    axis = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    return [*(axis * np.sin(angle / 2)), float(np.cos(angle / 2))]


def _recording(chore, kind, anchor, frames, hand="right", noise=0.002, seed=0) -> dict:
    """`frames`: list of dicts {"right": (p, q, grip), "left": (p, q, grip)}; a missing hand is
    untracked for that frame."""
    rng = np.random.default_rng(seed)
    samples = []
    for i, frame in enumerate(frames):
        sample = {"t": round(i / RATE, 4), "head": {"p": [0.0, 1.65, 0.55], "q": IDENT}}
        for side in ("left", "right"):
            if side in frame:
                p, q, grip = frame[side]
                p = np.asarray(p, dtype=float) + rng.normal(0, noise, 3)
                sample[side] = {"p": p.round(4).tolist(), "q": list(q), "grip": round(float(grip), 3),
                                "force_n": None, "tracked": True}  # fmt: skip
            else:
                sample[side] = {"p": [0, 0, 0], "q": IDENT, "grip": 0.0, "force_n": None, "tracked": False}
        samples.append(sample)
    return {
        "schema": "capture.recording/1",
        "id": f"synthetic-{chore.replace(' ', '-')}",
        "kind": kind,
        "chore": chore,
        "site": "synthetic",
        "frame": "scene",
        "rate_hz": RATE,
        "floor_y": FLOOR_Y,
        "hand": hand,
        "device": {"headset": "synthetic", "input": "hands", "glove": None},
        "anchor": anchor,
        "samples": samples,
    }


def _line(a, b, seconds):
    n = max(2, int(seconds * RATE))
    return [np.asarray(a) + (np.asarray(b) - np.asarray(a)) * k / (n - 1) for k in range(n)]


def wipe_table(passes: int = 4, width: float = 0.6, depth: float = 0.3) -> dict:
    """An open hand sweeps left and right over a patch of table top, moving away each pass."""
    anchor = {"p": [0.0, TABLE_Y, 0.0], "normal": [0.0, 1.0, 0.0], "label": "table"}
    hover = TABLE_Y + 0.02
    path = _line([0.25, 1.1, 0.5], [-width / 2, hover, depth / 2], 1.0)
    for k in range(passes):
        z = depth / 2 - depth * k / max(passes - 1, 1)
        a, b = ([-width / 2, hover, z], [width / 2, hover, z]) if k % 2 == 0 else ([width / 2, hover, z], [-width / 2, hover, z])
        path += _line(a, b, 0.9)
    path += _line(path[-1], [0.25, 1.1, 0.5], 1.0)
    return _recording("wipe table", "path", anchor, [{"right": (p, IDENT, 0.1)} for p in path])


def move_bin(distance: float = 0.8, width: float = 0.42) -> dict:
    """Both hands close on a bin's sides, lift it 20 cm, carry it sideways and set it down."""
    anchor = {"p": [0.0, TABLE_Y + 0.15, 0.0], "normal": None, "label": "bin"}
    half = np.array([width / 2, 0.0, 0.0])
    centre = np.array([0.0, TABLE_Y + 0.15, 0.0])
    legs = [
        (_line(centre + [0, 0.25, 0.4], centre, 1.0), 0.0),  # reach in
        ([centre] * int(0.4 * RATE), 0.9),  # close
        (_line(centre, centre + [0, 0.2, 0], 0.6), 0.9),  # lift
        (_line(centre + [0, 0.2, 0], centre + [distance, 0.2, 0], 1.5), 0.9),  # carry
        (_line(centre + [distance, 0.2, 0], centre + [distance, 0, 0], 0.6), 0.9),  # lower
        ([centre + [distance, 0, 0]] * int(0.3 * RATE), 0.1),  # let go
        (_line(centre + [distance, 0, 0], centre + [distance, 0.25, 0.4], 0.8), 0.0),  # back away
    ]
    frames = [{"right": (c + half, IDENT, grip), "left": (c - half, IDENT, grip)} for pts, grip in legs for c in pts]
    return _recording("move bin", "path", anchor, frames)


def open_box(radius: float = 0.3, angle_deg: float = 100.0) -> dict:
    """One hand takes the front edge of a box lid and swings it up and back about the hinge
    along the box's far edge (a line parallel to x)."""
    hinge = np.array([0.0, TABLE_Y + 0.25, -radius])
    anchor = {"p": [0.0, TABLE_Y + 0.25, 0.0], "normal": [0.0, 1.0, 0.0], "label": "box lid"}
    grasp = hinge + [0.0, 0.0, radius]
    swing = []
    for k in range(int(1.6 * RATE)):
        a = np.radians(angle_deg) * k / (int(1.6 * RATE) - 1)
        swing.append((hinge + [0.0, radius * np.sin(a), radius * np.cos(a)], _quat_about([1, 0, 0], -a)))
    frames = [{"right": (p, IDENT, 0.0)} for p in _line(grasp + [0, 0.2, 0.3], grasp + [0, 0.12, 0], 0.9)]
    frames += [{"right": (p, IDENT, 0.0)} for p in _line(grasp + [0, 0.12, 0], grasp, 0.3)]
    frames += [{"right": (grasp, IDENT, 0.8)}] * int(0.3 * RATE)
    frames += [{"right": (p, q, 0.8)} for p, q in swing]
    frames += [{"right": (swing[-1][0], swing[-1][1], 0.0)}] * int(0.3 * RATE)
    frames += [{"right": (p, swing[-1][1], 0.0)} for p in _line(swing[-1][0], swing[-1][0] + [0, 0.1, 0.4], 0.8)]
    return _recording("open box", "path", anchor, frames)


def unscrew_bulb(turns: float = 1.5, height: float = 1.6) -> dict:
    """A hand reaches up to a hanging bulb, holds it and turns it anticlockwise seen from below."""
    bulb = np.array([0.0, height, 0.0])
    anchor = {"p": bulb.tolist(), "normal": [0.0, -1.0, 0.0], "label": "bulb"}
    frames = [{"right": (p, IDENT, 0.0)} for p in _line([0.2, 1.2, 0.4], bulb, 1.0)]
    n = int(2.0 * RATE)
    frames += [{"right": (bulb, _quat_about([0, 1, 0], 2 * np.pi * turns * k / (n - 1)), 0.6)} for k in range(n)]
    last = frames[-1]["right"][1]
    frames += [{"right": (p, last, 0.0)} for p in _line(bulb, [0.2, 1.2, 0.4], 0.8)]
    return _recording("unscrew bulb", "path", anchor, frames)


def squeeze(low: float = 0.3, high: float = 0.8, force_per_unit: float | None = None) -> dict:
    """A squeeze test: the hand holds still and tightens from `low` to `high`. With
    `force_per_unit` the samples carry glove newtons as well."""
    p = [0.0, 1.0, 0.3]
    n = int(3.0 * RATE)
    rec = _recording("squeeze", "squeeze", {"p": p, "normal": None, "label": "bulb"},
                     [{"right": (p, IDENT, low + (high - low) * k / (n - 1))} for k in range(n)], noise=0.0)  # fmt: skip
    if force_per_unit is not None:
        rec["device"]["glove"] = "synthetic force glove"
        for s in rec["samples"]:
            s["right"]["force_n"] = round(s["right"]["grip"] * force_per_unit, 3)
    return rec


ALL = {"wipe-table": wipe_table, "move-bin": move_bin, "open-box": open_box, "unscrew-bulb": unscrew_bulb, "squeeze": squeeze}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "capture/store")
    out.mkdir(parents=True, exist_ok=True)
    for name, make in ALL.items():
        (out / f"{name}.json").write_text(json.dumps(make()), encoding="utf8")
        print("wrote", out / f"{name}.json")
