"""The force gloves: read them on the laptop and merge their readings into headset recordings.

Each glove is an ESP32 that prints one line about 100 times a second on a serial port (USB, or
the COM port Windows makes for it over Bluetooth), 115200 baud:

    thumb:0,index:0,middle:0,ring:0,pinky:0

Each value is a fingertip pressure sensor's raw reading, 0 to 4095. It is not a force: the
sensors are not linear and differ from each other, so a raw reading only compares with other
readings of the same sensor until that sensor is calibrated (`Calibration`).

Over Bluetooth Low Energy a glove advertises as `Glove-L` or `Glove-R`. Its one characteristic
holds the same five readings as ten bytes (five little-endian 16-bit numbers, in the order the
serial line prints them). The firmware gives that characteristic no descriptor, so a computer
cannot switch its notifications on; the reader polls it instead, which gives about 30 readings
a second. A glove on Bluetooth only needs power, so it can run from a battery.

`GloveHub` reads the ports in background threads and keeps the last ten minutes, stamped with
the laptop's clock. `merge` puts the readings onto a recording's samples: the backend notes the
laptop time when the headset says a recording started, so sample time t is laptop time
start + t. Each hand's sample gains `glove_raw` (five numbers, thumb to pinky) and, when that
glove is calibrated, `force_n` (the hardest-pressed fingertip, in newtons).

    GLOVE_PORTS=left=COM8,right=COM9          # which port is which hand (USB)
    GLOVE_PORTS=left=ble,right=ble            # over Bluetooth: the gloves named Glove-L and Glove-R
    GLOVE_PORTS=left=ble:Glove-L              # or a Bluetooth name of your choosing
    python -m capture.glove watch              # live readings, to find out which is which
    python -m capture.glove point right index 200    # calibrate: 200 g on the right index tip
"""

from __future__ import annotations

import bisect
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
BAUD = 115200
FULL_SCALE = 4095
KEEP_SECONDS = 600
G = 9.80665
CALIBRATION_FILE = Path(__file__).resolve().parent / "glove_calibration.json"
PERIOD_S = 0.01  # the gloves print 100 lines a second
BLE_CHARACTERISTIC = "a7c4e000-5c1a-4f2e-9d6b-1f0a9e0c0002"
BLE_NAMES = {"left": "Glove-L", "right": "Glove-R"}


def parse_ble(value: bytes) -> list[int] | None:
    """The characteristic's ten bytes -> five ints in printed order. None when it is not ten
    bytes of readings in range."""
    if len(value) < 10:
        return None
    values = [int.from_bytes(value[k : k + 2], "little") for k in range(0, 10, 2)]
    return values if max(values) <= FULL_SCALE else None

# Which printed name is which real finger, per glove. The left glove's sensors are wired in the
# opposite order across the hand from what its firmware prints (checked finger by finger on the
# live graph): its "pinky" is the index finger, and so on. Thumb is right. The right glove has
# not been checked.
FINGER_MAP = {
    "left": {"thumb": "thumb", "index": "pinky", "middle": "ring", "ring": "middle", "pinky": "index"},
    "right": {f: f for f in FINGERS},
}


def remap(hand: str, printed: list[int]) -> list[int]:
    """Readings in the order the glove printed them -> real thumb, index, middle, ring, pinky."""
    wiring = FINGER_MAP.get(hand) or {}
    return [printed[FINGERS.index(wiring.get(finger, finger))] for finger in FINGERS]


def spread_times(arrived: float, count: int, period: float = PERIOD_S) -> list[float]:
    """When `count` lines that arrived together were really sent. The USB serial driver hands
    the stream over in lumps of about a second, so a lump's lines did not happen at once: the
    last is put at the arrival time and the rest one period apart before it."""
    return [arrived - (count - 1 - i) * period for i in range(count)]


def parse_line(line: str) -> list[int] | None:
    """`thumb:12,index:0,...` -> five ints, thumb to pinky. None for anything else (boot
    messages, a line cut in half)."""
    values = {}
    for part in line.strip().split(","):
        name, sep, value = part.partition(":")
        if not sep:
            return None
        try:
            values[name.strip().lower()] = int(float(value))
        except ValueError:
            return None
    if any(f not in values for f in FINGERS):
        return None
    return [min(max(values[f], 0), FULL_SCALE) for f in FINGERS]


