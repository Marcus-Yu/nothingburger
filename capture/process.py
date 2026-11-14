"""Turn a raw headset recording into `demo.json` and `grip.json`.

A recording (`capture.recording/1`, written by the Quest app's DemoRecorder) is what the person
did: head and both hands sampled about 30 times a second in the scan's frame (metres, right
handed, +Y up), each hand with a grip value from 0 to 1 and, when a force glove is worn, a force
in newtons. It also carries the anchor: the point on the scan the person marked as the thing
they are about to work on.

`build_demo` reduces that to what the designer and the motion stream need:

- the working hand's 6-DoF path at a fixed rate, relative to the anchor;
- phase labels (approach, work, retreat);
- what kind of motion the work was, with its numbers: a wipe (the patch of surface covered and
  the stroke), a carry (pick and place poses, the grasp width when both hands held it), a hinge
  (axis, radius and angle of the swing, as when a box lid opens) or a twist (axis and turns);
- the reach it asks of a robot: how high, how low, how far from the body, and the direction the
  hand came in from.

`build_grip` gives the grip-force band in newtons.

Nothing here knows about a particular chore: the motion kind is read off the geometry.
"""

from __future__ import annotations

import numpy as np

RATE_HZ = 30.0
UP = np.array([0.0, 1.0, 0.0])
ENGAGE_GRIP = 0.5  # a hand is holding something above this
GLOVE_CONTACT_RAW = 82  # 2 % of the glove's 4095
CLOSED_HAND = 0.55  # mean finger curl above this is a closed hand
ENGAGE_NEAR_M = 0.05  # or working on the anchor surface within this distance of its plane
DEFAULT_N_PER_UNIT = 12.0  # trigger or pinch travel 0..1 to newtons, until a glove measures it


# ------------------------------------------------------------------------------- small maths


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def quat_rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rotate vectors `v` (..., 3) by quaternions `q` (..., 4) given as x, y, z, w."""
    u, w = q[..., :3], q[..., 3:4]
    return v + 2.0 * np.cross(u, np.cross(u, v) + w * v)


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ],
        axis=-1,
    )


def quat_conj(q: np.ndarray) -> np.ndarray:
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def quat_from_matrix(m: np.ndarray) -> np.ndarray:
    """x, y, z, w of a rotation matrix (columns are the rotated axes)."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, s / 4]
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(1.0 + m[i, i] - m[j, j] - m[k, k]) * 2
        q = [0.0, 0.0, 0.0, (m[k, j] - m[j, k]) / s]
        q[i], q[j], q[k] = s / 4, (m[j, i] + m[i, j]) / s, (m[k, i] + m[i, k]) / s
    return _unit(np.array(q))


def _slerp(q0: np.ndarray, q1: np.ndarray, t: np.ndarray) -> np.ndarray:
    dot = np.sum(q0 * q1, axis=-1, keepdims=True)
    q1 = np.where(dot < 0, -q1, q1)
    dot = np.clip(np.abs(dot), 0.0, 1.0)
    theta = np.arccos(dot)
    s = np.sin(theta)
    near = s < 1e-6
    a = np.where(near, 1.0 - t, np.sin((1.0 - t) * theta) / np.where(near, 1.0, s))
    b = np.where(near, t, np.sin(t * theta) / np.where(near, 1.0, s))
    out = a * q0 + b * q1
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


# --------------------------------------------------------------------------------- resampling


