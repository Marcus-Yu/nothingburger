"""A back-and-forth pattern over a patch of ground (mowing passes), as poses for a `navigate` task.

The route planner drives a navigate task's `waypoints` in order (nav/route.py); this module makes them.
"""
from __future__ import annotations

import math

LANE_M = 0.5      # distance between passes: the width of deck assumed (the catalog has no mowing deck)
BORDER_M = 0.7    # the passes stop this far from the area's edge, so the base can turn without touching a fence


def _cuts(polygon, axis, at):
    """Where the line (coordinate `axis` == at) crosses the polygon: sorted values of the other coordinate."""
    out = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[axis] - at) * (b[axis] - at) < 0:
            f = (at - a[axis]) / (b[axis] - a[axis])
            out.append(a[1 - axis] + f * (b[1 - axis] - a[1 - axis]))
    return sorted(out)


def passes(area, keep_out=(), lane=LANE_M, border=BORDER_M) -> list:
    """Back-and-forth passes over a polygon: [[x, y, yaw]], two poses a pass (its ends), passes `lane` apart
    along the polygon's longer side and stopping `border` short of every edge. `keep_out` boxes
    [x0, y0, x1, y1] (already grown by the clearance wanted) cut a pass in two."""
    xs, ys = [p[0] for p in area], [p[1] for p in area]
    along = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1   # passes run along this coordinate
    across = 1 - along
    lo, hi = min(p[across] for p in area) + border, max(p[across] for p in area) - border
    if hi < lo:
        return []
    n = int(math.floor((hi - lo) / lane + 1e-9)) + 1
    start = lo + ((hi - lo) - (n - 1) * lane) / 2
    out, forward = [], True
    for k in range(n):
        at = start + k * lane
        spans = []
        for edge in (at - border + 0.01, at, at + border - 0.01):  # the pass must clear the edge over its whole width
            c = _cuts(area, across, edge)
            spans.append([(c[i] + border, c[i + 1] - border) for i in range(0, len(c) - 1, 2)])
        if not all(spans):
            continue
        a, b = max(s[0][0] for s in spans), min(s[-1][1] for s in spans)
        pieces = [(a, b)] if b - a > 0.5 else []
        for x0, y0, x1, y1 in keep_out:
            klo, khi = (x0, x1) if along == 0 else (y0, y1)
            plo, phi = (y0, y1) if along == 0 else (x0, x1)
            if plo < at < phi:
                pieces = [q for p0, p1 in pieces for q in ((p0, min(p1, klo)), (max(p0, khi), p1)) if q[1] - q[0] > 0.5]
        for p0, p1 in (pieces if forward else [(q1, q0) for q0, q1 in reversed(pieces)]):
            yaw = (0.0 if p1 > p0 else math.pi) if along == 0 else (math.pi / 2 if p1 > p0 else -math.pi / 2)
            for v in (p0, p1):
                out.append([round(v, 2), round(at, 2), round(yaw, 4)] if along == 0 else [round(at, 2), round(v, 2), round(yaw, 4)])
        if pieces:
            forward = not forward
    return out


def task(area: dict, id_: str = "t1") -> dict | None:
    """The navigate task that covers one of a world's `areas` ({"id", "polygon", "keep_out"?}), or None when
    the area is too small for a single pass."""
    w = passes(area["polygon"], area.get("keep_out") or ())
    if not w:
        return None
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(w[::2], w[1::2]))
    lines = len({p[0 if w[0][1] != w[1][1] else 1] for p in w})
    return {"id": id_, "skill": "navigate", "anchor": None, "object": None, "carries": False, "pattern": "coverage",
            "area": area["id"], "lane_m": LANE_M, "border_m": BORDER_M, "waypoints": w,
            "note": f"{lines} lines {LANE_M} m apart, driven as {len(w) // 2} passes (a line that meets a keep-out is two), "
                    f"{round(length, 1)} m of cutting; a {BORDER_M} m border is left for a trimmer. "
                    "The catalog has no mowing deck: this plans where the base drives, and the deck is assumed."}