class Calibration:
    """Raw reading -> newtons, one curve per sensor: straight lines between measured points
    (a known weight pressed on the fingertip), from (0, 0). A sensor with fewer than two
    measured points is uncalibrated."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else CALIBRATION_FILE
        try:
            self.points = json.loads(self.path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            self.points = {}

    def add(self, hand: str, finger: str, raw: float, grams: float) -> None:
        self.points.setdefault(hand, {}).setdefault(finger, []).append([round(float(raw), 1), round(grams * G / 1000.0, 4)])
        self.points[hand][finger].sort()
        self.path.write_text(json.dumps(self.points, indent=1), encoding="utf8")

    def calibrated(self, hand: str) -> bool:
        return all(len(self.points.get(hand, {}).get(f, [])) >= 2 for f in FINGERS)

    def newtons(self, hand: str, raw: np.ndarray) -> np.ndarray | None:
        """(n, 5) raw -> (n, 5) newtons, or None when any of the hand's sensors is uncalibrated."""
        if not self.calibrated(hand):
            return None
        out = np.zeros_like(raw, dtype=float)
        for k, finger in enumerate(FINGERS):
            pts = np.array([[0.0, 0.0]] + self.points[hand][finger])
            out[:, k] = np.interp(raw[:, k], pts[:, 0], pts[:, 1])
        return out


