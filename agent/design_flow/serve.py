"""The design workflow over HTTP, for the studio (frontend/). Binds to 127.0.0.1.

    uv run --env-file .env python -m agent.design_flow.serve            # port 8020
    uv run python -m agent.design_flow.serve --standin                  # no API key: rule classifier, scenario tasks

    POST /sessions              {"world": space id, "job": text}  -> {"session_id", "status": "working"}
    GET  /sessions/<id>         -> {"session_id", "status": "working" | "waiting" | "done" | "error",
                                    "phase", "step": {"kind", "data"} | null, "error"}
    POST /sessions/<id>/reply   {"recordings"?: {"demo"?, "grip"?}}   answers a demo step; capture fills the rest
    POST /sessions/<id>/retry   reruns the step that failed
    GET  /runs/studio/<run>/snapshot.json   the Robot Design page's snapshot of a finished run
    GET  /runs/studio/<run>/events?from=N   the run's events.jsonl from byte N: {"events": [...], "next": N}
    GET  /catalog/names                     {part id: name} for every catalog card
    GET  /room.html?run=runs/studio/<run>   the run played inside the scanned room (needs world/_scans/<world>/room.glb)

Each reply runs in a thread, because the design step (the design and pathing pipeline) takes minutes:
the studio polls GET /sessions/<id>. Sessions live in memory and are lost on restart.

The classify step is SubQ Snap 1.2 first (SUBQ_API_KEY), then Claude Sonnet for what Snap can't settle
(see agent/design_flow/fast.py). --standin is for trying the flow without ANTHROPIC_API_KEY: a keyword
classifier stands in for Sonnet behind Snap, and the pipeline uses the scenario's own task list instead of
reading the job. Its answers say so.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from langchain_core.runnables import RunnableLambda

from agent.design_flow.api import DesignWorkflow, SessionError
from agent.design_flow import pipeline
from agent.design_flow.pipeline import REPO, RUNS, NoWorld
from agent.design_flow.schemas import TaskAssessment

PORT = 8020

# The --standin classifier: the first keyword group a task matches names its skill.
STANDIN_SKILLS = [
    (("mow", "cut the grass", "cut the lawn"), "mow_lawn", "Mow the lawn."),
    (("trash", "garbage"), "take_out_garbage", "Take the trash out."),
    (("wipe", "clean", "table", "counter", "surface"), "wipe_table", "Wipe the tables down."),
    (("bottle", "pick", "carry", "take out", "move", "bin", "container", "bring", "parcel", "towel", "deliver"), "move_bin", "Pick it up and carry it out."),
    (("bulb", "light", "lamp"), "change_bulb", "Change the light bulb."),
    (("open", "box", "lid"), "open_box", "Open it."),
]


UNKNOWN_WORDS = ("disposal", "hex", "nut", "radiator", "pilot", "filter", "latch", "heater", "pipe")


def standin_classifier():
    def classify(request: dict) -> TaskAssessment:
        text = request["task"].lower()
        if any(w in text for w in UNKNOWN_WORDS):  # caretaker jobs the keywords below would misread
            return TaskAssessment(valid=False, skill="", reason="The stand-in classifier doesn’t know this chore; with ANTHROPIC_API_KEY set, Claude would read it.")
        for words, skill, reason in STANDIN_SKILLS:
            if any(w in text for w in words):
                return TaskAssessment(valid=True, skill=skill, reason=f"{reason} (stand-in classifier)")
        return TaskAssessment(valid=False, skill="", reason="The stand-in classifier doesn’t know this chore; with ANTHROPIC_API_KEY set, Claude would read it.")
    return RunnableLambda(classify, name="stand-in classifier")


CTYPES = {".json": "application/json", ".jsonl": "application/x-ndjson", ".glb": "model/gltf-binary",
          ".bin": "application/octet-stream", ".png": "image/png", ".mp4": "video/mp4", ".xml": "application/xml"}


def catalog_names() -> dict:
    names = {}
    for f in sorted((REPO / "catalog").glob("*/*.json")):
        try:
            card = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if card.get("id") and card.get("name"):
            names[card["id"]] = card["name"]
    return names


def read_events(path: Path, start: int) -> dict:
    """Whole lines of events.jsonl from byte `start`; a line still being written waits for the next read."""
    if not path.is_file():
        return {"events": [], "next": 0}
    with path.open("rb") as f:
        f.seek(start)
        data = f.read()
    end = data.rfind(b"\n") + 1
    events = []
    for line in data[:end].splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"events": events, "next": start + end}


class Sessions:
    def __init__(self, workflow: DesignWorkflow):
        self.workflow = workflow
        self.lock = threading.Lock()
        self.by_id: dict[str, dict] = {}

    def view(self, sid: str) -> dict:
        with self.lock:
            if sid not in self.by_id:
                raise KeyError(sid)
            view = {"session_id": sid, **self.by_id[sid]}
        if pipeline.ACTIVE.get(sid):
            view["run"] = pipeline.ACTIVE[sid]  # the run folder, as soon as the design step starts writing it
        try:  # the classify verdict, and which node is running: a learned skill goes straight to design
            snap = self.workflow._snapshot(sid)
            view["assessment"] = snap.values.get("assessment")
            if view.get("status") == "working" and "design" in (snap.next or ()):
                view["phase"] = "design"
        except Exception:  # noqa: BLE001 - both are niceties
            pass
        return view

    def _set(self, sid: str, **fields) -> None:
        with self.lock:
            self.by_id.setdefault(sid, {}).update(fields)

    def _work(self, sid: str, phase: str, call) -> None:
        self._set(sid, status="working", phase=phase, error=None)

        def go():
            try:
                step = call()
            except (SessionError, NoWorld) as e:
                self._set(sid, status="error", error=str(e))
                return
            except Exception as e:  # noqa: BLE001 - shown to the user, who can retry
                self._set(sid, status="error", error=f"{type(e).__name__}: {e}")
                return
            done = step.kind == "design"
            self._set(sid, status="done" if done else "waiting", phase=step.kind, step={"kind": step.kind, "data": step.data})

        threading.Thread(target=go, daemon=True).start()

    def start(self, world: str, job: str) -> str:
        step = self.workflow.start(world=world)
        sid = step.session_id
        self._set(sid, world=world, job=job, step=None)
        self._work(sid, "classify", lambda: self.workflow.reply(sid, job))
        return sid

    def reply(self, sid: str, recordings: dict | None) -> None:
        self.view(sid)
        self._work(sid, "design", lambda: self.workflow.reply(sid, recordings or None))

    def retry(self, sid: str) -> None:
        self.view(sid)
        self._work(sid, "retry", lambda: self.workflow.retry(sid))


def make_handler(sessions: Sessions, standin: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet: the studio polls
            pass

        def _send(self, code: int, body: dict | bytes, ctype: str = "application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("content-length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            path = unquote(urlparse(self.path).path).rstrip("/")
            if path == "/health":
                return self._send(200, {"ok": True, "standin": standin,
                                        "model": bool(os.environ.get("ANTHROPIC_API_KEY")) and not standin})
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "sessions":
                try:
                    return self._send(200, sessions.view(parts[1]))
                except KeyError:
                    return self._send(404, {"detail": "unknown session"})
            if path == "/catalog/names":
                return self._send(200, catalog_names())
            if path.startswith("/runs/studio/") and path.endswith("/events"):
                folder = (REPO / path.lstrip("/")[: -len("/events")]).resolve()
                if not folder.is_relative_to(RUNS.resolve()):
                    return self._send(404, {"detail": "not found"})
                q = parse_qs(urlparse(self.path).query)
                return self._send(200, read_events(folder / "events.jsonl", int((q.get("from") or ["0"])[0])))
            if path == "/room.html":  # the real-room 3D page (web/viewer/room.html), for a studio run
                return self._send(200, (REPO / "web" / "viewer" / "room.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/scans/") and path.endswith("/room.glb"):  # the scanned room's mesh (world/_scans, not committed)
                file = (REPO / "world" / "_scans" / path[len("/scans/"):]).resolve()
                if file.is_file() and file.name == "room.glb":
                    return self._send(200, file.read_bytes(), "model/gltf-binary")
                return self._send(404, {"detail": "no room mesh on this machine"})
            if path.startswith("/runs/studio/"):  # a studio run's files: snapshot, events, world, the robot export
                file = (REPO / path.lstrip("/")).resolve()
                if file.is_relative_to(RUNS.resolve()) and file.is_file():
                    return self._send(200, file.read_bytes(), CTYPES.get(file.suffix, "application/octet-stream"))
            return self._send(404, {"detail": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/")
            parts = path.strip("/").split("/")
            try:
                body = self._body()
            except json.JSONDecodeError:
                return self._send(400, {"detail": "body is not JSON"})
            try:
                if parts == ["sessions"]:
                    job = (body.get("job") or "").strip()
                    if not job:
                        return self._send(400, {"detail": "job is empty"})
                    sid = sessions.start(body.get("world") or "rabinowitz-hall", job)
                    return self._send(200, sessions.view(sid))
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] in ("reply", "retry"):
                    if parts[2] == "reply":
                        sessions.reply(parts[1], body.get("recordings"))
                    else:
                        sessions.retry(parts[1])
                    return self._send(200, sessions.view(parts[1]))
            except KeyError:
                return self._send(404, {"detail": "unknown session"})
            return self._send(404, {"detail": "not found"})

    return Handler


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent.design_flow.serve", description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--standin", action="store_true",
                    help="no API key: keyword classifier, and the scenario's task list instead of reading the job")
    a = ap.parse_args(argv)
    options = {}
    if a.standin:
        os.environ["STUDIO_STANDIN_TASKS"] = "1"
        from agent.design_flow.graph import default_classifier

        options["classifier"] = default_classifier(fallback=standin_classifier())  # Snap first, keywords after
    sessions = Sessions(DesignWorkflow(**options))
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(sessions, a.standin))
    print(f"design workflow: http://127.0.0.1:{a.port}" + (" (stand-in classifier and tasks)" if a.standin else ""), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
