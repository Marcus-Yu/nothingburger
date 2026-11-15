"""One video of a run planned on an aerial survey, from the data to the robot doing the job.

    python world/scenarios/tools/aerial_story.py runs/gallery/kerbside_palmetto [--out docs/media/aerial/kerbside_palmetto-full.mp4]

The run's world must lie on surveyed ground (`ground.height` in world.json) and the run must have been made with
`--frames --walkthrough`. The video is 960 x 540 at the film's frame rate:

  1  the job, over the aerial photo
  2  the survey: how high everything stands above the ground
  3  what the robot may drive on, as nav reads it from that survey (nav/grid.py, ground_blocked)
  4  the planned route drawn over it, beside the route the same planner gives when the survey is taken away
  5  the film (frames/walkthrough.mp4) with a caption for each step and a map showing where the robot is
  6  what was planned, and what the video is not

Everything drawn comes from the run folder and the survey. Only the base's route reads the survey: arm motion is
checked against the world's obstacle boxes, not against it. Needs ffmpeg and Pillow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from agent.tools import viz  # noqa: E402  (the film's own timeline, so the map follows the same frames)
from nav import grid as G  # noqa: E402

W, H = viz.WALK_W, viz.WALK_H
FPS = viz.WALK_FPS
MARGIN_M = 2.5
INK, PAPER, ACCENT, BLOCK = (23, 20, 15), (255, 253, 250), (255, 122, 26), (226, 60, 50)
FONTS = ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def font(size: int):
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Map:
    """The survey over the world's rooms plus a margin, as pictures and as a way from metres to pixels."""

    def __init__(self, world: dict, width: int):
        g = world["ground"]
        self.x0, self.y0, self.x1, self.y1 = g["extent"]
        pts = [p for r in world["rooms"] for p in r["polygon"]]
        self.cx0 = max(self.x0, min(p[0] for p in pts) - MARGIN_M)
        self.cx1 = min(self.x1, max(p[0] for p in pts) + MARGIN_M)
        self.cy0 = max(self.y0, min(p[1] for p in pts) - MARGIN_M)
        self.cy1 = min(self.y1, max(p[1] for p in pts) + MARGIN_M)
        self.w = width
        self.h = round(width * (self.cy1 - self.cy0) / (self.cx1 - self.cx0))
        photo = Image.open(REPO / g["image"]).convert("RGB")
        sx, sy = photo.size[0] / (self.x1 - self.x0), photo.size[1] / (self.y1 - self.y0)
        box = (round((self.cx0 - self.x0) * sx), round((self.y1 - self.cy1) * sy), round((self.cx1 - self.x0) * sx), round((self.y1 - self.cy0) * sy))
        self.photo = photo.crop(box).resize((self.w, self.h), Image.LANCZOS)
        height, _, _ = G.ground_raster(world)
        self.height = np.asarray(Image.fromarray(height.astype(np.float32)).crop(box).resize((self.w, self.h), Image.BILINEAR))
        xs = self.cx0 + (np.arange(self.w) + 0.5) / self.w * (self.cx1 - self.cx0)
        ys = self.cy1 - (np.arange(self.h) + 0.5) / self.h * (self.cy1 - self.cy0)
        X, Y = np.meshgrid(xs, ys)
        grid = G.from_world(world, G.PREPASS_BAND_M)       # exactly what the planner sees: rooms, obstacles and the survey
        self.blocked = grid.occupied_at(X, Y)
        self.rooms = [[self.px(p) for p in r["polygon"]] for r in world["rooms"]]

    def px(self, p):
        return ((p[0] - self.cx0) / (self.cx1 - self.cx0) * self.w, (self.cy1 - p[1]) / (self.cy1 - self.cy0) * self.h)

    def survey(self) -> Image.Image:
        """Height above the ground, dark to bright, over a dimmed photo."""
        t = np.clip(self.height / 6.0, 0, 1)[..., None]
        ramp = (1 - t) * np.array([28, 30, 60]) + t * np.array([255, 214, 90])
        base = np.asarray(self.photo, float) * 0.25
        return Image.fromarray(np.where(self.height[..., None] > G.GROUND_STEP_M, ramp, base + 20).astype(np.uint8))

    def drivable(self) -> Image.Image:
        """The photo with everything the planner will not drive on in red."""
        a = np.asarray(self.photo, float)
        a[self.blocked] = a[self.blocked] * 0.30 + np.array(BLOCK) * 0.70
        return Image.fromarray(a.astype(np.uint8))


def route_points(route: dict) -> list:
    """The route as one polyline of [x, y], leg after leg."""
    pts = []
    for leg in route["legs"]:
        pts += [w[:2] for w in leg["waypoints"]]
    return pts


def through_obstacles(world: dict, pts: list) -> float:
    """Metres of a route that lie on ground the survey shows as blocked."""
    hit = 0.0
    for a, b in zip(pts, pts[1:]):
        a, b = np.array(a, float), np.array(b, float)
        n = max(2, int(np.linalg.norm(b - a) / 0.05))
        s = a + (b - a) * np.linspace(0, 1, n)[:, None]
        hit += float(G.ground_blocked(world, s[:, 0], s[:, 1]).mean()) * float(np.linalg.norm(b - a))
    return hit