def hand_track(recording: dict, hand: str, rate_hz: float = RATE_HZ) -> dict | None:
    """One hand at a fixed rate: `t`, `p` (n, 3), `q` (n, 4), `grip`, `force_n` (nan where the
    glove gave none). Samples where the hand was not tracked are bridged from their neighbours.
    None when the hand was tracked for less than half a second."""
    rows = [(s["t"], s[hand]) for s in recording["samples"] if s.get(hand) and s[hand].get("tracked", True)]
    if len(rows) < 2 or rows[-1][0] - rows[0][0] < 0.5:
        return None
    t_in = np.array([r[0] for r in rows], dtype=float)
    p_in = np.array([r[1]["p"] for r in rows], dtype=float)
    q_in = np.array([r[1]["q"] for r in rows], dtype=float)
    q_in /= np.linalg.norm(q_in, axis=1, keepdims=True)
    grip_in = np.array([float(r[1].get("grip", 0.0)) for r in rows])
    force_in = np.array([np.nan if r[1].get("force_n") is None else float(r[1]["force_n"]) for r in rows])

    t0, t1 = float(recording["samples"][0]["t"]), float(recording["samples"][-1]["t"])
    t = np.arange(max(t0, t_in[0]), min(t1, t_in[-1]) + 1e-9, 1.0 / rate_hz)
    hi = np.clip(np.searchsorted(t_in, t, side="right"), 1, len(t_in) - 1)
    lo = hi - 1
    w = ((t - t_in[lo]) / np.maximum(t_in[hi] - t_in[lo], 1e-9))[:, None]
    p = p_in[lo] * (1 - w) + p_in[hi] * w
    q = _slerp(q_in[lo], q_in[hi], w)
    grip = np.interp(t, t_in, grip_in)
    force = np.interp(t, t_in, force_in) if np.isfinite(force_in).all() else np.full(len(t), np.nan)
    # a light smoothing of position: tracking jitter is a few millimetres at 30 Hz
    kernel = np.array([1.0, 4.0, 6.0, 4.0, 1.0]) / 16.0
    if len(p) >= 5:
        padded = np.pad(p, ((2, 2), (0, 0)), mode="edge")
        p = sum(kernel[i] * padded[i : i + len(p)] for i in range(5))
    # The recording starts on the pinch that marked the target. That pinch is not part of the
    # chore: until the hand first opens again, it is not holding anything.
    if grip[0] >= ENGAGE_GRIP * 0.5:
        opened = np.flatnonzero(grip < 0.3)
        end = int(opened[0]) if len(opened) else len(grip)
        if end <= rate_hz * 1.5:
            grip = grip.copy()
            grip[:end] = 0.0
            force = force.copy()
            force[:end] = np.where(np.isfinite(force[:end]), 0.0, np.nan)
    # With finger joints the hand's closure is known: a fist or a hand round a cloth holds
    # something whether or not a fingertip touches the thumb.
    from capture import body  # noqa: PLC0415 -- body imports this module's quaternion helpers

    closure = body.closure_series(recording, hand)
    held = grip >= ENGAGE_GRIP
    if closure is not None:
        held = held | (np.interp(t, *closure) >= CLOSED_HAND)
    # A glove feels contact directly: any fingertip pressed past 2 % of full scale is touching
    # something, whatever shape the hand tracking thinks the hand is in.
    pressed = [(r[0], max(r[1]["glove_raw"])) for r in rows if r[1].get("glove_raw")]
    contact = None
    if len(pressed) >= 2:
        contact = np.interp(t, [a for a, _ in pressed], [b for _, b in pressed]) > GLOVE_CONTACT_RAW
        held = held | contact
    return {"t": t - t[0], "t0": float(t[0]), "p": p, "q": q, "grip": grip, "force_n": force, "held": held,
            "contact_s": 0.0 if contact is None else float(contact.sum() / rate_hz)}


# ------------------------------------------------------------------------------- anchor frame


