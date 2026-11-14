"""The demo flow's server side: the website, the worlds it can show, and a stand-in planner.

`GET /web/` serves the repo's `web/` folder. `GET /worlds` lists the spaces the site can open.
`POST /plan` answers with a plan for a job in a world.

The planner here is a STAND-IN: a lookup table keyed on words in the job, so the website's flow
can be clicked through. TODO(Shao, stream A): replace `make_plan` with the planning agent. Keep
the response shape, or change it together with `web/app.js`.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.config import get_settings

router = APIRouter()

REPO = Path(__file__).resolve().parents[4]
WEB_DIR = REPO / "web"


class PlanRequest(BaseModel):
    world: str = Field(min_length=1, max_length=80)
    job: str = Field(min_length=1, max_length=400)


# What a demonstration is needed for, per kind of job. `match` words are looked for in the job.
_JOBS = [
    {
        "id": "carry-out",
        "match": ["container", "outside", "carry", "crate", "move a bin", "move the bin"],
        "title": "Carry a container outside",
        "steps": [
            "Find the container and measure it",
            "Grip it on both sides without crushing it",
            "Lift it and carry it to the door (inside: Matterport)",
            "Check the door is wide enough for robot and container",
            "Cross to the drop-off point outside (outside: Vexcel)",
            "Set it down and let go",
        ],
        "demos": [
            {
                "chore": "lift container",
                "kind": "path",
                "why": "where to hold it, how far apart the hands are and how high to lift",
            },
            {
                "chore": "hold container",
                "kind": "squeeze",
                "why": "the grip that carries it without crushing it",
            },
        ],
        "outside": True,
    },
    {
        "id": "light-bulb",
        "match": ["bulb", "lamp", "light"],
        "title": "Change a light bulb",
        "steps": [
            "Find the fixture and its height",
            "Drive under it and raise the arm",
            "Hold the bulb without breaking it and unscrew",
            "Fit the new bulb and screw it in",
        ],
        "demos": [
            {
                "chore": "unscrew bulb",
                "kind": "path",
                "why": "the reach, the approach and how far to turn",
            },
            {
                "chore": "hold bulb",
                "kind": "squeeze",
                "why": "the grip that neither slips nor breaks the glass",
            },
        ],
    },
    {
        "id": "wipe",
        "match": ["wipe", "clean", "counter", "table"],
        "title": "Wipe a surface",
        "steps": [
            "Find the surface and its edges",
            "Reach over it",
            "Press and sweep in passes",
            "Lift off",
        ],
        "demos": [
            {"chore": "wipe table", "kind": "path", "why": "the patch, the stroke and the press"}
        ],
    },
    {
        "id": "trash",
        "match": ["trash", "bag", "garbage", "bin"],
        "title": "Take out a trash bag",
        "steps": ["Find the bin", "Grip the bag", "Lift it clear", "Carry it along the route out"],
        "demos": [
            {
                "chore": "lift trash bag",
                "kind": "path",
                "why": "where to hold and how high to lift",
            },
            {
                "chore": "hold trash bag",
                "kind": "squeeze",
                "why": "the grip that holds without ripping",
            },
        ],
    },
    {
        "id": "open-box",
        "match": ["box", "lid", "open", "door", "cabinet"],
        "title": "Open a box or a door",
        "steps": ["Find the handle or edge", "Grip it", "Swing it about its hinge", "Let go"],
        "demos": [
            {"chore": "open box", "kind": "path", "why": "the hinge line and how far it swings"}
        ],
    },
    {
        "id": "replace",
        "match": ["replace", "fit", "swap", "new ", "install"],
        "title": "Replace a part",
        "steps": [
            "Measure the opening in the scan",
            "Search the shops for parts that fit",
            "Place the best fit in the scan to check it",
        ],
        "demos": [],
        "parts": True,
    },
]


def make_plan(world: str, job: str) -> dict:
    """STAND-IN planner. TODO(Shao): the planning agent goes here."""
    text = job.lower()
    best = max(_JOBS, key=lambda j: sum(word in text for word in j["match"]))
    matched = any(word in text for word in best["match"])
    return {
        "id": f"plan-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}",
        "world": world,
        "job": job,
        "planner": "stand-in lookup table (the planning agent is not wired in yet)",
        "understood_as": best["title"] if matched else None,
        "steps": best["steps"] if matched else ["The stand-in planner has no entry for this job."],
        "demos": best["demos"] if matched else [],
        "parts": bool(matched and best.get("parts")),
        "outside": bool(matched and best.get("outside")),
    }


@router.post("/plan")
def plan(req: PlanRequest) -> dict:
    return make_plan(req.world, req.job)


@router.get("/worlds")
def worlds() -> list[dict]:
    """The spaces the site can open: `web/worlds.json`, each marked with whether a scene package
    for it is on this server (so the headset can load it too)."""
    try:
        listed = json.loads((WEB_DIR / "worlds.json").read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"web/worlds.json unreadable: {exc}") from exc
    scenes = Path(get_settings().SCENE_DIR)
    for world in listed:
        site = world.get("site")
        world["in_headset"] = bool(site and (scenes / site / "scene.json").is_file())
        # the outside: a Vexcel scene package on this server, shown on the site as a 3D model
        world["outside_mesh"] = None
        try:
            outside = json.loads(
                (scenes / world["outside"] / "scene.json").read_text(encoding="utf8")
            )
            world["outside_mesh"] = f"/scenes/{world['outside']}/{outside['mesh']['file']}"
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return listed


@router.get("/web-config")
def web_config() -> dict:
    """What the page needs from the server's environment. The Showcase SDK key is a browser
    key (it is sent to Matterport from the page), kept in .env so it is not committed."""
    settings = get_settings()
    extra = {k.upper(): v for k, v in (settings.model_extra or {}).items()}
    return {"matterport_sdk_key": extra.get("MATTERPORT_SDK_KEY") or None}