class GloveReader:
    """One glove on one serial port, read in a background thread."""

    def __init__(self, hand: str, port: str):
        self.hand, self.port = hand, port
        self.times: deque[float] = deque(maxlen=KEEP_SECONDS * 120)
        self.values: deque[list[int]] = deque(maxlen=KEEP_SECONDS * 120)
        self.error: str | None = None
        self.resets = 0  # times the glove's ESP32 restarted while we listened
        self.last_reset: float | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"glove-{hand}", daemon=True)

    def start(self) -> "GloveReader":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def feed(self, when: float, values: list[int]) -> None:
        with self._lock:
            self.times.append(when)
            self.values.append(values)

    def _run(self) -> None:
        import serial  # pyserial; imported here so the rest of capture/ works without it

        while not self._stop.is_set():
            try:
                with serial.Serial(self.port, BAUD, timeout=0.05) as link:
                    self.error = None
                    heard = time.time()
                    pending = b""
                    while not self._stop.is_set():
                        chunk = link.read(max(1, link.in_waiting))
                        now = time.time()
                        if chunk:
                            *lines, pending = (pending + chunk).split(b"\n")
                            readings = []
                            for line in lines:
                                text = line.decode("ascii", "replace")
                                if "rst:" in text:  # the ESP32's boot banner: it restarted
                                    self.resets += 1
                                    self.last_reset = now
                                values = parse_line(text)
                                if values is not None:
                                    readings.append(remap(self.hand, values))
                            if readings:
                                heard = now
                                for when, values in zip(spread_times(now, len(readings)), readings):
                                    self.feed(when, values)
                        elif now - heard > 10.0:
                            # A glove that was unplugged and plugged back leaves this handle open
                            # and silent on Windows: reopen the port. Ten seconds, because a
                            # glove that restarted needs a few to boot before it streams.
                            raise OSError("no readings for 10 s: reopening the port")
            except Exception as exc:  # noqa: BLE001 -- unplugged, busy, wrong port: say so and retry
                self.error = str(exc)[:200]
                self._stop.wait(2.0)

    def window(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """Readings between two laptop times: (times, (n, 5) raw)."""
        with self._lock:
            times = list(self.times)
            lo, hi = bisect.bisect_left(times, t0), bisect.bisect_right(times, t1)
            return np.array(times[lo:hi]), np.array(list(self.values)[lo:hi], dtype=float).reshape(-1, 5)

    def status(self) -> dict:
        with self._lock:
            now = time.time()
            recent = sum(1 for t in list(self.times)[-400:] if now - t <= 2.0)
            last = self.values[-1] if self.values else None
            age = now - self.times[-1] if self.times else None
        return {"hand": self.hand, "port": self.port, "rate_hz": round(recent / 2.0, 1), "last": last,
                "last_age_s": None if age is None else round(age, 2), "error": self.error,
                "resets": self.resets,
                "last_reset_s_ago": None if self.last_reset is None else round(now - self.last_reset, 1)}  # fmt: skip


class BleGloveReader(GloveReader):
    """One glove over Bluetooth Low Energy: found by name, then its characteristic read in a
    loop. `port` is shown as `ble:<name>`."""

    def __init__(self, hand: str, name: str | None = None):
        self.name = name or BLE_NAMES[hand]
        super().__init__(hand, f"ble:{self.name}")

    def _run(self) -> None:
        import asyncio

        asyncio.run(self._loop())

    async def _loop(self) -> None:
        import asyncio

        from bleak import BleakClient, BleakScanner  # imported here: only this reader needs it

        while not self._stop.is_set():
            try:
                device = await BleakScanner.find_device_by_filter(
                    lambda d, adv: (d.name or adv.local_name or "") == self.name, timeout=15.0
                )
                if device is None:
                    raise OSError(f"{self.name} is not advertising (is the glove powered?)")
                async with BleakClient(device, timeout=20.0) as client:
                    if self.times:  # a reconnect: the glove went away, most likely a restart
                        self.resets += 1
                        self.last_reset = time.time()
                    self.error = None
                    while not self._stop.is_set():
                        values = parse_ble(bytes(await client.read_gatt_char(BLE_CHARACTERISTIC, use_cached=False)))
                        if values is not None:
                            self.feed(time.time(), remap(self.hand, values))
            except Exception as exc:  # noqa: BLE001 -- out of range, restarted, radio busy: retry
                self.error = (str(exc) or type(exc).__name__)[:200]
                await asyncio.sleep(1.0)


def make_reader(hand: str, port: str) -> GloveReader:
    """`COM8` -> the serial reader; `ble` or `ble:<name>` -> the Bluetooth one."""
    if port.lower().startswith("ble"):
        return BleGloveReader(hand, port.partition(":")[2].strip() or None)
    return GloveReader(hand, port)


class GloveHub:
    def __init__(self, calibration: Calibration | None = None):
        self.readers: dict[str, GloveReader] = {}
        self.calibration = calibration or Calibration()

    @classmethod
    def from_env(cls) -> "GloveHub":
        """Start a reader for each `hand=port` in `GLOVE_PORTS` (comma separated). No variable,
        no gloves."""
        hub = cls()
        for item in filter(None, (os.environ.get("GLOVE_PORTS") or "").split(",")):
            hand, sep, port = item.partition("=")
            if sep and hand.strip() in ("left", "right"):
                hub.readers[hand.strip()] = make_reader(hand.strip(), port.strip()).start()
        return hub

    def status(self) -> list[dict]:
        return [r.status() | {"calibrated": self.calibration.calibrated(r.hand)} for r in self.readers.values()]

    def merge(self, recording: dict, started: float) -> dict:
        """Put each glove's readings on the recording's samples, in place. `started` is the
        laptop time of sample time 0. Returns what was merged per hand."""
        samples = recording.get("samples") or []
        if not samples or not self.readers:
            return {}
        t = np.array([float(s["t"]) for s in samples]) + started
        report = {}
        for hand, reader in self.readers.items():
            times, raw = reader.window(t[0] - 0.5, t[-1] + 0.5)
            if len(times) < 2:
                report[hand] = {"readings": int(len(times)), "merged": False}
                continue
            at = np.stack([np.interp(t, times, raw[:, k]) for k in range(5)], axis=1)
            newtons = self.calibration.newtons(hand, at)
            for i, sample in enumerate(samples):
                side = sample.get(hand)
                if not isinstance(side, dict):
                    continue
                side["glove_raw"] = [int(round(v)) for v in at[i]]
                if newtons is not None:
                    side["force_n"] = round(float(newtons[i].max()), 3)
                    side["glove_n"] = [round(float(v), 3) for v in newtons[i]]
            report[hand] = {"readings": int(len(times)), "merged": True, "calibrated": newtons is not None,
                            "peak_raw": int(at.max())}  # fmt: skip
        if any(r.get("merged") for r in report.values()):
            device = recording.setdefault("device", {})
            device["glove"] = "ESP32 fingertip pressure, raw 0-4095, thumb to pinky"
            device["glove_link"] = {h: r.port for h, r in self.readers.items()}
        return report


# Raw reading -> newtons for a glove nobody has calibrated: an estimate, the same curve for every
# sensor. It is anchored on one real take, a 0.55 kg bottle lifted in a one-handed grasp
# (demo-20261114-201313): the thumb has to press with at least m g / (2 mu) = 5.4 N (mu 0.5) or the
# bottle slips, and it read about 1000 raw at the low end of the hold, 2500 at the high end, where
# people grip at about twice the slip limit. Above 3500 the sensor flattens, so the top of the curve
# is a floor on the force, not a reading. Good to about a factor of two.
ESTIMATE_POINTS = [(0, 0.0), (80, 0.2), (1000, 5.4), (2500, 10.8), (3300, 18.0), (3800, 30.0), (FULL_SCALE, 45.0)]
ESTIMATE_BASIS = ("estimated from raw glove readings with one generic curve anchored on a 0.55 kg bottle lift; "
                  "not calibrated, good to about a factor of two")


def estimate_newtons(raw):
    """Raw glove units -> estimated newtons (see ESTIMATE_POINTS). Not a calibration."""
    pts = np.array(ESTIMATE_POINTS, dtype=float)
    return np.interp(np.asarray(raw, dtype=float), pts[:, 0], pts[:, 1])


def raw_band(recording: dict) -> dict | None:
    """The grip in raw glove units, for an uncalibrated glove: for the hand that pressed
    hardest, the 10th to 90th percentile of its hardest-pressed fingertip while anything was
    pressed (over 2 % of full scale), and each fingertip's peak. None without glove readings."""
    best = None
    for hand in ("left", "right"):
        raw = np.array([s[hand]["glove_raw"] for s in recording.get("samples", [])
                        if isinstance(s.get(hand), dict) and s[hand].get("glove_raw")], dtype=float)  # fmt: skip
        if len(raw) < 3:
            continue
        hardest = raw.max(axis=1)
        pressed = hardest > 0.02 * FULL_SCALE
        if pressed.sum() < 3:
            continue
        if best is None or hardest[pressed].max() > best[2][best[3]].max():
            best = (hand, raw, hardest, pressed)
    if best is None:
        return None
    hand, raw, hardest, pressed = best
    lo, hi = np.percentile(hardest[pressed], [10, 90])
    return {
        "hand": hand,
        "raw": {"min": int(lo), "max": int(hi), "peak": int(hardest.max())},
        "per_finger_peak": {f: int(raw[:, k].max()) for k, f in enumerate(FINGERS)},
        "near_ceiling": bool(hardest.max() > 3500),  # above about 3500 the sensor barely moves
        # the same band and peaks in estimated newtons (estimate_newtons): a prediction, not a measurement
        "est_n": {"min": round(float(estimate_newtons(lo)), 1), "max": round(float(estimate_newtons(hi)), 1),
                  "peak": round(float(estimate_newtons(hardest.max())), 1)},
        "per_finger_peak_n": {f: round(float(estimate_newtons(raw[:, k].max())), 1) for k, f in enumerate(FINGERS)},
    }


def _watch() -> None:
    hub = GloveHub.from_env()
    if not hub.readers:
        sys.exit("Set GLOVE_PORTS, e.g. GLOVE_PORTS=left=COM8,right=COM9")
    print("Squeeze a glove to see which is which. Ctrl+C to stop.")
    while True:
        time.sleep(0.5)
        print("  ".join(f"{s['hand']}({s['port']}) {s['last']} {s['rate_hz']} Hz{' ERR ' + s['error'] if s['error'] else ''}"
                        for s in hub.status()))  # fmt: skip


def _point(hand: str, finger: str, grams: float, seconds: float = 3.0) -> None:
    hub = GloveHub.from_env()
    if hand not in hub.readers or finger not in FINGERS:
        sys.exit(f"need a glove on {hand!r} in GLOVE_PORTS and a finger from {FINGERS}")
    print(f"Hold {grams:g} g on the {hand} {finger} tip...")
    time.sleep(1.0)
    start = time.time()
    time.sleep(seconds)
    _, raw = hub.readers[hand].window(start, time.time())
    if len(raw) < 20:
        sys.exit("no readings: is the glove streaming?")
    value = float(np.median(raw[:, FINGERS.index(finger)]))
    hub.calibration.add(hand, finger, value, grams)
    print(f"raw {value:.0f} = {grams * G / 1000:.2f} N saved to {hub.calibration.path}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "watch":
        _watch()
    elif len(sys.argv) == 5 and sys.argv[1] == "point":
        _point(sys.argv[2], sys.argv[3], float(sys.argv[4]))
    else:
        sys.exit(__doc__)
