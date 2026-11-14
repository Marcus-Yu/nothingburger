"""The hand's shape and the arm behind it, from what the headset records.

The Quest tracks every finger joint, so the hand's shape is measured: how far apart the thumb
and the fingers are (the aperture a gripper has to match) and how curled each finger is.

The arm is not tracked. It is estimated: the shoulder sits a fixed way below and beside the
head, and the elbow is where a two-bone arm of the wearer's proportions has to bend to put the
wrist where it was. Those numbers say how the person's arm did the motion (shoulder to wrist
reach, elbow angle), which is what gets translated to a robot arm. They are an estimate and are
labelled as one.
"""

from __future__ import annotations

import numpy as np

UP = np.array([0.0, 1.0, 0.0])
FINGERS = ("Index", "Middle", "Ring", "Pinky")
# Proportions of standing height (Drillis and Contini's segment ratios, rounded).
UPPER_ARM, FOREARM, SHOULDER_HALF_WIDTH, EYE_TO_SHOULDER = 0.186, 0.146, 0.129, 0.117


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n > 1e-9, n, 1.0)


def joint_tracks(recording: dict, hand: str) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """(times, joints (n, J, 3), names) for the samples where that hand's skeleton was tracked.
    None when the recording has no joints for it (controllers, or an older recording)."""
    names = recording.get("joint_names")
    if not names:
        return None
    rows = [(s["t"], s[hand]["joints"]) for s in recording["samples"]
            if s.get(hand) and s[hand].get("tracked") and s[hand].get("joints")]  # fmt: skip
    if len(rows) < 5:
        return None
    return np.array([r[0] for r in rows], dtype=float), np.array([r[1] for r in rows], dtype=float), list(names)


def hand_shape(recording: dict, hand: str, t0: float | None = None, t1: float | None = None) -> dict | None:
    """The hand's shape between `t0` and `t1` seconds (the whole recording by default).

    - `aperture_m`: thumb tip to the nearest other fingertip. `min` is how small a thing was
      held; `max` how wide the hand opened.
    - `span_m`: thumb tip to pinky tip, the open hand's width.
    - `curl`: per finger, 0 (straight) to 1 (folded onto the palm), the median over the window.
    - `closure`: the four fingers' mean curl over time, as `min`, `median`, `max`: a grasp
      measure that, unlike a pinch, sees a fist or a flat palm for what it is.
    """
    tracks = joint_tracks(recording, hand)
    if tracks is None:
        return None
    t, joints, names = tracks
    index = {name: i for i, name in enumerate(names)}
    need = ["HandThumbTip", "HandWristRoot"] + [f"Hand{f}Tip" for f in FINGERS] + [f"Hand{f}1" for f in FINGERS]
    if any(n not in index for n in need):
        return None
    keep = np.ones(len(t), dtype=bool)
    if t0 is not None:
        keep &= t >= t0
    if t1 is not None:
        keep &= t <= t1
    if keep.sum() < 3:
        return None
    j = joints[keep]

    def at(name):
        return j[:, index[name]]

    thumb = at("HandThumbTip")
    tips = np.stack([at(f"Hand{f}Tip") for f in FINGERS], axis=1)  # (n, 4, 3)
    aperture = np.linalg.norm(tips - thumb[:, None], axis=2).min(axis=1)
    span = np.linalg.norm(at("HandPinkyTip") - thumb, axis=1)

    # curl: how far the fingertip has come back toward the knuckle's line to the wrist.
    # Straight, the tip is a finger's length beyond the knuckle; folded, it is beside it.
    curls = {}
    for f in FINGERS:
        knuckle, tip, wrist = at(f"Hand{f}1"), at(f"Hand{f}Tip"), at("HandWristRoot")
        along = _unit(knuckle - wrist)
        reach = np.einsum("nk,nk->n", tip - knuckle, along)  # + straight out, - folded back
        length = np.percentile(np.linalg.norm(tip - knuckle, axis=1), 95) + 1e-6
        curls[f.lower()] = np.clip(0.5 - 0.5 * reach / length, 0.0, 1.0)
    closure = np.mean(list(curls.values()), axis=0)
    r3 = lambda v: round(float(v), 3)  # noqa: E731
    return {
        "source": "tracked finger joints",
        "aperture_m": {"min": r3(aperture.min()), "median": r3(np.median(aperture)), "max": r3(aperture.max())},
        "span_m": {"median": r3(np.median(span)), "max": r3(span.max())},
        "curl": {name: r3(np.median(c)) for name, c in curls.items()},
        "closure": {"min": r3(closure.min()), "median": r3(np.median(closure)), "max": r3(closure.max())},
    }