def anchor_frame(anchor: dict) -> tuple[np.ndarray, np.ndarray]:
    """The object frame: origin at the anchor point, z along the surface normal there (out of
    the surface), x horizontal. Returns (origin, R) with R's columns the frame's axes in the
    scan frame. Without a normal the frame is the scan's own axes moved to the anchor."""
    origin = np.array(anchor["p"], dtype=float)
    normal = anchor.get("normal")
    if normal is None or np.linalg.norm(normal) < 1e-6:
        return origin, np.eye(3)
    z = _unit(np.array(normal, dtype=float))
    x = np.cross(UP, z)
    if np.linalg.norm(x) < 0.2:  # a floor, table top or ceiling: no horizontal direction of its own
        x = np.cross(z, np.array([0.0, 0.0, 1.0]))
    x = _unit(x)
    y = np.cross(z, x)
    return origin, np.stack([x, y, z], axis=1)


# ------------------------------------------------------------------------------------- phases


def engaged_mask(track: dict, origin: np.ndarray, normal: np.ndarray | None) -> np.ndarray:
    """Where the hand is doing the work: holding (grip) or on the anchor's surface."""
    held = track["held"]
    if normal is None:
        return held
    rel = track["p"] - origin
    height = rel @ normal
    lateral = np.linalg.norm(rel - np.outer(height, normal), axis=1)
    on_surface = (np.abs(height) <= ENGAGE_NEAR_M) & (lateral <= 1.5)
    return held | on_surface


def phases(engaged: np.ndarray) -> list[str]:
    """approach until the work starts, retreat after it ends, work between (gaps included: a
    hand lifting off mid-wipe is still wiping)."""
    idx = np.flatnonzero(engaged)
    if len(idx) == 0:
        return ["approach"] * len(engaged)
    first, last = int(idx[0]), int(idx[-1])
    return ["approach"] * first + ["work"] * (last - first + 1) + ["retreat"] * (len(engaged) - last - 1)


# -------------------------------------------------------------------------------- motion kind


def _plane_fit(points: np.ndarray):
    centre = points.mean(axis=0)
    _, s, vt = np.linalg.svd(points - centre, full_matrices=False)
    return centre, vt, s / np.sqrt(len(points))


def _fit_arc(points: np.ndarray) -> dict | None:
    """A circle through `points`: the swing of something on a hinge. None when they do not
    lie on one (too little spread, or too straight to tell from a line)."""
    centre, vt, spread = _plane_fit(points)
    if spread[0] < 0.03 or spread[1] < 0.01 or spread[2] > 0.35 * spread[1]:
        return None
    axis = vt[2]
    uv = (points - centre) @ vt[:2].T
    a = np.c_[2 * uv, np.ones(len(uv))]
    sol, *_ = np.linalg.lstsq(a, (uv**2).sum(axis=1), rcond=None)
    c2 = sol[:2]
    radius = float(np.sqrt(max(sol[2] + c2 @ c2, 0.0)))
    if not 0.03 <= radius <= 2.0:
        return None
    residual = float(np.sqrt(np.mean((np.linalg.norm(uv - c2, axis=1) - radius) ** 2)))
    if residual > 0.06 * radius:
        return None
    ang = np.unwrap(np.arctan2(uv[:, 1] - c2[1], uv[:, 0] - c2[0]))
    sweep = float(ang[-1] - ang[0])
    if abs(sweep) < np.radians(25):
        return None
    return {
        "axis": (axis * np.sign(sweep)).tolist(),  # right-hand rule: the swing is positive about it
        "point": (centre + c2 @ vt[:2]).tolist(),
        "radius_m": round(radius, 4),
        "angle_deg": round(abs(np.degrees(sweep)), 1),
        "residual_m": round(residual, 4),
    }


def _twist(q: np.ndarray) -> tuple[np.ndarray, float]:
    """Axis (scan frame) and signed angle in degrees of the rotation from the first to the last
    orientation, following it through, so more than half a turn is counted."""
    step = quat_mul(q[1:], quat_conj(q[:-1]))
    step = np.where(step[:, 3:4] < 0, -step, step)
    rotvec = 2.0 * step[:, :3]  # small angles
    total = rotvec.sum(axis=0)
    angle = float(np.degrees(np.linalg.norm(total)))
    return _unit(total), angle


