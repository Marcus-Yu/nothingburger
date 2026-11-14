import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import demos
from server.app import app

sys.path.append(str(Path(__file__).resolve().parents[4]))  # the repo root: capture/
synthetic = pytest.importorskip("capture.synthetic")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demos, "folder", lambda: tmp_path / "demos")
    monkeypatch.setattr(demos, "_pending", None)
    monkeypatch.setattr(demos, "_active", None)
    demos._stop.clear()
    return TestClient(app)


def test_request_is_handed_to_the_headset_once_then_recorded_and_read(client, tmp_path):
    assert client.get("/demos/control").json() == {"request": None, "stop": False}
    asked = client.post("/demos/request", json={"chore": "wipe table", "max_seconds": 20}).json()
    got = client.get("/demos/control").json()["request"]
    assert got["id"] == asked["id"] and got["chore"] == "wipe table" and got["kind"] == "path"
    assert client.get("/demos/control").json()["request"] is None  # once

    assert client.get("/demos/control", params={"active": asked["id"]}).json()["stop"] is False
    assert client.post("/demos/stop").json() == {"stopping": asked["id"]}
    assert client.get("/demos/control", params={"active": asked["id"]}).json()["stop"] is True

    recording = synthetic.wipe_table() | {"id": asked["id"]}
    saved = client.post("/demos", json=recording).json()
    assert saved["samples"] == len(recording["samples"])
    assert saved["read_as"]["motion"]["kind"] == "wipe"
    assert json.loads((tmp_path / "demos" / f"{asked['id']}.json").read_text())["chore"] == "wipe table"
    assert client.get("/demos").json()[0]["id"] == asked["id"]
    assert client.get(f"/demos/{asked['id']}").json()["schema"] == "capture.recording/1"
    assert client.get("/demos/control", params={"active": asked["id"]}).json()["stop"] is False  # cleared


def test_bad_recordings_and_ids_are_refused(client):
    good = synthetic.squeeze()
    assert client.post("/demos", json=good | {"schema": "nope"}).status_code == 422
    assert client.post("/demos", json=good | {"samples": []}).status_code == 422
    assert client.post("/demos", json=good | {"id": "../x"}).status_code == 422
    assert client.get("/demos/..%2Fsecret").status_code in (400, 404)
    assert client.get("/demos/missing").status_code == 404
    assert client.post("/demos/request", json={"chore": "x", "kind": "dance"}).status_code == 422
    assert client.post("/demos", json=good).json()["read_as"]["grip"]["force_n"]["max"] > 0


def test_a_take_can_be_thrown_away_and_done_again(client, tmp_path):
    asked = client.post("/demos/request", json={"chore": "hold container", "kind": "squeeze"}).json()
    recording = synthetic.squeeze() | {"id": asked["id"]}
    for sample in recording["samples"]:
        sample["left"]["glove_raw"] = [0, 900, 40, 0, 0]
    client.post("/demos", json=recording)
    read = client.get(f"/demos/{asked['id']}/read").json()
    assert read["glove_peaks"] == {"left": {"thumb": 0, "index": 900, "middle": 40, "ring": 0, "pinky": 0}}
    assert read["samples"] == len(recording["samples"])

    assert client.post(f"/demos/{asked['id']}/discard").json()["discarded"] is True
    assert client.get("/demos").json() == []  # out of the inbox
    assert client.get(f"/demos/{asked['id']}/read").status_code == 404
    assert (tmp_path / "demos" / "_discarded" / f"{asked['id']}.json").is_file()  # but not destroyed
    assert client.post(f"/demos/{asked['id']}/discard").status_code == 404

    again = client.post("/demos/request", json={"chore": "hold container", "kind": "squeeze"}).json()
    assert again["id"] != asked["id"] and client.get("/demos/control").json()["request"]["id"] == again["id"]
