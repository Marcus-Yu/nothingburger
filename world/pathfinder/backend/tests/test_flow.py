from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_site_and_worlds_are_served():
    assert "Create plan" in client.get("/web/").text
    worlds = client.get("/worlds").json()
    assert worlds[0]["id"] == "rabinowitz-hall" and worlds[0]["matterport"]  # the default space
    assert all("in_headset" in w for w in worlds)


def test_stand_in_plan_asks_for_demos_only_where_a_grip_or_motion_is_needed():
    bulb = client.post(
        "/plan", json={"world": "rabinowitz-hall", "job": "Change the dead light bulb"}
    ).json()
    assert bulb["understood_as"] == "Change a light bulb"
    assert [d["kind"] for d in bulb["demos"]] == ["path", "squeeze"] and bulb["parts"] is False
    part = client.post("/plan", json={"world": "la-mirada", "job": "Replace the dishwasher"}).json()
    assert part["parts"] is True and part["demos"] == []
    odd = client.post("/plan", json={"world": "la-mirada", "job": "juggle"}).json()
    assert odd["understood_as"] is None and odd["demos"] == []
    assert client.post("/plan", json={"world": "x", "job": ""}).status_code == 422