def _passes(along: np.ndarray) -> int:
    """How many times the hand swept along the stroke: one more than its turn-arounds, counting
    a turn only after it has gone a fifth of the stroke the other way."""
    span = float(along.max() - along.min())
    if span < 1e-6:
        return 1
    turns, direction, extreme = 0, 0, along[0]
    for v in along[1:]:
        if direction == 0:
            if abs(v - extreme) > 0.2 * span:
                direction = 1 if v > extreme else -1
                extreme = v
        elif (v - extreme) * direction > 0:
            extreme = v
        elif abs(v - extreme) > 0.2 * span:
            turns, direction, extreme = turns + 1, -direction, v
    return turns + 1


def classify(work_p: np.ndarray, work_q: np.ndarray, held: np.ndarray, normal: np.ndarray | None) -> dict:
    """What the work was. `work_p` in the scan frame."""
    net = float(np.linalg.norm(work_p[-1] - work_p[0]))
    length = float(np.linalg.norm(np.diff(work_p, axis=0), axis=1).sum())
    axis, turn = _twist(work_q)
    extent = float(np.linalg.norm(work_p.max(axis=0) - work_p.min(axis=0)))

    if turn >= 60 and extent < 0.12:
        return {"kind": "twist", "axis": axis.tolist(), "angle_deg": round(turn, 1),
                "turns": round(turn / 360.0, 2)}  # fmt: skip

    # what the hand did while it held something, without the reach in and the letting go
    held_p = work_p[held] if held.sum() >= 5 else None
    arc = _fit_arc(held_p) if held_p is not None else None
    if arc is not None:
        return {"kind": "hinge", **arc}

    if held_p is not None:
        moved = float(np.linalg.norm(held_p[-1] - held_p[0]))
        if moved >= 0.25:
            return {"kind": "carry", "distance_m": round(moved, 3),
                    "lift_m": round(float(held_p[:, 1].max() - held_p[0, 1]), 3)}  # fmt: skip

    centre, vt, spread = _plane_fit(work_p)
    flat = spread[2] <= max(0.02, 0.25 * spread[1])
    if length >= 2.0 * max(net, 0.15) and flat and extent >= 0.15:
        n = vt[2] if normal is None else normal
        uv = (work_p - centre) @ vt[:2].T
        lo, hi = uv.min(axis=0), uv.max(axis=0)
        return {
            "kind": "wipe",
            "surface_normal": _unit(n * np.sign(n @ (UP if abs(n @ UP) > 0.5 else n))).tolist(),
            "centre": centre.tolist(),
            "stroke_axis": vt[0].tolist(),
            "size_m": [round(float(hi[0] - lo[0]), 3), round(float(hi[1] - lo[1]), 3)],
            "path_m": round(length, 3),
            "passes": _passes(uv[:, 0]),
        }
    return {"kind": "reach", "distance_m": round(net, 3)}


# -------------------------------------------------------------------------------- the outputs


def pick_hand(recording: dict, tracks: dict) -> str:
    """The working hand: the one named in the recording, else the one that moved more."""
    named = recording.get("hand")
    if named in tracks:
        return named
    # a gloved hand that felt contact did the work
    touched = {h: tr["contact_s"] for h, tr in tracks.items() if tr["contact_s"] >= 0.5}
    if touched:
        return max(touched, key=touched.get)
    return max(tracks, key=lambda h: float(np.linalg.norm(np.diff(tracks[h]["p"], axis=0), axis=1).sum()))


