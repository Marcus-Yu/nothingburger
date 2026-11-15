"""The headset's launch list (GET /vr/runs) and the run files behind it (runs/demos, runs/gallery, runs/studio),
and the robot's model as GLB (GET /cad/robot.glb).

A repo is made up in a temp folder: no committed run, scan or network is read.

    uv run python -m unittest discover -s agent/design_flow/tests -t .
"""

import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agent.design_flow import serve
from agent.tools import cad

os.environ["LANGSMITH_TRACING"] = "false"

TOUR = {"t": 9.0, "kind": "tour", "glb": "frames/tour_robot.glb", "frames": "frames/tour_frames.bin", "bodies": 2, "fps": 24, "n": 240,
        "chapters": [{"t": 0.0, "label": "drive: dock to t1"}]}


def make_run(folder: Path, *, world: dict, job: str | None = None, tour: bool = True, export: bool = True, mtime: float | None = None) -> None:
    (folder / "frames").mkdir(parents=True)
    events = [{"t": 0.0, "kind": "run_start", "job": job}] + ([TOUR] if tour else []) + [{"t": 9.5, "kind": "run_end", "ok": True}]
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (folder / "world.json").write_text(json.dumps(world))
    if job:
        (folder / "intake.json").write_text(json.dumps({"job": job}))
    if export:
        (folder / "frames" / "tour_robot.glb").write_bytes(b"glTF")
        (folder / "frames" / "tour_frames.bin").write_bytes(b"\0" * 56)
    if mtime is not None:
        os.utime(folder / "events.jsonl", (mtime, mtime))


class VrRunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        repo = self.repo = Path(self.tmp.name).resolve()
        (repo / "web" / "viewer").mkdir(parents=True)
        (repo / "web" / "viewer" / "vr.html").write_text("<!doctype html><title>launch</title>")
        (repo / "web" / "worlds.json").write_text(json.dumps([{"id": "the-hall", "name": "The Hall, Princeton", "matterport": "ABC123"}]))
        (repo / "secret.txt").write_text("not a run file")
        (repo / "runs" / "scratch" / "s1").mkdir(parents=True)
        (repo / "runs" / "scratch" / "s1" / "world.json").write_text("{}")
        (repo / "world" / "_scans" / "hall").mkdir(parents=True)
        (repo / "world" / "_scans" / "hall" / "room.glb").write_bytes(b"glTF")

        hall = {"id": "hall", "tour": {"matterport": "ABC123"}}
        flat = {"id": "flat_9", "source": "read from Matterport model XYZ789 (9 Side Street, Unit 2, Houston, TX, 77002, US) by world/matterport.py"}
        make_run(repo / "runs" / "demos" / "hall-wipe", world=hall, job="Wipe the hall table")
        make_run(repo / "runs" / "demos" / "flat-wipe", world=flat, job="Wipe the counter")
        make_run(repo / "runs" / "demos" / "lot-mow", world={"id": "lot"}, job="Mow the lawn", tour=False, export=False)  # outdoors: no export
        make_run(repo / "runs" / "demos" / "half-done", world=hall, job="Stopped early", tour=False)                      # export, no tour event
        make_run(repo / "runs" / "gallery" / "hall", world=hall)                                                         # a task-file run: no job in words
        for i in range(serve.STUDIO_IN_VR + 3):
            make_run(repo / "runs" / "studio" / f"run-{i:02d}", world=hall, job=f"Studio job {i}", mtime=1_800_000_000 + i)

        for name, value in (("REPO", repo), ("RUNS", repo / "runs" / "studio")):
            patch = mock.patch.object(serve, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(sessions=None, standin=True))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        """The path is sent as written: nothing tidies a `..` away before the server sees it."""
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            self.headers = dict((k.lower(), v) for k, v in r.getheaders())
            return r.status, r.getheader("content-type"), r.read()
        finally:
            conn.close()

    def test_serves_the_robot_model_for_the_parts_in_the_address(self):
        asked = []

        def robot_glb(parts):
            asked.append(parts)
            if parts.get("arm") == "no_such_arm":
                raise ValueError("these parts cannot be composed: 'no_such_arm'")
            return b"glTF" + b"\0" * 20

        with mock.patch.object(cad, "robot_glb", robot_glb):
            code, ctype, body = self.get("/cad/robot.glb?base=tidybot_arx5&lift=liftkit_500&arm=ur10e&gripper=robotiq_2f85"
                                         "&lidar=rplidar_s2&lidar_mount=stage_rear&wrist_cam=true&ego_cam=base_front&colour=red")
            self.assertEqual((code, ctype, body[:4]), (200, "model/gltf-binary", b"glTF"))
            self.assertEqual(self.headers["cache-control"], "public, max-age=3600")
            self.assertEqual(self.headers["access-control-allow-origin"], "*")
            self.assertEqual(asked[-1], {"base": "tidybot_arx5", "lift": "liftkit_500", "arm": "ur10e", "gripper": "robotiq_2f85",
                                         "lidar": "rplidar_s2", "lidar_mount": "stage_rear", "wrist_cam": True, "ego_cam": "base_front"})

            self.assertEqual(self.get("/cad/robot.glb?base=tidybot_arx5&arm=ur10e&gripper=robotiq_2f85&wrist_cam=false&lift=")[0], 200)
            self.assertEqual(asked[-1], {"base": "tidybot_arx5", "arm": "ur10e", "gripper": "robotiq_2f85", "wrist_cam": False})  # what is left out is cad's to fill

            code, ctype, body = self.get("/cad/robot.glb?base=tidybot_arx5&arm=no_such_arm&gripper=robotiq_2f85")
            self.assertEqual((code, ctype), (400, "application/json"))
            self.assertIn("no_such_arm", json.loads(body)["detail"])
            self.assertEqual(self.headers["cache-control"], "no-store")  # a refusal is not kept

    def test_lists_the_runs_the_room_page_can_play(self):
        code, ctype, body = self.get("/vr/runs")
        self.assertEqual((code, ctype), (200, "application/json"))
        runs = json.loads(body)
        by_run = {r["run"]: r for r in runs}
        self.assertNotIn("runs/demos/lot-mow", by_run)     # no robot export
        self.assertNotIn("runs/demos/half-done", by_run)   # no tour event
        self.assertEqual([r["run"] for r in runs[:3]], ["runs/demos/flat-wipe", "runs/demos/hall-wipe", "runs/gallery/hall"])

        hall = by_run["runs/demos/hall-wipe"]
        self.assertEqual({k: hall[k] for k in ("title", "place", "world", "has_room", "seconds")},
                         {"title": "Wipe the hall table", "place": "The Hall, Princeton", "world": "hall", "has_room": True, "seconds": 10})
        self.assertRegex(hall["when"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        flat = by_run["runs/demos/flat-wipe"]              # not a studio space: the address it was read from; no mesh here
        self.assertEqual((flat["place"], flat["has_room"]), ("9 Side Street, Unit 2, Houston, TX", False))
        self.assertEqual(by_run["runs/gallery/hall"]["title"], "hall")  # no job in words: the folder's name

        studio = [r["run"] for r in runs if r["run"].startswith("runs/studio/")]
        newest = [f"runs/studio/run-{i:02d}" for i in range(serve.STUDIO_IN_VR + 2, 2, -1)]
        self.assertEqual(studio, newest)                   # the newest fifteen, newest first

    def test_serves_run_files_from_demos_gallery_and_studio_only(self):
        for path, ctype in (("/runs/demos/hall-wipe/world.json", "application/json"),
                            ("/runs/demos/hall-wipe/events.jsonl", "application/x-ndjson"),
                            ("/runs/gallery/hall/frames/tour_robot.glb", "model/gltf-binary"),
                            ("/runs/studio/run-00/frames/tour_frames.bin", "application/octet-stream")):
            code, got, body = self.get(path)
            self.assertEqual((code, got), (200, ctype), path)
            self.assertTrue(body, path)
        self.assertEqual(json.loads(self.get("/runs/demos/hall-wipe/world.json")[2])["id"], "hall")
        for path in ("/runs/scratch/s1/world.json",              # a run folder that is not one of the three
                     "/runs/demos/../../secret.txt",             # out of the run folders, plainly
                     "/runs/demos/..%2f..%2fsecret.txt",         # and with the slashes encoded
                     "/runs/demos/%2e%2e/scratch/s1/world.json",
                     "/runs/demos/hall-wipe/nothing.json",
                     "/runs/demos/hall-wipe"):                   # a folder, not a file
            self.assertEqual(self.get(path)[0], 404, path)

    def test_serves_the_launch_page_and_the_scan(self):
        code, ctype, body = self.get("/vr")
        self.assertEqual((code, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b"launch", body)
        self.assertEqual(self.get("/scans/hall/room.glb")[0], 200)
        self.assertEqual(self.get("/scans/flat_9/room.glb")[0], 404)

    def test_follows_a_scan_folder_linked_from_another_checkout(self):
        other = self.repo / "elsewhere" / "atrium"
        other.mkdir(parents=True)
        (other / "room.glb").write_bytes(b"glTF-linked")
        (other / "scan.json").write_text('{"levels": []}')
        (other / "notes.txt").write_text("not for serving")
        (self.repo / "elsewhere" / "private.glb").write_bytes(b"no")
        os.symlink(other, self.repo / "world" / "_scans" / "atrium")
        make_run(self.repo / "runs" / "demos" / "atrium-wipe", world={"id": "atrium"}, job="Wipe the atrium table")

        self.assertEqual(self.get("/scans/atrium/room.glb")[::2], (200, b"glTF-linked"))
        self.assertEqual(self.get("/scans/atrium/scan.json")[0], 200)
        runs = {r["run"]: r for r in json.loads(self.get("/vr/runs")[2])}
        self.assertTrue(runs["runs/demos/atrium-wipe"]["has_room"])
        for path in ("/scans/atrium/notes.txt",                 # only the mesh and its listing
                     "/scans/atrium/../private.glb",
                     "/scans/atrium/..%2fprivate.glb",
                     "/scans/../elsewhere/atrium/room.glb",
                     "/scans/%2e%2e/elsewhere/atrium/room.glb",
                     "/scans/hall/sub/room.glb"):
            self.assertEqual(self.get(path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