def without_survey(world: dict, build: dict, requirements: dict, route: dict):
    """(route points, metres, metres through surveyed obstacles) for the same stops planned with the survey taken
    away: what the planner would do if all it had was the photo as a picture."""
    from nav import api as nav

    blind = {**world, "ground": {k: v for k, v in world["ground"].items() if k != "height"}}
    r = nav.plan(blind, build, requirements=requirements, standoffs=route["standoffs"])
    pts = route_points(r)
    return pts, round(sum(leg.get("length_m") or 0 for leg in r["legs"]), 1), round(through_obstacles(world, pts), 1)


def draw_route(img: Image.Image, m: Map, pts: list, upto: float = 1.0, width: int = 4, colour=None) -> None:
    if len(pts) < 2:
        return
    seg = np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1)
    want, done, line = float(seg.sum()) * upto, 0.0, [m.px(pts[0])]
    for a, b, length in zip(pts, pts[1:], seg):
        if done + length >= want:
            f = (want - done) / max(length, 1e-9)
            line.append(m.px([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]))
            break
        line.append(m.px(b))
        done += length
    ImageDraw.Draw(img).line(line, fill=colour or ACCENT, width=width, joint="curve")


def marks(img: Image.Image, m: Map, world: dict, tasks: list, way_out, small: bool = False) -> None:
    d = ImageDraw.Draw(img)
    r = 5 if small else 9
    anchors = {a["id"]: a for a in world.get("anchors", [])}
    for k, t in enumerate(tasks):
        a = anchors.get(t.get("anchor"))
        if not a:
            continue
        x, y = m.px(a["point"])
        d.ellipse([x - r, y - r, x + r, y + r], fill=INK, outline=PAPER, width=2)
        if not small:
            d.text((x, y), str(k + 1), fill=PAPER, font=font(12), anchor="mm")
    x, y = m.px(world["dock"]["pose"])
    d.ellipse([x - r, y - r, x + r, y + r], outline=PAPER, width=3)
    if way_out:
        x, y = m.px(way_out)
        d.rectangle([x - r, y - r, x + r, y + r], fill=PAPER, outline=INK, width=2)


