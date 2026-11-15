"""Steering and stopping a design run: agent.run's flags, pipeline.stop, and the server's stop and steer.

Stand-ins replace the classifier and the designer; the graph, the HTTP handler and the skill store are real.

    uv run python -m unittest discover -s agent/design_flow/tests -t .
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from agent import observe
from agent import run as agent_run
from agent.design_flow import pipeline, serve
from agent.design_flow.api import DesignWorkflow
from agent.design_flow.schemas import TaskAssessment
from agent.design_flow.skills import SkillStore

os.environ["LANGSMITH_TRACING"] = "false"
REPO = Path(__file__).resolve().parents[3]
STEER = ["--exclude", '[{"arm": "xarm7"}, {"lift": "none", "arm": "piper"}]', "--require", '{"base": "go2"}',
         "--max-price", "30000"]


class Captured(Exception):
    pass


class RunFlagsTest(unittest.TestCase):
    def test_flags_parse_into_steering(self):
        ap = agent_run.parser()
        a = ap.parse_args(["--world", "w", "--out", "o", *STEER])
        self.assertEqual(agent_run.steering(ap, a), {"exclude": [{"arm": "xarm7"}, {"lift": "none", "arm": "piper"}],
                                                     "require": {"base": "go2"}, "max_price_usd": 30000.0})
        a = ap.parse_args(["--world", "w", "--out", "o"])
        self.assertEqual(agent_run.steering(ap, a), {"exclude": None, "require": None, "max_price_usd": None})

    def test_bad_flags_are_refused(self):
        ap = agent_run.parser()
        for bad in (["--exclude", "{not json"], ["--exclude", '{"arm": "x"}'], ["--require", '{"hat": "x"}'],
                    ["--require", "[]"]):
            a = ap.parse_args(["--world", "w", "--out", "o", *bad])
            with unittest.mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                agent_run.steering(ap, a)

    def test_main_puts_them_in_state_and_emits_steer(self):
        seen = {}

        def fake_pipeline(state):
            seen.update(state)
            raise Captured()

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(agent_run, "pipeline", fake_pipeline):
            out = Path(tmp) / "run"
            had = os.environ.get("AGENT_NO_MODEL")
            try:
                with self.assertRaises(Captured):
                    agent_run.main(["--world", str(REPO / "contracts" / "world.example.json"),
                                    "--tasks", str(REPO / "agent" / "tasks.example.json"), "--no-model", "--out", str(out), *STEER])
            finally:
                observe._events["path"] = None  # the run's event log goes with the temp folder
                if had is None:
                    os.environ.pop("AGENT_NO_MODEL", None)
            events = [json.loads(l) for l in (out / "events.jsonl").read_text().splitlines()]
        self.assertEqual(seen["exclude"], [{"arm": "xarm7"}, {"lift": "none", "arm": "piper"}])
        self.assertEqual(seen["require"], {"base": "go2"})
        self.assertEqual(seen["max_price_usd"], 30000.0)
        steer = [e for e in events if e["kind"] == "steer"]
        self.assertEqual(len(steer), 1)
        self.assertEqual(steer[0]["require"], {"base": "go2"})

    def test_pipeline_seeds_excluded_and_design_step_passes_the_limits(self):
        from agent.nodes import design as design_node

        calls = []

        def fake_steered(requirements, **kw):
            calls.append(kw)
            return {"schema": "design/1", "parts": None, "price_usd": None, "mass_kg": None, "checks": [], "labels": [],
                    "infeasible": {"binding_checks": [{"check": "price limit", "status": "fail", "requirements": []}]}}

        state = {"requirements": {}, "excluded": [{"arm": "xarm7"}], "require": {"base": "go2"}, "max_price_usd": 30000.0}
        with unittest.mock.patch.object(design_node.composer, "design", fake_steered):  # the tool wrapper the node calls
            out = design_node.step(state)
        self.assertTrue(out["infeasible"])
        self.assertEqual(calls[0]["exclude"], [{"arm": "xarm7"}])
        self.assertEqual(calls[0]["require"], {"base": "go2"})
        self.assertEqual(calls[0]["max_price_usd"], 30000.0)

    def test_steer_flags(self):
        self.assertEqual(pipeline.steer_flags(None), [])
        self.assertEqual(pipeline.steer_flags({"exclude": [{"arm": "x"}], "require": {"base": "go2"}, "max_price_usd": 30000}),
                         ["--exclude", '[{"arm": "x"}]', "--require", '{"base": "go2"}', "--max-price", "30000.0"])


# A stand-in for `python -m agent.run`: writes a start event, spawns a worker, writes both pids, then sleeps.
SLEEPER = """
import json, os, subprocess, sys, time
out = sys.argv[sys.argv.index('--out') + 1]
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'events.jsonl'), 'a').write(json.dumps({'kind': 'run_start'}) + '\\n')
w = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
open(os.path.join(out, 'pids'), 'w').write(f'{os.getpid()} {w.pid}')
time.sleep(60)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class PipelineStopTest(unittest.TestCase):
    def test_stop_kills_the_tree_and_raises_stopped(self):
        real_popen = pipeline.subprocess.Popen

        def popen(cmd, **kw):
            return real_popen([sys.executable, "-c", SLEEPER, *cmd[1:]], **kw)

        result = {}
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(pipeline.subprocess, "Popen", popen):
            def go():
                try:
                    pipeline.run_pipeline({"task": "wipe the tables", "skill": "wipe_table", "world": "rabinowitz-hall"},
                                          runs=Path(tmp), standin_tasks=True, session="stop-test")
                except BaseException as e:  # noqa: BLE001
                    result["error"] = e

            t = threading.Thread(target=go)
            t0 = time.monotonic()
            t.start()
            out = None
            while time.monotonic() - t0 < 20:
                out = next(Path(tmp).glob("*/pids"), None)
                if out and out.read_text() and pipeline.running("stop-test"):
                    break
                time.sleep(0.05)
            self.assertTrue(pipeline.running("stop-test"))
            leader, worker = map(int, out.read_text().split())
            self.assertTrue(pipeline.stop("stop-test"))
            t.join(10)
            self.assertFalse(t.is_alive())
            self.assertIsInstance(result.get("error"), pipeline.Stopped)
            self.assertEqual(str(result["error"]), "Stopped by you")
            self.assertTrue(isinstance(result["error"], RuntimeError))
            time.sleep(0.2)
            self.assertFalse(alive(worker), "the worker outlived the stop")
            events = [json.loads(l) for l in (out.parent / "events.jsonl").read_text().splitlines()]
            self.assertEqual(events[-1], {"kind": "run_end", "ok": False, "stopped": True})
            self.assertEqual(pipeline.ACTIVE["stop-test"], pipeline._rel(out.parent))
            self.assertLess(time.monotonic() - t0, 20)
        pipeline.clear_stop("stop-test")
        self.assertFalse(pipeline.stop("nothing-here"))  # nothing running: marks only
        pipeline.clear_stop("nothing-here")


class ServerSteerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SkillStore(Path(self.tmp.name))
        self.requests = []
        self.release = threading.Event()

        def classify(request):
            return TaskAssessment(valid=True, skill="wipe_table", reason="Wipe it.")

        def design(request, config):  # stands in for the pipeline: runs until released or stopped
            sid = config["configurable"]["thread_id"]
            self.requests.append((sid, request))
            pipeline.ACTIVE[sid] = f"runs/studio/fake-{len(self.requests)}"
            while not self.release.wait(0.02):
                if sid in pipeline.STOPPED:
                    raise pipeline.Stopped()
            return {"kind": "pipeline", "run": pipeline.ACTIVE[sid], "options": request.get("options")}

        workflow = DesignWorkflow(latest_recording=lambda kind, chore: None, classifier=RunnableLambda(classify),
                                  designer=RunnableLambda(design), store=self.store)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(serve.Sessions(workflow), standin=True))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(self, sid, *statuses):
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10:
            code, view = self.call("GET", f"/sessions/{sid}")
            if view.get("status") in statuses and (view.get("run") or "done" in statuses):
                return view
            time.sleep(0.02)
        self.fail(f"session {sid} never reached {statuses}: {view}")

    def test_demo_then_stop_then_steer(self):
        _, view = self.call("POST", "/sessions", {"world": "la-mirada", "job": "Wipe down the table in the kitchen"})
        sid = view["session_id"]
        while self.call("GET", f"/sessions/{sid}")[1].get("status") != "waiting":
            time.sleep(0.02)
        code, _ = self.call("POST", f"/sessions/{sid}/stop")
        self.assertEqual(code, 409)  # waiting on the demo: nothing is running
        recordings = {"demo": {"motion": {"kind": "wipe"}}, "grip": {"force_n": {"peak": 10.0}}}
        self.call("POST", f"/sessions/{sid}/reply", {"recordings": recordings})
        self.wait(sid, "working")

        code, view = self.call("POST", f"/sessions/{sid}/stop")
        self.assertEqual(code, 200)
        self.assertEqual((view["status"], view["phase"], view["error"]), ("stopped", "design", "Stopped by you"))
        self.assertEqual(view["run"], "runs/studio/fake-1")
        time.sleep(0.2)  # the design thread sees the stop and must not overwrite it
        view = self.call("GET", f"/sessions/{sid}")[1]
        self.assertEqual((view["status"], view["error"]), ("stopped", "Stopped by you"))
        self.assertEqual(self.call("POST", f"/sessions/{sid}/stop")[0], 409)

        code, view = self.call("POST", f"/sessions/{sid}/steer", {"max_price_usd": 30000, "require": {"base": "go2"}})
        self.assertEqual(code, 200)
        self.assertEqual(view["previous"], sid)
        new = view["session_id"]
        self.assertNotEqual(new, sid)
        self.assertEqual(view["options"], {"max_price_usd": 30000, "require": {"base": "go2"}})
        view = self.wait(new, "working")  # straight to design: the skill's recordings are in the store
        self.assertEqual(view["run"], "runs/studio/fake-2")
        self.release.set()
        view = self.wait(new, "done")
        self.assertEqual(view["step"]["data"]["options"], {"max_price_usd": 30000, "require": {"base": "go2"}})
        new_sid, req = self.requests[-1]
        self.assertEqual(new_sid, new)
        self.assertEqual(req["task"], "Wipe down the table in the kitchen")
        self.assertEqual(req["world"], "la-mirada")
        self.assertEqual(req["options"], {"max_price_usd": 30000, "require": {"base": "go2"}})
        self.assertEqual(req["demo"], recordings)

    def test_steer_running_session_with_new_job(self):
        self.store.save("wipe_table", {"demo": {"motion": {"kind": "wipe"}}, "grip": {"force_n": {"peak": 10.0}}})
        _, view = self.call("POST", "/sessions", {"world": "la-mirada", "job": "Wipe the table"})
        sid = view["session_id"]
        self.wait(sid, "working")
        code, view = self.call("POST", f"/sessions/{sid}/steer", {"job": "Wipe the counter", "exclude": [{"arm": "xarm7"}]})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", f"/sessions/{sid}")[1]["status"], "stopped")
        self.wait(view["session_id"], "working")
        self.assertEqual(self.requests[-1][1]["task"], "Wipe the counter")
        self.assertEqual(self.requests[-1][1]["options"], {"exclude": [{"arm": "xarm7"}]})

    def test_bad_steer_and_unknown_session(self):
        self.assertEqual(self.call("POST", "/sessions/nope/steer", {})[0], 404)
        self.assertEqual(self.call("POST", "/sessions/nope/stop")[0], 404)
        _, view = self.call("POST", "/sessions", {"world": "la-mirada", "job": "Wipe the table"})
        self.assertEqual(self.call("POST", f"/sessions/{view['session_id']}/steer", {"require": {"hat": "x"}})[0], 400)
        self.assertEqual(self.call("POST", f"/sessions/{view['session_id']}/steer", {"max_price_usd": "cheap"})[0], 400)

    def test_catalog_cards(self):
        code, cards = self.call("GET", "/catalog/cards")
        self.assertEqual(code, 200)
        self.assertEqual(set(cards), {"base", "lift", "arm", "gripper", "lidar", "camera"})
        self.assertTrue(all(c.get("name") and c.get("id") for slot in cards.values() for c in slot))


if __name__ == "__main__":
    unittest.main()