def build_demo(recording: dict, rate_hz: float = RATE_HZ) -> dict:
    """`demo.json` for a path recording. Raises ValueError when no hand was tracked."""
    tracks = {h: tr for h in ("left", "right") if (tr := hand_track(recording, h, rate_hz)) is not None}
    if not tracks:
        raise ValueError("no hand was tracked for long enough to make a demo")
    hand = pick_hand(recording, tracks)
    track = tracks[hand]
    anchor = recording.get("anchor") or {"p": track["p"][len(track["p"]) // 2].tolist()}
    origin, R = anchor_frame(anchor)
    normal = R[:, 2] if anchor.get("normal") is not None else None

    engaged = engaged_mask(track, origin, normal)
    labels = phases(engaged)
    work = np.array([label == "work" for label in labels])
    if work.sum() < 3:  # nothing marked the work: the whole recording is the motion
        work[:] = True
        labels = ["work"] * len(labels)
    held = track["held"][work]
    motion = classify(track["p"][work], track["q"][work], held, normal)

    # both hands on it at once, the same distance apart throughout: a two-handed hold
    other = next((h for h in tracks if h != hand), None)
    two_handed = None
    if other is not None:
        n = min(len(track["p"]), len(tracks[other]["p"]))
        both = track["held"][:n] & tracks[other]["held"][:n]
        if both.sum() >= rate_hz * 0.5:
            gap = np.linalg.norm(track["p"][:n][both] - tracks[other]["p"][:n][both], axis=1)
            if gap.std() < 0.06:
                two_handed = {"width_m": round(float(np.median(gap)), 3), "seconds": round(float(both.sum() / rate_hz), 2)}

    # object-relative path: p_obj = R^T (p - origin), q_obj = q_R^-1 * q
    rel_p = (track["p"] - origin) @ R
    rel_q = quat_mul(np.broadcast_to(quat_conj(quat_from_matrix(R)), track["q"].shape), track["q"])

    first = int(np.argmax(work))
    lead = track["p"][max(0, first - int(rate_hz * 0.5)) : first + 1]
    approach = _unit(lead[-1] - lead[0]) if len(lead) >= 2 and np.linalg.norm(lead[-1] - lead[0]) > 0.02 else None

    floor_y = recording.get("floor_y")
    heads = np.array([s["head"]["p"] for s in recording["samples"] if s.get("head")], dtype=float)
    reach = {
        "max_height_m": None if floor_y is None else round(float(track["p"][work][:, 1].max() - floor_y), 3),
        "min_height_m": None if floor_y is None else round(float(track["p"][work][:, 1].min() - floor_y), 3),
        "work_extent_m": [round(float(v), 3) for v in np.ptp(track["p"][work], axis=0)],
    }
    if len(heads):
        # how far from the body's vertical axis the hand had to be while working
        head_at = heads[np.clip(np.searchsorted([s["t"] for s in recording["samples"] if s.get("head")],
                                                track["t"][work] + track["t0"]), 0, len(heads) - 1)]  # fmt: skip
        out = track["p"][work] - head_at
        reach["max_from_body_m"] = round(float(np.linalg.norm(out[:, [0, 2]], axis=1).max()), 3)

    # the hand's shape while it worked, and the arm behind it
    from capture import body  # noqa: PLC0415

    t_work = track["t"][work] + track["t0"]
    shape = body.hand_shape(recording, hand, float(t_work[0]), float(t_work[-1]))
    arm = None
    head_rows = [s for s in recording["samples"] if s.get("head")]
    if len(head_rows) >= 2:
        head_t = np.array([s["t"] for s in head_rows], dtype=float)
        at = np.clip(np.searchsorted(head_t, track["t"] + track["t0"]), 0, len(head_rows) - 1)
        head_p = np.array([head_rows[i]["head"]["p"] for i in at], dtype=float)
        head_q = np.array([head_rows[i]["head"]["q"] for i in at], dtype=float)
        height = recording.get("wearer_height_m")
        if height is None and floor_y is not None:
            # eyes are about 0.93 of standing height; a seated wearer makes this an underestimate
            eyes = float(np.percentile(head_p[:, 1], 95) - floor_y)
            # under about 1.35 m the wearer is sitting, and eye height says nothing of their size
            height = float(np.clip(eyes / 0.93, 1.5, 2.0)) if eyes >= 1.35 else None
        arm = body.arm_summary(body.estimate_arm(head_p, head_q, track["p"], hand, height or 1.72), work)

    return {
        "schema": "capture.demo/1",
        "recording": recording.get("id"),
        "chore": recording.get("chore"),
        "site": recording.get("site"),
        "frame": "object: origin at the anchor, z out of its surface, x horizontal; metres",
        "anchor": {"p": origin.tolist(), "rotation": R.tolist(), "label": anchor.get("label")},
        "hand": hand,
        "input": (recording.get("device") or {}).get("input"),
        "rate_hz": rate_hz,
        "duration_s": round(float(track["t"][-1]), 3),
        "path": [
            {"t": round(float(t), 4), "p": [round(float(v), 4) for v in p],
             "q": [round(float(v), 5) for v in q], "phase": label}
            for t, p, q, label in zip(track["t"], rel_p, rel_q, labels)
        ],  # fmt: skip
        "phases": {name: int(sum(label == name for label in labels)) for name in ("approach", "work", "retreat")},
        "motion": motion,
        "two_handed": two_handed,
        "approach_direction": None if approach is None else [round(float(v), 4) for v in approach @ R],
        "reach": reach,
        "hand_shape": shape,
        "arm": arm,
    }


def build_grip(recording: dict, n_per_unit: float = DEFAULT_N_PER_UNIT, rate_hz: float = RATE_HZ) -> dict:
    """`grip.json`: the force band the person used while holding. With a force glove the band
    is its newtons (`source: "glove"`). Otherwise it is the trigger or pinch travel times
    `n_per_unit` (`source: "travel"`): a scale, not a measurement, until it is calibrated."""
    best = None
    for hand in ("left", "right"):
        track = hand_track(recording, hand, rate_hz)
        if track is None:
            continue
        held = track["grip"] >= ENGAGE_GRIP * 0.5
        if held.sum() < 3:
            continue
        measured = np.isfinite(track["force_n"][held]).all()
        values = track["force_n"][held] if measured else track["grip"][held] * n_per_unit
        if best is None or held.sum() > best[0]:
            best = (int(held.sum()), hand, measured, values, track["grip"][held])
    from capture import glove  # noqa: PLC0415

    raw = glove.raw_band(recording)
    if best is None:
        if raw is None:
            raise ValueError("no hand gripped anything in this recording")
        # the glove felt a press the hand tracking did not read as a grip (a flat-handed push)
        return {
            "schema": "capture.grip/1", "recording": recording.get("id"),
            "object": (recording.get("anchor") or {}).get("label"), "hand": raw["hand"],
            "source": "glove_raw", "force_n": None, "glove_raw": raw, "travel": None,
            "scale_n_per_unit": None, "held_s": None,
        }  # fmt: skip
    count, hand, measured, values, travel = best
    if raw is not None and not measured:
        hand = raw["hand"]  # the band that counts is the glove's, so name the gloved hand
    lo, hi = np.percentile(values, [10, 90])
    return {
        "schema": "capture.grip/1",
        "recording": recording.get("id"),
        "object": (recording.get("anchor") or {}).get("label"),
        "hand": hand,
        # "glove": calibrated newtons. "glove_raw": the glove was worn but is not calibrated, so
        # the band that means something is glove_raw (this glove's own units) and force_n is null.
        "source": "glove" if measured else "glove_raw" if raw is not None else "travel",
        "force_n": None if (raw is not None and not measured) else
        {"min": round(float(lo), 2), "max": round(float(hi), 2), "peak": round(float(values.max()), 2)},
        "glove_raw": raw,
        "travel": {"min": round(float(np.percentile(travel, 10)), 3), "max": round(float(np.percentile(travel, 90)), 3)},
        "scale_n_per_unit": None if (measured or raw is not None) else n_per_unit,
        "held_s": round(count / rate_hz, 2),
    }