def card(picture: Image.Image, title: str, lines: list, step: str = "") -> Image.Image:
    """A frame: the picture across the top, the words under it."""
    frame = Image.new("RGB", (W, H), PAPER)
    frame.paste(picture, ((W - picture.size[0]) // 2, 0))
    d = ImageDraw.Draw(frame)
    y = picture.size[1] + 14
    if step:
        d.text((28, y + 4), step, fill=ACCENT, font=font(13))
    d.text((28 + (58 if step else 0), y), title, fill=INK, font=font(22))
    for k, line in enumerate(lines):
        d.text((28, y + 34 + 21 * k), line, fill=(70, 64, 56), font=font(15))
    return frame


def caption(label: str, tasks: list) -> str:
    """A film chapter in plain words: "drive: t1 to way_out (carrying)" -> "Carrying bag 1 to the kerb"."""
    n = {t["id"]: k + 1 for k, t in enumerate(tasks)}
    thing = (tasks[0].get("object") or "it").replace("_", " ").replace("trash ", "") if tasks else "it"
    if label.startswith("drive:"):
        a, _, b = label[len("drive: "):].replace(" (carrying)", "").partition(" to ")
        if b == "way_out":
            return f"Carrying {thing} {n.get(a, '')} to the kerb"
        if b == "dock":
            return "Driving back to the dock"
        return f"Driving to {thing} {n.get(b, '')}, round what the survey shows in the way"
    tid, _, what = label.partition(": ")
    return {"reach in": f"Reaching for {thing} {n.get(tid, '')}", "pick": f"Picking up {thing} {n.get(tid, '')}",
            "fold away": f"Lifting {thing} {n.get(tid, '')} clear"}.get(what, label)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    run = a.run.resolve()
    load = lambda n: json.loads((run / n).read_text())  # noqa: E731
    world, route, build, traj = load("world.json"), load("route.json"), load("build.json"), load("trajectory.json")
    requirements = load("requirements.json")
    tasks, design = load("tasks.json")["tasks"], load("design.json")
    film = run / "frames" / "walkthrough.mp4"
    if not (world.get("ground") or {}).get("height") or not film.exists():
        print("this run has no surveyed ground or no film (make it with --frames --walkthrough)")
        return 2
    job = next((json.loads(line).get("job") for line in (run / "events.jsonl").read_text().splitlines()[:1]), None)
    job = job or (REPO / "world" / "scenarios" / f"{world['id']}.job.txt").read_text().strip()
    out = a.out or run / "frames" / "story.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    big = Map(world, W)
    way_out, _ = G.way_out_point(world)
    pts = route_points(route)
    metres = round(sum(leg.get("length_m") or 0 for leg in route["legs"]), 1)
    free = round(float((~big.blocked).mean()) * (big.cx1 - big.cx0) * (big.cy1 - big.cy0))
    parts = design["parts"]
    src = world["ground"]["source"].split("collection ")[-1]
    same = (world["ground"].get("dsm") or {}).get("collection") == src
    blind_pts, blind_m, blind_hit = without_survey(world, build, requirements, route)

    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", str(out)],
                           stdin=subprocess.PIPE)

    def hold(frame: Image.Image, seconds: float) -> None:
        raw = frame.tobytes()
        for _ in range(round(seconds * FPS)):
            enc.stdin.write(raw)

    words = job if len(job) < 100 else job[:job.rfind(" ", 0, 100)] + " …"
    more = job[len(words) - 2:].strip() if len(job) >= 100 else ""
    photo = big.photo.copy()
    hold(card(photo, "The job", [words] + ([more] if more else []) + [f"Vexcel aerial photo, {world['ground']['m_per_px']} m a pixel ({src})."], "1"), 3.5)
    hold(card(big.survey(), "The survey", [f"Vexcel’s surface model{', from the same collection as the photo' if same else ''}: how high everything stands above the ground.",
                                           "Roofs, trees, fences and each parked vehicle are in it. Brighter is taller, up to 6 m."], "2"), 4)
    hold(card(big.drivable(), "What the robot may drive on", [f"Red: anything standing more than {G.GROUND_STEP_M} m high, and the road beyond the kerb line.",
                                                              f"About {free} m² is left. No obstacle was traced: the planner reads the survey. Only the work area, kerb line and bags were set by hand."], "3"), 4.5)
    base = big.drivable()
    for k in range(round(3.5 * FPS)):   # first what the planner does with the photo as a picture only
        img = base.copy()
        draw_route(img, big, blind_pts, min(1.0, (k + 1) / (2.0 * FPS)), colour=PAPER)
        marks(img, big, world, tasks, way_out)
        enc.stdin.write(card(img, "Without the survey", [f"The same planner and the same stops, with the heights taken away: {blind_m} m,",
                                                         f"of which {blind_hit} m goes straight through things the survey shows standing there."], "4").tobytes())
    for k in range(round(4.5 * FPS)):
        img = base.copy()
        draw_route(img, big, blind_pts, 1.0, width=2, colour=PAPER)
        draw_route(img, big, pts, min(1.0, (k + 1) / (2.6 * FPS)))
        marks(img, big, world, tasks, way_out)
        enc.stdin.write(card(img, "With the survey", [f"{metres} m in {len(route['legs'])} legs, none of it through an obstacle: out to each bag, to the kerb, back to the dock.",
                                                      "Orange: the route used. White: the route without the survey. Dots: bags. Square: kerb. Ring: dock."], "5").tobytes())

    # the film, with a caption for each chapter and a map that follows the robot
    frames, chapters = viz._timeline(build, route, traj)
    mini = Map(world, 330)
    inset = mini.drivable()
    draw_route(inset, mini, pts, 1.0, width=2)
    marks(inset, mini, world, tasks, way_out, small=True)
    dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(film), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    labels, at = [caption(label, tasks) for _, label in chapters], [i for i, _ in chapters]
    n = 0
    while True:
        raw = dec.stdout.read(W * H * 3)
        if len(raw) < W * H * 3:
            break
        frame = Image.frombytes("RGB", (W, H), raw)
        d = ImageDraw.Draw(frame, "RGBA")
        pose = frames[min(n, len(frames) - 1)][0]
        m = inset.copy()
        x, y = mini.px(pose)
        ImageDraw.Draw(m).ellipse([x - 5, y - 5, x + 5, y + 5], fill=PAPER, outline=INK, width=2)
        d.rectangle([W - mini.w - 22, 14, W - 14, 22 + mini.h], fill=(*PAPER, 235))
        frame.paste(m, (W - mini.w - 18, 18))
        which = max((k for k, i in enumerate(at) if i <= n), default=0)
        d.rectangle([0, H - 46, W, H], fill=(*INK, 190))
        d.text((24, H - 34), labels[which] if labels else "", fill=PAPER, font=font(19))
        d.text((W - 24, H - 32), "the plan played back, not physics", fill=(220, 214, 204), font=font(13), anchor="ra")
        enc.stdin.write(frame.tobytes())
        n += 1
    dec.wait()

    done = base.copy()
    draw_route(done, big, pts, 1.0)
    marks(done, big, world, tasks, way_out)
    hold(card(done, "What was planned", [f"{len(tasks)} bags to the kerb, {metres} m, by {parts['base']} + {parts['arm']} + {parts['gripper']} (${design['price_usd']:,}).",
                                         "The plan is played back: no contact or forces are simulated. The bags and where they stand are assumed."], "6"), 4.5)
    enc.stdin.close()
    if enc.wait() != 0:
        print("ffmpeg failed")
        return 1
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {n} film frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
