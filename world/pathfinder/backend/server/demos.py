"""Demonstration intake: the headset records a person doing a chore and posts it here.

The flow has three parties. Whoever wants a demonstration (the agent, or a person at the
laptop) asks for one with `POST /demos/request`. The headset polls `GET /demos/control`, shows
the request to the wearer, records, and uploads the raw recording with `POST /demos`. It is
saved as `<DATA_DIR>/demos/<id>.json`, which is the inbox `capture.api.latest()` reads, so a
recorded demo keeps working with the headset off.

State is in memory and there is one headset: a single pending request and a single stop flag.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.config import get_settings

router = APIRouter()

SCHEMA = "capture.recording/1"
MAX_SAMPLES = 30 * 60 * 5  # five minutes at 30 Hz
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_started: dict[str, float] = {}  # recording id -> laptop time the headset said it began
_hub = None


def gloves():
    """The glove readers, started on first use from GLOVE_PORTS (none without it). None when
    the capture package or pyserial is not importable."""
    global _hub
    if _hub is None:
        root = str(Path(__file__).resolve().parents[4])
        if root not in sys.path:
            sys.path.append(root)
        try:
            from capture import glove

            _hub = glove.GloveHub.from_env()
        except Exception:  # noqa: BLE001
            _hub = False
    return _hub or None


_pending: dict[str, Any] | None = None
_active: str | None = None
_stop: set[str] = set()


class DemoRequest(BaseModel):
    chore: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="path", pattern="^(path|squeeze)$")
    max_seconds: float = Field(default=30.0, gt=1.0, le=300.0)
    prompt: str | None = Field(default=None, max_length=200)


def folder() -> Path:
    return Path(get_settings().DATA_DIR) / "demos"


def _summary(recording: dict) -> dict | None:
    """What the capture stream reads in it, for the headset's "saved" line. None when the
    capture package is not importable from here or the recording gives no demo."""
    root = str(Path(__file__).resolve().parents[4])  # the repo root, where capture/ lives
    if root not in sys.path:
        sys.path.append(root)
    try:
        from capture import process

        grip = None
        try:
            built = process.build_grip(recording)
            grip = {
                "source": built["source"],
                "force_n": built["force_n"],
                "glove_raw": built.get("glove_raw"),
            }
        except ValueError:
            pass
        if recording.get("kind") == "squeeze":
            return {"grip": grip}
        demo = process.build_demo(recording)
        return {"motion": demo["motion"], "phases": demo["phases"], "two_handed": demo["two_handed"],
                "hand_shape": demo["hand_shape"], "arm": demo["arm"], "grip": grip}  # fmt: skip
    except Exception:  # noqa: BLE001 -- a summary is a courtesy; the recording is saved regardless
        return None


@router.post("/demos/request")
def request_demo(req: DemoRequest) -> dict:
    """Ask the wearer for a demonstration. Replaces a request the headset has not picked up."""
    global _pending
    _pending = {
        "id": f"demo-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}",
        **req.model_dump(),
    }
    return _pending


@router.get("/demos/control")
def control(active: str | None = None) -> dict:
    """The headset's poll. `request` is handed out once. `stop` is true when someone asked for
    the recording named by `active` to end."""
    global _pending, _active
    request, _pending = _pending, None
    if request is not None:
        _active = request["id"]
    return {"request": request, "stop": bool(active and active in _stop)}


@router.post("/demos/stop")
def stop_demo() -> dict:
    """End the recording in progress (the wearer can also end it with the done gesture)."""
    if _active:
        _stop.add(_active)
    return {"stopping": _active}


@router.post("/demos/started")
def started(id: str) -> dict:
    """The headset calls this the moment a recording begins. The laptop time is kept so glove
    readings, which are stamped with the same clock, can be laid onto the recording."""
    if not _ID.match(id):
        raise HTTPException(400, "invalid id")
    _started[id] = time.time()
    return {"id": id, "gloves": [g["hand"] for g in (gloves().status() if gloves() else [])]}


@router.get("/gloves")
def glove_status() -> dict:
    hub = gloves()
    return {"gloves": hub.status() if hub else [], "configured": bool(hub and hub.readers)}


@router.get("/gloves/recent")
def glove_recent(seconds: float = 10.0) -> dict:
    """The last `seconds` of every glove's readings, for the live graph: per glove, `t` (seconds
    before now, negative) and `raw` (five lists, thumb to pinky), thinned to about 50 a second.
    `recording` names the demonstration under way, with how long it has run."""
    seconds = min(max(seconds, 1.0), 60.0)
    now = time.time()
    out = []
    hub = gloves()
    for hand, reader in hub.readers.items() if hub else []:
        times, raw = reader.window(now - seconds, now)
        step = max(1, len(times) // int(seconds * 50))
        out.append({
            "hand": hand, "port": reader.port, "error": reader.error,
            "t": [round(float(v - now), 3) for v in times[::step]],
            "raw": [[int(v) for v in raw[::step, k]] for k in range(5)] if len(times) else [[] for _ in range(5)],
        })  # fmt: skip
    active = next(iter(_started.items()), None)
    return {"gloves": out, "fingers": ["thumb", "index", "middle", "ring", "pinky"], "full_scale": 4095,
            "recording": None if active is None else {"id": active[0], "for_s": round(now - active[1], 1)}}  # fmt: skip


@router.post("/demos")
def save_demo(recording: dict) -> dict:
    """Save a raw recording from the headset."""
    global _active
    if recording.get("schema") != SCHEMA:
        raise HTTPException(422, f"schema must be {SCHEMA}")
    samples = recording.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise HTTPException(422, "a recording needs at least two samples")
    if len(samples) > MAX_SAMPLES:
        raise HTTPException(413, "recording too long")
    demo_id = str(recording.get("id") or "")
    if not _ID.match(demo_id):
        raise HTTPException(422, "id must be letters, digits, dot, dash or underscore")
    duration = float(samples[-1].get("t", 0.0)) - float(samples[0].get("t", 0.0))
    merged = {}
    hub = gloves()
    if hub and hub.readers:
        # without the headset's start call, the start is the upload time less the recording
        begun = _started.pop(demo_id, None)
        merged = hub.merge(recording, begun if begun is not None else time.time() - duration - 0.2)
        recording["glove_sync"] = "start call" if begun is not None else "upload time (approximate)"
    out = folder()
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".{demo_id}.json.tmp"
    tmp.write_text(json.dumps(recording), encoding="utf8")
    tmp.replace(out / f"{demo_id}.json")
    _stop.discard(demo_id)
    if _active == demo_id:
        _active = None
    return {"id": demo_id, "samples": len(samples), "duration_s": round(duration, 2),
            "gloves": merged, "read_as": _summary(recording)}  # fmt: skip


@router.get("/demos")
def list_demos() -> list[dict]:
    """Saved recordings, newest first."""
    out = folder()
    if not out.is_dir():
        return []
    rows = []
    for path in sorted(out.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rec = json.loads(path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({"id": path.stem, "chore": rec.get("chore"), "kind": rec.get("kind"),
                     "site": rec.get("site"), "samples": len(rec.get("samples") or [])})  # fmt: skip
    return rows


@router.get("/demos/{demo_id}")
def get_demo(demo_id: str) -> dict:
    if not _ID.match(demo_id):
        raise HTTPException(400, "invalid id")
    path = folder() / f"{demo_id}.json"
    if not path.is_file():
        raise HTTPException(404, "no such recording")
    return json.loads(path.read_text(encoding="utf8"))


@router.get("/demos/{demo_id}/read")
def read_demo(demo_id: str) -> dict:
    """What the capture stream reads in a saved recording: 404 until the headset has uploaded it."""
    recording = get_demo(demo_id)
    samples = recording.get("samples") or []
    duration = (
        float(samples[-1].get("t", 0.0)) - float(samples[0].get("t", 0.0))
        if len(samples) > 1
        else 0.0
    )
    return {"id": demo_id, "chore": recording.get("chore"), "kind": recording.get("kind"),
            "duration_s": round(duration, 2), "read_as": _summary(recording)}  # fmt: skip
