import numpy as np
import pytest

from capture import body, process, synthetic


def test_hand_shape_tells_an_open_hand_from_a_closed_one():
    wipe = body.hand_shape(synthetic.wipe_table(), "right")
    assert wipe["closure"]["median"] < 0.25 and wipe["aperture_m"]["min"] > 0.05  # a flat hand
    rec = synthetic.move_bin()
    held = body.hand_shape(rec, "right", 1.5, 3.5)  # while carrying
    assert held["closure"]["median"] > 0.7 and held["aperture_m"]["median"] < 0.04
    assert set(held["curl"]) == {"index", "middle", "ring", "pinky"}
    rec["joint_names"] = None
    assert body.hand_shape(rec, "right") is None  # controllers: no skeleton


def test_a_closed_hand_counts_as_holding_without_a_pinch():
    rec = synthetic.move_bin()
    for s in rec["samples"]:
        for side in ("left", "right"):
            s[side]["grip"] = 0.0  # no fingertip ever touches the thumb
    demo = process.build_demo(rec)
    assert demo["motion"]["kind"] == "carry" and demo["two_handed"] is not None


def test_arm_estimate_puts_the_elbow_where_the_arm_has_to_bend():
    n = 4
    head_p = np.tile([0.0, 1.6, 0.0], (n, 1))
    head_q = np.tile([0.0, 0.0, 0.0, 1.0], (n, 1))  # looking along +z
    h = 1.72
    upper, fore = body.UPPER_ARM * h, body.FOREARM * h
    shoulder_r = np.array([-body.SHOULDER_HALF_WIDTH * h, 1.6 - body.EYE_TO_SHOULDER * h, 0.0])  # right is -x
    wrist = np.tile(shoulder_r + [0.0, 0.0, 0.40], (n, 1))  # straight ahead of the right shoulder
    arm = body.estimate_arm(head_p, head_q, wrist, "right", h)
    assert np.allclose(arm["shoulder"][0], shoulder_r, atol=1e-6)
    assert np.allclose(np.linalg.norm(arm["elbow"] - arm["shoulder"], axis=1), upper, atol=1e-4)
    assert np.allclose(np.linalg.norm(wrist - arm["elbow"], axis=1), fore, atol=1e-4)
    want = np.degrees(np.arccos((upper**2 + fore**2 - 0.4**2) / (2 * upper * fore)))
    assert arm["elbow_deg"][0] == pytest.approx(want, abs=0.1)
    assert arm["elbow"][0][1] < shoulder_r[1]  # the elbow hangs below the line to the wrist
    assert arm["elbow"][0][0] < shoulder_r[0]  # and out to the right
    left = body.estimate_arm(head_p, head_q, wrist, "left", h)
    assert left["shoulder"][0][0] > 0
    far = body.estimate_arm(head_p, head_q, wrist + [0, 0, 1.0], "right", h)
    assert far["overreach"].all() and body.arm_summary(far)["leaned_pct"] == 100.0


def test_demo_carries_hand_shape_and_arm():
    demo = process.build_demo(synthetic.open_box())
    assert demo["hand_shape"]["source"] == "tracked finger joints"
    assert demo["arm"]["shoulder_to_wrist_m"]["max"] > demo["arm"]["shoulder_to_wrist_m"]["min"]
    assert "estimated" in demo["arm"]["source"]
