"""The live run view: a small local server for web/viewer and the run folders it reads.

    python -m web.serve            # then open http://127.0.0.1:8010

It serves web/viewer/, the files under runs/, a list of runs, and can start a run of the agent as a
separate process (the page's Run button). It binds to 127.0.0.1 only. The page reads a run folder and
nothing else: events.jsonl as it grows, and the frames next to it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO = Path(__file__).resolve().parents[1]
VIEWER = REPO / "web" / "viewer"
RUNS = REPO / "runs"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".jsonl": "application/x-ndjson", ".png": "image/png", ".svg": "image/svg+xml", ".xml": "text/xml", ".txt": "text/plain"}


def list_runs() -> list:
    out = []
    for ev in RUNS.glob("**/events.jsonl"):
        try:
            lines = ev.read_text().splitlines()
            first = json.loads(lines[0]) if lines else {}
            last = json.loads(lines[-1]) if lines else {}
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"run": str(ev.parent.relative_to(REPO)), "modified": ev.stat().st_mtime,
                    "job": first.get("job") or (f"tasks: {first.get('tasks_file')}" if first.get("tasks_file") else ""),
                    "finished": last.get("kind") == "run_end", "ok": last.get("ok")})
    # the kept gallery first, then everything else, newest first
    return sorted(out, key=lambda r: (not r["run"].startswith("runs/gallery/"), -r["modified"]))


def prior_run(rel: str) -> dict | None:
    """What a new run takes over from an earlier one: its job, its world file and the answers given so far.
    None when `rel` is not a run folder under runs/ with a job in words."""
    folder = (REPO / rel).resolve()
    if RUNS.resolve() not in folder.parents or not (folder / "intake.json").is_file() or not (folder / "world.json").is_file():
        return None
    intake = json.loads((folder / "intake.json").read_text())
    if not intake.get("job"):
        return None
    return {"job": intake["job"], "world": str((folder / "world.json").relative_to(REPO)), "answers": intake.get("answers", [])}


def start_run(job: str | None, use_model: bool, resume: dict | None = None, answers: list | None = None, proceed: bool = False) -> str:
    """Start the agent in a new folder under runs/scratch. With `resume` (from prior_run) the new run has the
    earlier run's job and world, and its answers plus `answers`; `proceed` goes on past open questions."""
    name = time.strftime("web-%Y%m%d-%H%M%S")
    out = RUNS / "scratch" / name
    out.mkdir(parents=True, exist_ok=True)
    if resume:
        cmd = [sys.executable, "-m", "agent.run", "--world", resume["world"], "--job", resume["job"], "--frames",
               "--out", str(out.relative_to(REPO))]
        given = resume["answers"] + [{"question": str(a.get("question", ""))[:1000], "answer": str(a.get("answer", ""))[:2000]}
                                     for a in answers or [] if str(a.get("answer", "")).strip()]
        if given:
            (out / "answers.json").write_text(json.dumps(given, indent=2))
            cmd += ["--answers", str((out / "answers.json").relative_to(REPO))]
        if proceed:
            cmd += ["--proceed"]
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        subprocess.Popen(cmd, cwd=REPO, env=env, stdout=open(out / "log.txt", "w"), stderr=subprocess.STDOUT)
        return str(out.relative_to(REPO))
    cmd = [sys.executable, "-m", "agent.run", "--world", "contracts/world.example.json", "--demo", "contracts/demo.example.json",
           "--grip", "contracts/grip.example.json", "--frames", "--out", str(out.relative_to(REPO))]
    if job and use_model:
        cmd += ["--job", job]
    else:
        cmd += ["--tasks", "agent/tasks.example.json", "--demo-task", "t1"] + ([] if use_model else ["--no-model"])
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    log = open(out / "log.txt", "w")
    subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    return str(out.relative_to(REPO))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, root: Path, rel: str) -> None:
        path = (root / rel).resolve()
        if root.resolve() not in path.parents and path != root.resolve() or not path.is_file():
            return self._send(404, b"not found", "text/plain")
        self._send(200, path.read_bytes(), TYPES.get(path.suffix, "application/octet-stream"))

    def do_GET(self):
        p = unquote(urlparse(self.path).path)
        if p in ("/", "/index.html"):
            return self._file(VIEWER, "index.html")
        if p == "/api/runs":
            return self._json(list_runs())
        if p.startswith("/runs/"):
            return self._file(RUNS, p[len("/runs/"):])
        return self._file(VIEWER, p.lstrip("/"))

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self._send(404, b"not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad JSON"}, 400)
        if body.get("resume"):  # answers to an earlier run's questions, or "go on without them"
            prior = prior_run(str(body["resume"]))
            if prior is None:
                return self._json({"error": "no such run to continue"}, 400)
            answers = body.get("answers") if isinstance(body.get("answers"), list) else []
            return self._json({"run": start_run(None, True, resume=prior, answers=answers, proceed=bool(body.get("proceed")))})
        job = (body.get("job") or "").strip()[:1000] or None
        return self._json({"run": start_run(job, bool(body.get("model", True)))})


def main() -> None:
    port = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT") or 8010)
    print(f"live run view: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
