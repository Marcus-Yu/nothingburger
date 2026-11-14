import json
import os
import time

import numpy as np
import pytest

from capture import api, process, synthetic


def test_wipe_is_read_as_a_wipe_with_its_patch_of_table():
    demo = process.build_demo(synthetic.wipe_table(passes=4, width=0.6, depth=0.3))
    m = demo["motion"]
    assert m["kind"] == "wipe"
    assert m["size_m"][0] == pytest.approx(0.6, abs=0.04)  # along the stroke
    assert m["size_m"][1] == pytest.approx(0.3, abs=0.04)
    assert abs(m["surface_normal"][1]) > 0.95
    assert abs(m["stroke_axis"][0]) > 0.95  # the sweeps run along x
    assert m["passes"] == 4
    assert demo["phases"]["approach"] > 10 and demo["phases"]["retreat"] > 10
    assert demo["reach"]["max_height_m"] == pytest.approx(0.77, abs=0.03)
    assert demo["two_handed"] is None


def test_bin_is_a_two_handed_carry():
    demo = process.build_demo(synthetic.move_bin(distance=0.8, width=0.42))
    assert demo["motion"]["kind"] == "carry"
    assert demo["motion"]["distance_m"] == pytest.approx(0.8, abs=0.05)
    assert demo["motion"]["lift_m"] == pytest.approx(0.2, abs=0.03)
    assert demo["two_handed"]["width_m"] == pytest.approx(0.42, abs=0.02)


def test_box_lid_is_a_hinge_with_its_axis_radius_and_angle():
    demo = process.build_demo(synthetic.open_box(radius=0.3, angle_deg=100))
    m = demo["motion"]
    assert m["kind"] == "hinge"
    assert m["radius_m"] == pytest.approx(0.3, abs=0.02)
    assert m["angle_deg"] == pytest.approx(100, abs=8)
    assert abs(m["axis"][0]) > 0.97  # the hinge runs along x
    assert np.allclose(m["point"][1:], [0.75 + 0.25, -0.3], atol=0.03)  # on the hinge line


def test_bulb_is_a_twist_about_the_vertical_counted_past_a_full_turn():
    demo = process.build_demo(synthetic.unscrew_bulb(turns=1.5))
    m = demo["motion"]
    assert m["kind"] == "twist"
    assert m["turns"] == pytest.approx(1.5, abs=0.1)
    assert m["axis"][1] > 0.97
    assert demo["reach"]["max_height_m"] == pytest.approx(1.6, abs=0.02)
    # the hand came up at the bulb from below and in front
    assert demo["approach_direction"] is not None


def test_path_is_relative_to_the_anchor_at_a_fixed_rate():
    rec = synthetic.wipe_table()
    demo = process.build_demo(rec)
    t = np.array([s["t"] for s in demo["path"]])
    assert np.allclose(np.diff(t), 1 / 30, atol=1e-3)
    # on the table the hand is 2 cm above the anchor's surface: object z, whatever the scan's axes
    work = np.array([s["p"] for s in demo["path"] if s["phase"] == "work"])
    assert np.allclose(work[:, 2], 0.02, atol=0.035) and np.median(work[:, 2]) == pytest.approx(0.02, abs=0.005)
    # moving the whole scene does not change the object-relative path
    for s in rec["samples"]:
        for side in ("left", "right"):
            s[side]["p"] = (np.array(s[side]["p"]) + [5.0, 0.0, -3.0]).tolist()
    rec["anchor"]["p"] = (np.array(rec["anchor"]["p"]) + [5.0, 0.0, -3.0]).tolist()
    moved = np.array([s["p"] for s in process.build_demo(rec)["path"]])
    assert np.allclose(moved, np.array([s["p"] for s in demo["path"]]), atol=1e-3)


def test_grip_band_from_travel_and_from_a_glove():
    travel = process.build_grip(synthetic.squeeze(low=0.3, high=0.8), n_per_unit=12.0)
    assert travel["source"] == "travel" and travel["scale_n_per_unit"] == 12.0
    assert travel["force_n"]["min"] == pytest.approx(0.35 * 12, abs=0.4)
    assert travel["force_n"]["max"] == pytest.approx(0.75 * 12, abs=0.4)
    glove = process.build_grip(synthetic.squeeze(low=0.3, high=0.8, force_per_unit=20.0))
    assert glove["source"] == "glove" and glove["scale_n_per_unit"] is None
    assert glove["force_n"]["peak"] == pytest.approx(16.0, abs=0.1)
    with pytest.raises(ValueError):
        process.build_grip(synthetic.wipe_table())  # an open hand never gripped


def test_untracked_stretches_are_bridged_and_an_empty_recording_is_refused():
    rec = synthetic.move_bin()
    for s in rec["samples"][40:52]:
        s["right"]["tracked"] = False
    assert process.build_demo(rec)["motion"]["kind"] == "carry"
    for s in rec["samples"]:
        s["right"]["tracked"] = s["left"]["tracked"] = False
    with pytest.raises(ValueError):
        process.build_demo(rec)


def test_latest_prefers_the_newest_and_the_right_kind(tmp_path):
    for k, (name, make) in enumerate([("a", synthetic.wipe_table), ("b", synthetic.squeeze), ("c", synthetic.move_bin)]):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(make()))
        os.utime(path, (time.time() + k, time.time() + k))
    assert api.latest("demo", tmp_path)["chore"] == "move bin"
    assert api.latest("demo", tmp_path, chore="wipe table")["motion"]["kind"] == "wipe"
    assert api.latest("grip", tmp_path)["recording"] == "synthetic-squeeze"  # the squeeze test, not the bin
    assert api.latest("demo", tmp_path / "missing") is None
    written = api.ingest(synthetic.open_box(), tmp_path / "run")
    assert set(written) == {"demo", "grip"}
    assert json.loads((tmp_path / "run" / "demo.json").read_text())["motion"]["kind"] == "hinge"


def test_the_pinch_that_starts_a_recording_is_not_a_grip():
    rec = synthetic.wipe_table()
    for s in rec["samples"][:12]:  # the marking pinch, released after 0.4 s
        s["right"]["grip"] = 1.0
    assert process.build_demo(rec)["phases"]["approach"] > 10  # the work still starts at the table
    with pytest.raises(ValueError):
        process.build_grip(rec)
    held = synthetic.move_bin()  # a hold that starts later is kept
    assert process.build_grip(held)["held_s"] > 2


def test_a_box_lifted_with_two_hands_and_put_back_is_a_carry_not_a_wipe():
    """The first real glove recording: only one hand gloved, the other never read as gripping,
    the box lifted 35 cm and set down near where it started."""
    rec = synthetic.move_bin(distance=0.05, width=0.28)
    for s in rec["samples"]:
        s["left"]["grip"] = 0.0
        s["left"]["joints"] = synthetic.hand_joints(s["left"]["p"], 0.1)  # an open hand on the side
    demo = process.build_demo(rec)
    assert demo["motion"]["kind"] == "carry" and demo["motion"]["put_back"] is True
    assert demo["motion"]["lift_m"] == pytest.approx(0.2, abs=0.03)
    assert demo["two_handed"]["width_m"] == pytest.approx(0.28, abs=0.02)