def closure_series(recording: dict, hand: str) -> tuple[np.ndarray, np.ndarray] | None:
    """(times, closure 0..1) for that hand: the four fingers' mean curl, sample by sample."""
    tracks = joint_tracks(recording, hand)
    if tracks is None:
        return None
    t, joints, names = tracks
    index = {name: i for i, name in enumerate(names)}
    try:
        wrist = joints[:, index["HandWristRoot"]]
        out = []
        for f in FINGERS:
            knuckle, tip = joints[:, index[f"Hand{f}1"]], joints[:, index[f"Hand{f}Tip"]]
            reach = np.einsum("nk,nk->n", tip - knuckle, _unit(knuckle - wrist))
            length = np.percentile(np.linalg.norm(tip - knuckle, axis=1), 95) + 1e-6
            out.append(np.clip(0.5 - 0.5 * reach / length, 0.0, 1.0))
    except KeyError:
        return None
    return t, np.mean(out, axis=0)


def estimate_arm(head_p: np.ndarray, head_q: np.ndarray, wrist_p: np.ndarray, hand: str,
                 height_m: float = 1.72) -> dict:  # fmt: skip
    """Shoulder and elbow for each sample, from the head pose and the wrist (arrays (n, 3),
    (n, 4), (n, 3) in the recording's right-handed frame). `height_m` scales the segments.

    The shoulder is below the eyes and to the side the hand is on, turning with the head's
    heading only (a nod does not move the shoulders). The elbow is on the circle a two-bone arm
    allows, at the point lowest and outermost: where an elbow hangs when nothing else decides.
    """
    from capture.process import quat_rotate

    upper, fore = UPPER_ARM * height_m, FOREARM * height_m
    # In the recording's frame (X mirrored from Unity) the head looks along +z and its own +x
    # axis points to the wearer's left.
    forward = quat_rotate(head_q, np.broadcast_to(np.array([0.0, 0.0, 1.0]), head_p.shape))
    forward[:, 1] = 0.0
    forward = _unit(forward)
    to_left = np.cross(UP, forward)  # right-handed, +Y up, looking along +z: left is +x
    side = to_left if hand == "left" else -to_left
    shoulder = head_p - UP * (EYE_TO_SHOULDER * height_m) + side * (SHOULDER_HALF_WIDTH * height_m)

    reach_vec = wrist_p - shoulder
    reach = np.linalg.norm(reach_vec, axis=1)
    d = np.clip(reach, abs(upper - fore) + 1e-4, upper + fore - 1e-4)
    axis = _unit(reach_vec)
    a = (upper**2 - fore**2 + d**2) / (2 * d)  # shoulder to the elbow circle's centre
    radius = np.sqrt(np.maximum(upper**2 - a**2, 0.0))
    # direction on the circle: down and outward, made perpendicular to the arm's axis
    want = -UP + 0.5 * side
    perp = _unit(want - np.einsum("nk,nk->n", want, axis)[:, None] * axis)
    elbow = shoulder + axis * a[:, None] + perp * radius[:, None]
    cos_elbow = (upper**2 + fore**2 - d**2) / (2 * upper * fore)
    elbow_deg = np.degrees(np.arccos(np.clip(cos_elbow, -1.0, 1.0)))  # 180 = straight
    return {
        "source": "estimated from the head pose and the wrist; the arm itself is not tracked",
        "assumed_height_m": height_m,
        "segments_m": {"upper_arm": round(upper, 3), "forearm": round(fore, 3)},
        "shoulder": shoulder,
        "elbow": elbow,
        "reach_m": reach,
        "elbow_deg": elbow_deg,
        "overreach": reach > upper + fore,  # the wrist was farther than this arm reaches: they leaned
    }


def arm_summary(arm: dict, mask: np.ndarray | None = None) -> dict:
    """The arm estimate reduced to what a robot arm has to cover."""
    m = np.ones(len(arm["reach_m"]), dtype=bool) if mask is None else mask
    r3 = lambda v: round(float(v), 3)  # noqa: E731
    return {
        "source": arm["source"],
        "assumed_height_m": arm["assumed_height_m"],
        "segments_m": arm["segments_m"],
        "shoulder_to_wrist_m": {"min": r3(arm["reach_m"][m].min()), "max": r3(arm["reach_m"][m].max())},
        "elbow_deg": {"min": r3(arm["elbow_deg"][m].min()), "max": r3(arm["elbow_deg"][m].max())},
        "leaned_pct": round(100.0 * float(arm["overreach"][m].mean()), 1),
    }
