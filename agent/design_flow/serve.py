"""The design workflow over HTTP, for the studio (frontend/). Binds to 127.0.0.1.

    uv run --env-file .env python -m agent.design_flow.serve            # port 8020
    uv run python -m agent.design_flow.serve --standin                  # no API key: rule classifier, scenario tasks

    POST /sessions              {"world": space id, "job": text, "options"?: steering}  -> the session's view
    GET  /sessions/<id>         -> {"session_id", "status": "working" | "waiting" | "done" | "error" | "stopped",
                                    "phase", "step": {"kind", "data"} | null, "error", "run"?, "options"?, "previous"?}
    POST /sessions/<id>/stop    stops the running design: status "stopped", phase "design", error "Stopped by you";
                                "run" stays set. 409 when nothing is running. -> the view
    POST /sessions/<id>/steer   {"job"?, "exclude"?: [{slot: part}], "require"?: {slot: part}, "max_price_usd"?: number}
                                stops the design if running, then starts a new session in the same world with the job
                                (the old one if not given) and these options -> the new view, with "previous": old id
    POST /sessions/<id>/reply   {"recordings"?: {"demo"?, "grip"?}}   answers a demo step; capture fills the rest
                                {"answer": {"sid"} | text}            answers a building step
    GET  /buildings?q=<words>   the 3D database (docs/probe/models_index.csv): best matches, with "loaded"
    POST /buildings/<sid>/load  reads the model into a world (world/matterport.py, ~5 s); {"card", "scenario"}
    POST /sessions/<id>/retry   reruns the step that failed
    GET  /runs/studio/<run>/snapshot.json   the Robot Design page's snapshot of a finished run
    GET  /runs/studio/<run>/events?from=N   the run's events.jsonl from byte N: {"events": [...], "next": N}
    GET  /catalog/names                     {part id: name} for every catalog card
    GET  /catalog/cards                     {slot: [card, ...]} (frontend/robot-design/data/export.py's catalog())

Steering options (slots: base, lift, arm, gripper, lidar, lidar_mount, wrist_cam, ego_cam):
    {"exclude": [{slot: part id, ...}], "require": {slot: part id}, "max_price_usd": number | null}
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
import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from langchain_core.runnables import RunnableLambda

from agent.design_flow.api import DesignWorkflow, SessionError
from agent.design_flow import buildings, pipeline
from agent.design_flow.pipeline import EXPORT, REPO, RUNS, NoWorld, Stopped
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


_EXPORT = None


def catalog_cards() -> dict:
    """{slot: [card, ...]} from the working tree's catalog, as the Robot Design page's snapshot carries them."""
    global _EXPORT
    if _EXPORT is None:  # export.py is a script, not a package module: load it by path
        spec = importlib.util.spec_from_file_location("robot_design_export", EXPORT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EXPORT = mod
    cards = _EXPORT.catalog(REPO)
    for slot in cards.values():
        for c in slot:
            c.setdefault("name", c.get("id"))
    return cards


STEER_SLOTS = ("base", "lift", "arm", "gripper", "lidar", "lidar_mount", "wrist_cam", "ego_cam")


def steering(body: dict) -> dict:
    """The steering options in a request body, checked; ValueError says what is wrong. Only those set are kept."""
    def pattern(p, what):
        if not isinstance(p, dict) or not p:
            raise ValueError(f"{what} must be a non-empty object of slot -> part id")
        bad = sorted(set(p) - set(STEER_SLOTS))
        if bad:
            raise ValueError(f"{what}: unknown slots {bad}; slots are {', '.join(STEER_SLOTS)}")
        return dict(p)

    out = {}
    if body.get("exclude"):
        if not isinstance(body["exclude"], list):
            raise ValueError("exclude must be a list of {slot: part id} patterns")
        out["exclude"] = [pattern(p, "each exclude pattern") for p in body["exclude"]]
    if body.get("require"):
        out["require"] = pattern(body["require"], "require")
    if body.get("max_price_usd") is not None:
        v = body["max_price_usd"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise ValueError("max_price_usd must be a positive number")
        out["max_price_usd"] = v
    return out


def read_events(path: Path, start: int) -> dict:
    """Whole lines of events.jsonl from byte `start`; a line still being written waits for the next read."""
    if not path.is_file():
        return {"events": [], "next": 0}
    reset = start > path.stat().st_size  # the log was started again (a rerun into the same folder)
    if reset:
        start = 0
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
    return {"events": events, "next": start + end, **({"reset": True} if reset else {})}


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
            view["building"] = snap.values.get("building")
            if view.get("status") == "working":  # the node running now
                for node, phase in (("design", "design"), ("find_building", "building"), ("classify", "classify")):
                    if node in (snap.next or ()):
                        view["phase"] = phase
                        break
        except Exception:  # noqa: BLE001 - both are niceties
            pass
        return view

    def _set(self, sid: str, **fields) -> None:
        with self.lock:
            self.by_id.setdefault(sid, {}).update(fields)

    def _stopped(self, sid: str) -> None:
        self._set(sid, status="stopped", phase="design", error=pipeline.STOP_MESSAGE)

    def _work(self, sid: str, phase: str, call) -> None:
        self._set(sid, status="working", phase=phase, error=None)

        def go():
            try:
                step = call()
            except Stopped:
                self._stopped(sid)
                return
            except (SessionError, NoWorld) as e:
                if sid in pipeline.STOPPED:
                    return self._stopped(sid)
                self._set(sid, status="error", error=str(e))
                return
            except Exception as e:  # noqa: BLE001 - shown to the user, who can retry
                if sid in pipeline.STOPPED:  # the graph may wrap the Stopped it raised
                    return self._stopped(sid)
                self._set(sid, status="error", error=f"{type(e).__name__}: {e}")
                return
            if sid in pipeline.STOPPED:  # the stop came as the run was finishing: it still reads as stopped
                return self._stopped(sid)
            done = step.kind == "design"
            self._set(sid, status="done" if done else "waiting", phase=step.kind, step={"kind": step.kind, "data": step.data})

        threading.Thread(target=go, daemon=True).start()

    def start(self, world: str, job: str, options: dict | None = None) -> str:
        step = self.workflow.start(world=world, options=options or None)
        sid = step.session_id
        self._set(sid, world=world, job=job, step=None, **({"options": options} if options else {}))
        self._work(sid, "classify", lambda: self.workflow.reply(sid, job))
        return sid

    def stop(self, sid: str) -> bool:
        """Stop the session's running design. False when nothing is running (the view is unchanged)."""
        view = self.view(sid)
        designing = view.get("status") == "working" and view.get("phase") == "design"
        if not (pipeline.running(sid) or designing):
            return False
        self._stopped(sid)  # before the kill returns, so the view says so at once and go() can't say otherwise
        pipeline.stop(sid)
        return True

    def steer(self, sid: str, job: str | None, options: dict) -> str:
        """Stop the session's design if it runs, then start a new session in the same world with the job and
        the steering options. A learned skill goes straight to design (the store kept its recordings)."""
        old = self.view(sid)
        self.stop(sid)
        world = None
        try:
            world = self.workflow._snapshot(sid).values.get("world")  # what find_building settled on
        except Exception:  # noqa: BLE001
            pass
        new = self.start(world or old.get("world") or "rabinowitz-hall", job or old.get("job") or "", options)
        self._set(new, previous=sid)
        return new

    def reply(self, sid: str, answer) -> None:
        """Answer the step the session waits on: recordings for a demo, {"sid"} or text for a building."""
        waiting = (self.view(sid).get("step") or {}).get("kind")
        self._work(sid, "building" if waiting == "building" else "design", lambda: self.workflow.reply(sid, answer or None))

    def retry(self, sid: str) -> None:
        self.view(sid)
        pipeline.clear_stop(sid)  # a stopped design can be run again
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
            if path == "/buildings":
                q = parse_qs(urlparse(self.path).query)
                return self._send(200, {"results": buildings.search((q.get("q") or [""])[0], int((q.get("limit") or ["8"])[0]))})
            if path == "/catalog/names":
                return self._send(200, catalog_names())
            if path == "/catalog/cards":
                return self._send(200, catalog_cards())
            if path.startswith("/runs/studio/") and path.endswith("/events"):
                folder = (REPO / path.lstrip("/")[: -len("/events")]).resolve()
                if not folder.is_relative_to(RUNS.resolve()):
                    return self._send(404, {"detail": "not found"})
                q = parse_qs(urlparse(self.path).query)
                return self._send(200, read_events(folder / "events.jsonl", int((q.get("from") or ["0"])[0])))
            if path == "/room.html":  # the real-room 3D page (web/viewer/room.html), for a studio run
                return self._send(200, (REPO / "web" / "viewer" / "room.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/scans/") and path.endswith(("/room.glb", "/scan.json")):  # the scanned room's mesh and its listing
                scans = (REPO / "world" / "_scans").resolve()
                file = (scans / path[len("/scans/"):]).resolve()
                if file.is_relative_to(scans) and file.is_file():
                    return self._send(200, file.read_bytes(), "model/gltf-binary" if file.suffix == ".glb" else "application/json")
                return self._send(404, {"detail": "no room mesh on this machine"})
            if path.startswith("/mp/images/"):  # Matterport's logo for the room page, from the SDK bundle (web/fetch_sdk.py)
                vendor = (REPO / "web" / "_vendor").resolve()
                file = (vendor / path[len("/mp/"):]).resolve()
                if file.is_relative_to(vendor) and file.is_file():
                    return self._send(200, file.read_bytes(), "image/svg+xml" if file.suffix == ".svg" else "application/octet-stream")
                return self._send(404, {"detail": "not found"})
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
                    try:
                        options = steering(body.get("options") or {})
                    except ValueError as e:
                        return self._send(400, {"detail": str(e)})
                    sid = sessions.start(body.get("world") or "rabinowitz-hall", job, options)
                    return self._send(200, sessions.view(sid))
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "stop":
                    if not sessions.stop(parts[1]):
                        return self._send(409, {"detail": "nothing is running in this session", **sessions.view(parts[1])})
                    return self._send(200, sessions.view(parts[1]))
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "steer":
                    try:
                        options = steering(body)
                    except ValueError as e:
                        return self._send(400, {"detail": str(e)})
                    job = body.get("job")
                    if job is not None and (not isinstance(job, str) or not job.strip()):
                        return self._send(400, {"detail": "job must be non-empty text"})
                    sessions.view(parts[1])  # 404 for an unknown session, before anything is stopped
                    new = sessions.steer(parts[1], job.strip() if job else None, options)
                    return self._send(200, {**sessions.view(new), "previous": parts[1]})
                if len(parts) == 3 and parts[0] == "buildings" and parts[2] == "load":
                    try:
                        scenario = buildings.load(parts[1])
                    except (LookupError, RuntimeError, OSError) as e:
                        return self._send(400, {"detail": str(e)})
                    return self._send(200, {"card": buildings.get(parts[1]), "scenario": scenario})
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] in ("reply", "retry"):
                    if parts[2] == "reply":
                        sessions.reply(parts[1], body["answer"] if "answer" in body else body.get("recordings"))
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
