import numpy as np
import pytest

from capture import glove, process, synthetic


def test_parse_line_takes_the_gloves_format_and_nothing_else():
    assert glove.parse_line("thumb:12,index:0,middle:4095,ring:7,pinky:1\r\n") == [12, 0, 4095, 7, 1]
    assert glove.parse_line("thumb:9999,index:-5,middle:0,ring:0,pinky:0") == [4095, 0, 0, 0, 0]  # clamped
    for junk in ("", "rst:0x1 (POWERON_RESET)", "thumb:1,index:2", "thumb:a,index:0,middle:0,ring:0,pinky:0"):
        assert glove.parse_line(junk) is None


def _hub(tmp_path, start, seconds=6.0, peak=2000):
    hub = glove.GloveHub(glove.Calibration(tmp_path / "cal.json"))
    reader = glove.GloveReader("right", "TEST")  # never started: fed by hand
    for k in range(int(seconds * 100)):
        t = k / 100.0
        press = peak if 2.0 <= t <= 4.0 else 0  # squeezed for two seconds
        reader.feed(start + t, [press // 2, press, 0, 0, 0])
    hub.readers["right"] = reader
    return hub


def test_merge_lays_glove_readings_on_the_samples_by_time(tmp_path):
    rec = synthetic.squeeze()  # 3 s
    hub = _hub(tmp_path, start=1000.0)
    report = hub.merge(rec, started=1001.0)  # sample time 0 is laptop time 1001: the squeeze spans t = 1..3
    assert report["right"]["merged"] and report["right"]["calibrated"] is False
    raw = np.array([s["right"]["glove_raw"] for s in rec["samples"]])
    t = np.array([s["t"] for s in rec["samples"]])
    assert raw[t < 0.9].max() == 0 and (raw[(t > 1.1) & (t < 2.9), 1] == 2000).all()
    assert rec["samples"][40]["right"]["force_n"] is None  # uncalibrated: no newtons invented
    assert "left" not in report and rec["samples"][0]["left"].get("glove_raw") is None
    assert rec["device"]["glove"].startswith("ESP32")

    grip = process.build_grip(rec)
    assert grip["source"] == "glove_raw" and grip["force_n"] is None
    assert grip["glove_raw"]["raw"]["peak"] == 2000 and grip["glove_raw"]["per_finger_peak"]["index"] == 2000
    assert grip["glove_raw"]["near_ceiling"] is False


def test_a_calibrated_glove_gives_newtons(tmp_path):
    hub = _hub(tmp_path, start=1000.0)
    for finger in glove.FINGERS:
        hub.calibration.add("right", finger, 1000, 100)  # 100 g reads 1000
        hub.calibration.add("right", finger, 3000, 500)  # 500 g reads 3000
    assert hub.calibration.calibrated("right") and not hub.calibration.calibrated("left")
    rec = synthetic.squeeze()
    assert hub.merge(rec, started=1001.0)["right"]["calibrated"] is True
    mid = rec["samples"][60]["right"]  # t = 2 s, index pressed at 2000: halfway between the points
    assert mid["force_n"] == pytest.approx((0.1 + 0.5) / 2 * 9.80665, abs=0.02)
    grip = process.build_grip(rec)
    assert grip["source"] == "glove" and grip["force_n"]["peak"] == pytest.approx(2.94, abs=0.05)


def test_no_readings_in_the_window_merges_nothing(tmp_path):
    rec = synthetic.squeeze()
    assert _hub(tmp_path, start=1000.0).merge(rec, started=5000.0)["right"]["merged"] is False
    assert rec["samples"][0]["right"].get("glove_raw") is None
    assert process.build_grip(rec)["source"] == "travel"
