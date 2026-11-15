"""Write contracts/examples/*.json: one coherent run, changing a ceiling bulb.

    python contracts/examples/make_examples.py

Edit the values here, not the JSON, then run contracts/validate.py.
"""
import hashlib, json, math, sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
SCHEMAS = Path(__file__).resolve().parent.parent
OUT.mkdir(parents=True, exist_ok=True)
RUN = "example-unit-a-bulb"
T = "2026-11-14T15:00:00Z"


def h(s):  # stand-in hash for files the example names but does not ship
    return hashlib.sha256(s.encode()).hexdigest()


def hdr(stream, module):
    return {"schema_version": "0.1", "run_id": RUN, "created_at": T,
            "producer": {"stream": stream, "module": module}}


def ref(f, p):
    return {"file": f, "pointer": p}


def meas(v, prov, f=None, p=None, note=None):
    s = {"provenance": prov}
    if f:
        s["ref"] = ref(f, p)
    if note:
        s["note"] = note
    return {"value": v, "source": s}


def fref(path, fmt=None):
    r = {"path": path, "sha256": h(path)}
    if fmt:
        r["format"] = fmt
    return r


def dump(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2) + "\n")


CAL = "glove-r1-cal-20261114"
GLOVE = "glove-r1"

INSPECT = {"target": "empty E26 socket and fixture cup", "sensor": "rgb_camera",
           "look_for": ["scorch_mark", "broken_glass_in_socket", "bent_contact", "loose_fixture"],
           "standoff_m": 0.15, "min_resolution_mm": 0.5, "views": 2, "on_finding": "ask_human",
           "report": "socket_findings"}

# ---------------------------------------------------------------- requirements
dump("requirements", {
    "header": hdr("A", "agent.requirements"),
    "scenario": {"building_model_id": "PLACEHOLDER-MATTERPORT-ID", "label": "Unit A, 2BR 2BA",
                 "world": ref("world.json", "")},
    "conversation": {"summary": "Landlord wants the hallway ceiling bulb changed when it fails. Agent asked one follow-up: demonstrate the twist at home."},
    "tasks": [{
        "task_id": "bulb",
        "request_text": "Can it swap the bulb in the hallway ceiling light when it burns out?",
        "job": "change_light_bulb",
        "priority": 1,
        "frequency": "on request",
        "target": {"object_class": "a19_bulb", "object_id": "fixture-hall-ceiling-1", "room_id": "hallway-1",
                   "world": ref("world.json", "/fixtures/0")},
        "steps": [
            {"step_id": "go", "text": "Drive to below the hallway ceiling light.", "skill": "navigate"},
            {"step_id": "reach", "text": "Raise the gripper to the bulb.", "skill": "reach"},
            {"step_id": "grasp", "text": "Grip the old bulb firmly enough not to slip, gently enough not to crack it.", "skill": "grasp", "needs_demo": True},
            {"step_id": "unscrew", "text": "Turn the bulb counter-clockwise about three turns until it is free.", "skill": "twist", "needs_demo": True,
             "params": {"turns": 3, "direction": "ccw"}},
            {"step_id": "lower", "text": "Lower the old bulb and put it in the tray.", "skill": "place"},
            {"step_id": "inspect", "text": "Look into the empty socket for scorch marks, broken glass or a bent contact; if there are any, stop and tell the landlord.",
             "skill": "inspect", "inspection": INSPECT},
        ],
        "success_criteria": [
            {"criterion_id": "no-slip", "text": "The bulb does not slip in the grip while turning.", "metric": "bulb_slip_rad", "op": "<=", "value": 0.2},
            {"criterion_id": "no-crush", "text": "Grip force stays under the glass's safe limit.", "metric": "grip_force_N", "op": "<=", "value": 8.0},
            {"criterion_id": "inspected", "text": "Both views of the socket are captured and every defect class is scored.", "metric": "socket_views_captured", "op": ">=", "value": 2, "kind": "action_done"},
            {"criterion_id": "free", "text": "The bulb is out of the socket.", "metric": "bulb_in_socket", "op": "==", "value": 0, "kind": "outcome_confirmed"},
        ],
        "demo": {"required": True, "reason": "Grip force decides between slipping and breaking the glass.",
                 "demo_id": "demo-bulb-1", "grip_id": "grip-bulb-1"},
    }],
    "design_spec": {
        "base": {
            "max_width_m": meas(0.61, "building_scan", "world.json", "/passages/narrowest/width_m", "0.71 m doorway minus 0.05 m each side"),
            "max_length_m": meas(0.80, "default", note="Turn in a 1.02 m hallway."),
            "max_height_stowed_m": meas(1.90, "building_scan", "world.json", "/passages/narrowest/height_m", "2.03 m door head minus margin"),
            "min_turn_width_m": meas(1.02, "building_scan", "world.json", "/rooms/hallway-1/width_m"),
            "mobility": "wheeled",
            "max_step_m": meas(0.02, "building_scan", "world.json", "/floors/0/max_step_m"),
        },
        "reach": {
            "min_height_m": meas(0.30, "default", note="Tray height."),
            "max_height_m": meas(2.47, "building_scan", "world.json", "/fixtures/0/position_m/2"),
            "max_horizontal_m": meas(0.25, "default", note="Base can park directly below."),
        },
        "payload_kg": meas(0.5, "default", note="Bulb is 0.03 kg; margin for a glass shade."),
        "gripper": {
            "min_aperture_m": meas(0.04, "measured_at_home", "demo.json", "/object/dimensions_m/0"),
            "max_aperture_m": meas(0.08, "measured_at_home", "demo.json", "/object/dimensions_m/0", "Bulb is 0.06 m across."),
            "wrist_roll_turns": 3,
            "force_bands": [
                {"task_id": "bulb", "step_id": "unscrew",
                 "band": {"units": "N", "min": 2.0, "max": 6.0, "provenance": "measured_at_home", "calibration_id": CAL},
                 "ref": ref("grip.json", "/bands/1/hold")},
            ],
        },
        "environment": {"floors": "single",
                        "ceiling_height_m": meas(2.62, "building_scan", "world.json", "/rooms/hallway-1/height_m")},
    },
    "open_questions": [
        {"question_id": "q-glass-limit", "text": "What force breaks this bulb? The 8 N limit is a guess until tested.",
         "blocking": False, "task_id": "bulb", "answer": None, "answered_by": None},
    ],
    "approval": {"status": "approved", "approved_by": "lead", "approved_at": T},
})

# ---------------------------------------------------------------- calibration
sensors = [("r-thumb", "thumb", "thumb-tip"), ("r-index", "index", "index-finger-tip"), ("r-middle", "middle", "middle-finger-tip")]
cal_points = {  # raw counts at 50, 100, 200, 500, 800 g
    "r-thumb": [410, 980, 1820, 3050, 3480],
    "r-index": [520, 1150, 2050, 3240, 3560],
    "r-middle": [450, 1010, 1900, 3110, 3500],
}
grams = [50, 100, 200, 500, 800]
dump("calibration", {
    "header": hdr("C", "capture.calibrate"),
    "calibration_id": CAL, "glove_id": GLOVE, "method": "kitchen_scale", "performed_at": "2026-11-14T13:00:00Z",
    "scale_resolution_N": 0.0098,
    "sensors": [{
        "sensor_id": sid,
        "points": [{"raw": r, "force_N": round(g * 0.00981, 3), "mass_g": g} for r, g in zip(cal_points[sid], grams)],
        "model": {"kind": "piecewise_linear",
                  "params": {"knots": [[0, 0.0]] + [[r, round(g * 0.00981, 3)] for r, g in zip(cal_points[sid], grams)]}},
        "valid_raw_range": [0, cal_points[sid][-1]],
        "valid_force_range_N": [0, round(800 * 0.00981, 3)],
        "rmse_N": 0.0,
    } for sid, _, _ in sensors],
})

# ---------------------------------------------------------------- demo
def hand_joints(t):
    """25 joints, a hand closing around a bulb at the object origin. Object frame, metres."""
    joints = []
    wrist = [0.0, -0.09, -0.02]
    joints.append(wrist + [1, 0, 0, 0, 0.02])
    for f, (dx, n) in enumerate([(-0.03, 4), (-0.015, 5), (0.0, 5), (0.015, 5), (0.03, 5)]):
        for k in range(n):
            y = -0.07 + 0.018 * k
            curl = 0.01 * k * (0.5 + 0.5 * math.sin(t))
            joints.append([round(dx, 4), round(y, 4), round(-0.01 + curl, 4), 1, 0, 0, 0, 0.008 if k == n - 1 else 0.01])
    return joints

frames = [{"t_s": t, "left": {"tracked": False}, "right": {"tracked": True, "joints": hand_joints(t)}} for t in (0.0, 1.5, 3.0)]
dump("demo", {
    "header": hdr("C", "capture.api"),
    "demo_id": "demo-bulb-1", "task_id": "bulb", "operator": "p3", "recorded_at": "2026-11-14T14:00:00Z",
    "object": {"object_class": "a19_bulb", "description": "60 W A19, E26 base, frosted glass, in a ceiling batten at home",
               "frame": "object:a19_bulb",
               "pose_in_capture": {"frame": "capture", "position_m": [0.4, 0.1, 1.85], "orientation_wxyz": [1, 0, 0, 0]},
               "how_located": "controller_touch", "dimensions_m": [0.06, 0.06, 0.11], "mass_kg": 0.03},
    "device": {"headset": "Meta Quest 3", "tracking": "webxr-hand-input", "browser": "Meta Quest Browser", "glove_id": GLOVE},
    "hands": {
        "rate_hz": 60,
        "joint_names": json.loads((SCHEMAS / "demo.schema.json").read_text())["properties"]["hands"]["properties"]["joint_names"]["const"],
        "joint_layout": ["x_m", "y_m", "z_m", "qw", "qx", "qy", "qz", "radius_m"],
        "frames": frames,
    },
    "phases": [
        {"phase_id": "p-grasp", "skill": "grasp", "step_id": "grasp", "t_start_s": 0.0, "t_end_s": 1.0, "hand": "right", "how_segmented": "force_threshold"},
        {"phase_id": "p-twist", "skill": "twist", "step_id": "unscrew", "t_start_s": 1.0, "t_end_s": 3.0, "hand": "right", "how_segmented": "manual"},
    ],
    "sync": {"glove_offset_s": 0.042, "method": "tap_event", "residual_s": 0.008},
    "quality": {"tracked_fraction": 0.97, "notes": "Example has 3 frames; a real demo has one per 1/60 s."},
})

# ---------------------------------------------------------------- grip
raw = [[120, 140, 90], [1400, 1650, 1200], [1800, 2100, 1500], [1750, 2000, 1450], [300, 280, 200]]
def to_n(sid, r):
    knots = [[0, 0.0]] + [[c, round(g * 0.00981, 3)] for c, g in zip(cal_points[sid], grams)]
    for (r0, f0), (r1, f1) in zip(knots, knots[1:]):
        if r <= r1:
            return round(f0 + (f1 - f0) * (r - r0) / (r1 - r0), 3)
    return None
force = [[to_n(s[0], v) for s, v in zip(sensors, row)] for row in raw]
dump("grip", {
    "header": hdr("C", "capture.api"),
    "grip_id": "grip-bulb-1", "demo_id": "demo-bulb-1", "glove_id": GLOVE, "calibration_id": CAL,
    "provenance": "measured_at_home",
    "sensors": [{"sensor_id": sid, "hand": "right", "finger": f, "joint": j, "adc_bits": 12} for sid, f, j in sensors],
    "samples": {"rate_hz": 100, "clock": "glove", "t_s": [0.0, 0.8, 1.6, 2.4, 3.0], "raw": raw, "force_N": force,
                "saturated": [[False] * 3 for _ in raw]},
    "bands": [
        {"phase_id": "p-grasp", "sensor_ids": ["r-thumb", "r-index", "r-middle"],
         "hold": {"units": "N", "min": 1.5, "max": 3.5, "provenance": "measured_at_home", "calibration_id": CAL},
         "peak": {"units": "N", "min": 0, "max": 3.9, "provenance": "measured_at_home", "calibration_id": CAL},
         "hold_duration_s": 0.6, "slip_detected": False},
        {"phase_id": "p-twist", "sensor_ids": ["r-thumb", "r-index", "r-middle"],
         "hold": {"units": "N", "min": 2.0, "max": 6.0, "provenance": "measured_at_home", "calibration_id": CAL},
         "peak": {"units": "N", "min": 0, "max": 7.1, "provenance": "measured_at_home", "calibration_id": CAL},
         "hold_duration_s": 1.8, "slip_detected": False},
    ],
    "summary": {"grip_type": "tripod", "contact_fingers": ["thumb", "index", "middle"],
                "notes": "Sum of three fingertips. Five samples shown; a real file has one per 10 ms."},
})

# ---------------------------------------------------------------- design
dump("design", {
    "header": hdr("A", "agent.design"),
    "design_id": "design-2", "iteration": 2, "requirements": ref("requirements.json", "/design_spec"),
    "slots": {
        "base": {"card_id": "base.diff_drive_compact", "params": {"width_m": 0.52, "length_m": 0.60}},
        "reach": {"card_id": "reach.telescoping_mast", "params": {"stroke_m": 1.40}, "mount": "base.top_plate"},
        "wrist": {"card_id": "wrist.continuous_roll", "params": {}, "mount": "reach.carriage"},
        "gripper": {"card_id": "gripper.three_finger_soft", "params": {"max_aperture_m": 0.09}, "mount": "wrist.flange"},
        "sensors": [{"card_id": "sensor.fingertip_force", "params": {"count": 3}, "mount": "gripper.fingertips"},
                    {"card_id": "sensor.wrist_camera", "params": {}, "mount": "wrist.flange"}],
    },
    "wrist": {"roll_turns": 3},
    "checks": [
        {"check_id": "fit-door", "requirement": ref("requirements.json", "/design_spec/base/max_width_m"), "value": 0.52, "op": "<=", "limit": 0.61, "margin": 0.09, "pass": True},
        {"check_id": "reach-top", "requirement": ref("requirements.json", "/design_spec/reach/max_height_m"), "value": 2.55, "op": ">=", "limit": 2.47, "margin": 0.08, "pass": True},
        {"check_id": "stowed-height", "requirement": ref("requirements.json", "/design_spec/base/max_height_stowed_m"), "value": 1.35, "op": "<=", "limit": 1.90, "margin": 0.55, "pass": True},
        {"check_id": "grip-band", "requirement": ref("requirements.json", "/design_spec/gripper/force_bands/0"), "value": 15.0, "op": "covers", "limit": [2.0, 6.0], "pass": True},
        {"check_id": "aperture", "requirement": ref("requirements.json", "/design_spec/gripper/max_aperture_m"), "value": 0.09, "op": ">=", "limit": 0.08, "margin": 0.01, "pass": True},
        {"check_id": "aperture-min", "requirement": ref("requirements.json", "/design_spec/gripper/min_aperture_m"), "value": 0.0, "op": "<=", "limit": 0.04, "margin": 0.04, "pass": True},
        {"check_id": "length", "requirement": ref("requirements.json", "/design_spec/base/max_length_m"), "value": 0.60, "op": "<=", "limit": 0.80, "margin": 0.20, "pass": True},
        {"check_id": "turn", "requirement": ref("requirements.json", "/design_spec/base/min_turn_width_m"), "value": 0.80, "op": "<=", "limit": 1.02, "margin": 0.22, "pass": True},
        {"check_id": "step", "requirement": ref("requirements.json", "/design_spec/base/max_step_m"), "value": 0.02, "op": ">=", "limit": 0.02, "margin": 0.0, "pass": True},
        {"check_id": "reach-low", "requirement": ref("requirements.json", "/design_spec/reach/min_height_m"), "value": 0.30, "op": "<=", "limit": 0.30, "margin": 0.0, "pass": True},
        {"check_id": "reach-out", "requirement": ref("requirements.json", "/design_spec/reach/max_horizontal_m"), "value": 0.30, "op": ">=", "limit": 0.25, "margin": 0.05, "pass": True},
        {"check_id": "payload", "requirement": ref("requirements.json", "/design_spec/payload_kg"), "value": 1.0, "op": ">=", "limit": 0.5, "margin": 0.5, "pass": True},
    ],
    "constraints_applied": ["c-1"],
    "decisions": ref("decisions.jsonl", ""),
})

# ---------------------------------------------------------------- constraints
dump("constraints", {
    "header": hdr("A", "agent.constraints"),
    "constraints": [{
        "constraint_id": "c-1", "iteration": 1, "origin": "nav",
        "reason": "Iteration 1's 0.66 m base did not fit the 0.71 m bedroom doorway with the 0.05 m inflation on each side.",
        "field": "/design_spec/base/max_width_m", "op": "<=", "value": 0.61,
        "evidence": {"path": "iterations/1/route.json", "pointer": "/failure"},
    }],
})

# ---------------------------------------------------------------- build
P = "PLACEHOLDER"
def buy(line, pid, desc, cat, qty, mass, cad, notes=None):
    d = {"line": line, "part_id": pid, "description": desc, "category": cat, "quantity": qty,
         "make_or_buy": "buy", "sourcing_status": "placeholder", "manufacturer": P, "mpn": f"{P}-{line:03d}",
         "mass_kg": mass, "cad": {"file": fref(f"cad/{cad}.step", "step"), "format": "step", "units": "mm"}}
    if notes:
        d["notes"] = notes
    return d

bom = [
    buy(1, "base.diff_drive_compact", "Differential-drive base, 0.52 x 0.60 m, two hub motors, casters", "base", 1, 18.0, "base"),
    buy(2, "reach.telescoping_mast", "Telescoping mast, 1.40 m stroke, lead-screw drive", "reach", 1, 6.5, "mast"),
    buy(3, "wrist.continuous_roll", "Continuous-roll wrist with slip ring", "wrist", 1, 0.6, "wrist"),
    buy(4, "gripper.three_finger_soft", "Three-finger soft gripper, 0.09 m aperture", "gripper", 1, 0.45, "gripper"),
    buy(5, "sensor.fingertip_force", "Fingertip force sensor, 0-20 N", "sensor", 3, 0.01, "fingertip_sensor"),
    buy(6, "compute.sbc", "Single-board computer for the controllers", "compute", 1, 0.2, "sbc"),
    buy(7, "power.battery_24v", "24 V battery pack", "power", 1, 3.2, "battery"),
    buy(9, "sensor.wrist_camera", "RGB camera on the wrist, for inspection", "sensor", 1, 0.05, "wrist_camera"),
    {"line": 8, "part_id": "base.diff_drive_compact/mast_adapter", "description": "Adapter plate, base top plate to mast foot",
     "category": "structure", "quantity": 1, "make_or_buy": "make", "sourcing_status": "placeholder", "mass_kg": 0.35,
     "cad": {"file": fref("cad/mast_adapter.step", "step"), "format": "step", "units": "mm"},
     "fabrication": {"process": "cnc", "material": "6061-T6 aluminium", "drawing": fref("drawings/mast_adapter.pdf", "pdf"), "tolerance_mm": 0.1}},
]
dump("build", {
    "header": hdr("B", "composer.api"),
    "build_id": "build-2", "design_id": "design-2", "robot_name": "Bulb changer, unit A", "revision": "A",
    "source_of_truth": "mjcf",
    "artifacts": [
        {"kind": "mjcf", "file": fref("robot.xml", "mjcf"), "generated_from": None},
        {"kind": "urdf", "file": fref("export/robot.urdf", "urdf"), "generated_from": "mjcf"},
        {"kind": "step_assembly", "file": fref("export/robot_assembly.step", "step"), "generated_from": "mjcf"},
        {"kind": "bom_csv", "file": fref("export/bom.csv", "csv"), "generated_from": "mjcf"},
    ],
    "envelope": {"stowed_width_m": 0.52, "stowed_length_m": 0.60, "stowed_height_m": 1.35, "turning_width_m": 0.80,
                 "mass_kg": 29.6, "max_reach_height_m": 2.55, "min_reach_height_m": 0.30, "max_horizontal_reach_m": 0.30,
                 "payload_kg": 1.0, "max_grip_force_N": 15.0, "max_step_m": 0.02, "battery_runtime_min": 90},
    "bom": bom,
    "cost_summary": {"placeholder_lines": 9},
    "joints": [
        {"name": "wheel_left", "type": "continuous", "parent_link": "base", "child_link": "wheel_left", "axis": [0, 1, 0],
         "limits": {"lower": None, "upper": None, "velocity": 10.0, "effort": 20.0},
         "actuator": {"bom_line": 1, "gear_ratio": 1, "encoder": "hall, 90 counts/rev", "torque_sensing": "current"}},
        {"name": "wheel_right", "type": "continuous", "parent_link": "base", "child_link": "wheel_right", "axis": [0, 1, 0],
         "limits": {"lower": None, "upper": None, "velocity": 10.0, "effort": 20.0},
         "actuator": {"bom_line": 1, "gear_ratio": 1, "encoder": "hall, 90 counts/rev", "torque_sensing": "current"}},
        {"name": "mast_lift", "type": "prismatic", "parent_link": "base", "child_link": "carriage", "axis": [0, 0, 1],
         "limits": {"lower": 0.0, "upper": 1.40, "velocity": 0.15, "effort": 200.0},
         "actuator": {"bom_line": 2, "gear_ratio": 1, "encoder": "absolute linear, 0.1 mm", "torque_sensing": "current"}},
        {"name": "wrist_roll", "type": "continuous", "parent_link": "carriage", "child_link": "wrist", "axis": [0, 0, 1],
         "limits": {"lower": None, "upper": None, "velocity": 3.0, "effort": 2.0},
         "actuator": {"bom_line": 3, "gear_ratio": 50, "encoder": "14-bit absolute", "torque_sensing": "current"}},
        {"name": "finger_close", "type": "prismatic", "parent_link": "wrist", "child_link": "fingers", "axis": [1, 0, 0],
         "limits": {"lower": 0.0, "upper": 0.045, "velocity": 0.05, "effort": 15.0},
         "actuator": {"bom_line": 4, "gear_ratio": 1, "encoder": "12-bit absolute", "torque_sensing": "none"}},
    ],
    "sensors": [{"name": f"tip_{i}", "kind": "fingertip_force", "link": "fingers", "bom_line": 5, "rate_hz": 200, "range": "0-20 N"} for i in (1, 2, 3)]
               + [{"name": "wrist_cam", "kind": "rgb_camera", "link": "wrist", "bom_line": 9, "rate_hz": 30, "range": "0.1-2 m, 0.3 mm/px at 0.15 m"}],
    "mount_points": [
        {"name": "base.top_plate", "parent_bom_line": 1, "child_bom_line": 8,
         "transform": {"frame": "robot:base", "position_m": [0, 0, 0.32], "orientation_wxyz": [1, 0, 0, 0]}, "interface": "4x M6 on 120 mm square"},
        {"name": "adapter.mast_foot", "parent_bom_line": 8, "child_bom_line": 2,
         "transform": {"frame": "robot:base", "position_m": [0, 0, 0.012], "orientation_wxyz": [1, 0, 0, 0]}, "interface": "4x M5 on 80 mm square"},
        {"name": "reach.carriage", "parent_bom_line": 2, "child_bom_line": 3,
         "transform": {"frame": "robot:carriage", "position_m": [0, 0, 0.05], "orientation_wxyz": [1, 0, 0, 0]}, "interface": "ISO 9409-1-50-4-M6"},
        {"name": "wrist.flange", "parent_bom_line": 3, "child_bom_line": 4,
         "transform": {"frame": "robot:wrist", "position_m": [0, 0, 0.06], "orientation_wxyz": [1, 0, 0, 0]}, "interface": "ISO 9409-1-31.5-4-M5"},
    ],
    "assembly": [
        {"step": 1, "title": "Base", "bom_lines": [1, 7], "instructions": "Fit the battery into the base bay.", "verify": "Base powers on and both wheels turn."},
        {"step": 2, "title": "Mast adapter", "bom_lines": [8], "mount_point": "base.top_plate", "instructions": "Bolt the adapter plate to the base top plate.", "tools": ["torque wrench"]},
        {"step": 3, "title": "Mast", "bom_lines": [2], "mount_point": "adapter.mast_foot", "instructions": "Stand the mast on the adapter and bolt it.", "verify": "Mast runs its full 1.40 m stroke without binding."},
        {"step": 4, "title": "Wrist", "bom_lines": [3], "mount_point": "reach.carriage", "instructions": "Mount the wrist on the mast carriage.", "verify": "Wrist turns three full turns each way."},
        {"step": 5, "title": "Gripper and sensors", "bom_lines": [4, 5, 9], "mount_point": "wrist.flange", "instructions": "Mount the gripper, a force sensor on each fingertip, and the camera on the wrist.", "verify": "Each force sensor reads 0 N open and rises when pressed; the camera image is in focus at 0.15 m."},
        {"step": 6, "title": "Compute", "bom_lines": [6], "instructions": "Mount the computer in the base.", "verify": "All joints and sensors enumerate."},
    ],
    "out_of_scope": ["wiring", "fasteners", "firmware", "power_electronics"],
})

# ---------------------------------------------------------------- route
dump("route", {
    "header": hdr("C", "nav.api"),
    "route_id": "route-2", "build_id": "build-2", "world": ref("world.json", ""),
    "map": {"frame": "map", "resolution_m": 0.05, "file": fref("map/floor0.png", "png"), "floor_id": "floor-0", "footprint_inflation_m": 0.05},
    "planner": {"method": "sweep_graph_astar"},
    "feasible": True,
    "waypoints": [
        {"waypoint_id": "dock", "pose": {"x_m": 0.5, "y_m": 0.5, "yaw_rad": 0.0}, "room_id": "living-1", "stop": True},
        {"waypoint_id": "hall-door", "pose": {"x_m": 3.2, "y_m": 0.9, "yaw_rad": 1.571}, "room_id": "hallway-1", "sweep_id": "PLACEHOLDER-SWEEP"},
        {"waypoint_id": "under-light", "pose": {"x_m": 3.2, "y_m": 2.4, "yaw_rad": 1.571}, "room_id": "hallway-1", "stop": True},
    ],
    "segments": [
        {"from": "dock", "to": "hall-door", "length_m": 2.73, "min_clearance_m": 0.40, "max_speed_mps": 0.5},
        {"from": "hall-door", "to": "under-light", "length_m": 1.50, "passage_id": "hallway-1", "passage_width_m": 1.02, "min_clearance_m": 0.20, "max_speed_mps": 0.3},
    ],
    "standoffs": [
        {"task_id": "bulb", "step_id": "grasp", "waypoint_id": "under-light", "target_object_id": "fixture-hall-ceiling-1",
         "target_position_m": [3.2, 2.4, 2.47], "reach_used_m": 2.47, "reach_margin_m": 0.08},
    ],
    "total_length_m": 4.23, "estimated_duration_s": 14,
})

# ---------------------------------------------------------------- trajectory
J = ["mast_lift", "wrist_roll", "finger_close"]
band = {"units": "N", "min": 2.0, "max": 6.0, "provenance": "measured_at_home", "calibration_id": CAL}
dump("trajectory", {
    "header": hdr("B", "motion.api"),
    "trajectory_id": "traj-2", "build_id": "build-2", "route_id": "route-2", "joint_names": J,
    "segments": [
        {"segment_id": "s-reach", "task_id": "bulb", "step_id": "reach", "standoff_waypoint_id": "under-light", "control_mode": "position",
         "t_s": [0, 8], "q": [[0.0, 0.0, 0.0], [1.12, 0.0, 0.0]],
         "ee_target": {"frame": "world", "position_m": [3.2, 2.4, 2.40], "orientation_wxyz": [1, 0, 0, 0]},
         "retarget": {"method": "scripted"}},
        {"segment_id": "s-grasp", "task_id": "bulb", "step_id": "grasp", "demo_phase_id": "p-grasp", "control_mode": "force",
         "t_s": [0, 1], "q": [[1.19, 0.0, 0.0], [1.19, 0.0, 0.017]],
         "force_target": {"units": "N", "min": 1.5, "max": 3.5, "provenance": "measured_at_home", "calibration_id": CAL},
         "retarget": {"method": "ik_mink", "scale": 1.0, "max_residual_m": 0.004}},
        {"segment_id": "s-unscrew", "task_id": "bulb", "step_id": "unscrew", "demo_phase_id": "p-twist", "control_mode": "force",
         "t_s": [0, 3, 6], "q": [[1.19, 0.0, 0.017], [1.20, -9.42, 0.017], [1.21, -18.85, 0.017]],
         "force_target": band, "retarget": {"method": "ik_mink", "scale": 1.0, "max_residual_m": 0.006}},
        {"segment_id": "s-inspect", "task_id": "bulb", "step_id": "inspect", "standoff_waypoint_id": "under-light", "control_mode": "position",
         "t_s": [0, 4, 8], "q": [[1.06, 0.0, 0.0], [1.06, 1.571, 0.0], [1.06, 3.142, 0.0]],
         "ee_target": {"frame": "world", "position_m": [3.2, 2.4, 2.32], "orientation_wxyz": [1, 0, 0, 0]},
         "retarget": {"method": "scripted"}},
    ],
})

# ---------------------------------------------------------------- program
PROGRAM = {
    "header": hdr("A", "agent.program"),
    "program_id": "prog-2", "build_id": "build-2", "route_id": "route-2", "trajectory_id": "traj-2",
    "tasks": [{
        "task_id": "bulb", "schedule": "on request",
        "steps": [
            {"step_id": "go", "skill": "navigate", "waypoint_id": "under-light", "controller_id": "base", "timeout_s": 60, "on_failure": "ask_human",
             "postconditions": [{"kind": "action_done", "metric": "base_pose_error_m", "op": "<=", "value": 0.03}]},
            {"step_id": "reach", "skill": "reach", "segment_id": "s-reach", "controller_id": "arm", "timeout_s": 15, "on_failure": "abort",
             "postconditions": [{"kind": "action_done", "metric": "ee_pose_error_m", "op": "<=", "value": 0.005}]},
            {"step_id": "grasp", "skill": "grasp", "segment_id": "s-grasp", "controller_id": "grip", "timeout_s": 5, "on_failure": "retry", "max_retries": 2,
             "force": {"band": {"units": "N", "min": 1.5, "max": 3.5, "provenance": "measured_at_home", "calibration_id": CAL}, "ref": ref("grip.json", "/bands/0/hold")},
             "postconditions": [{"kind": "action_done", "metric": "grip_force_N", "op": "within", "value": [1.5, 3.5]}]},
            {"step_id": "unscrew", "skill": "twist", "segment_id": "s-unscrew", "controller_id": "grip", "params": {"turns": 3, "direction": "ccw"},
             "timeout_s": 20, "on_failure": "ask_human",
             "force": {"band": band, "ref": ref("grip.json", "/bands/1/hold")},
             "preconditions": [{"kind": "outcome_confirmed", "metric": "bulb_in_grip", "op": "==", "value": 1}],
             "postconditions": [{"kind": "action_done", "metric": "wrist_roll_turns", "op": ">=", "value": 3},
                                {"kind": "outcome_confirmed", "metric": "bulb_in_socket", "op": "==", "value": 0}]},
            {"step_id": "lower", "skill": "place", "controller_id": "arm", "timeout_s": 15, "on_failure": "ask_human",
             "postconditions": [{"kind": "outcome_confirmed", "metric": "bulb_in_tray", "op": "==", "value": 1}]},
            {"step_id": "inspect", "skill": "inspect", "segment_id": "s-inspect", "controller_id": "arm", "inspection": INSPECT,
             "timeout_s": 20, "on_failure": "ask_human",
             "postconditions": [{"kind": "action_done", "metric": "socket_views_captured", "op": ">=", "value": 2},
                                {"kind": "outcome_confirmed", "metric": "socket_findings_count", "op": "==", "value": 0}]},
        ],
    }],
    "controllers": [
        {"controller_id": "base", "kind": "base_velocity", "joints": ["wheel_left", "wheel_right"], "rate_hz": 50,
         "gains": {"kp_linear": 1.2, "kp_angular": 2.0}, "gains_source": "simulated", "tune_on_hardware": True,
         "tuning_notes": "Check against real floor friction; sim uses mu = 0.8."},
        {"controller_id": "arm", "kind": "joint_position_pid", "joints": ["mast_lift", "wrist_roll"], "rate_hz": 500,
         "gains": {"kp": [4000, 8], "kd": [200, 0.4], "ki": [0, 0]}, "gains_source": "simulated", "tune_on_hardware": True},
        {"controller_id": "grip", "kind": "gripper_force", "joints": ["finger_close", "wrist_roll"], "rate_hz": 500,
         "gains": {"kp_force": 0.002, "ki_force": 0.01}, "gains_source": "simulated", "tune_on_hardware": True,
         "tuning_notes": "Bulb slipped in sim below 1.8 N. Do not exceed 8 N until the glass limit is tested (requirements q-glass-limit)."},
    ],
    "safety": {"max_base_speed_mps": 0.5, "max_ee_speed_mps": 0.25, "max_contact_force_N": 8.0,
               "estop": "Hardware button on the base and a wireless stop.",
               "refuse_when": ["A person is within 0.5 m of the mast.", "The light switch reads on.", "Grip force leaves its band twice in a row."]},
    "tests": [
        {"test_id": "t-sim-no-slip", "kind": "sim", "task_id": "bulb", "step_id": "unscrew", "description": "Bulb does not slip while turning.",
         "metric": "bulb_slip_rad", "op": "<=", "threshold": 0.2, "criterion": ref("requirements.json", "/tasks/0/success_criteria/0")},
        {"test_id": "t-sim-no-crush", "kind": "sim", "task_id": "bulb", "description": "Peak grip under the glass limit.",
         "metric": "grip_force_N", "op": "<=", "threshold": 8.0, "criterion": ref("requirements.json", "/tasks/0/success_criteria/1")},
        {"test_id": "t-sim-inspect", "kind": "sim", "task_id": "bulb", "step_id": "inspect", "description": "Both socket views are captured in focus.",
         "metric": "socket_views_captured", "op": ">=", "threshold": 2, "criterion": ref("requirements.json", "/tasks/0/success_criteria/2")},
        {"test_id": "t-bench-inspect", "kind": "bench", "task_id": "bulb", "step_id": "inspect", "description": "Finds a planted scorch mark.",
         "metric": "socket_findings_count", "op": ">=", "threshold": 1,
         "procedure": "Mark a bench socket with a 2 mm scorch dot; run step inspect 10 times; all 10 report scorch_mark and ask a human."},
        {"test_id": "t-bench-twist", "kind": "bench", "task_id": "bulb", "step_id": "unscrew", "description": "Unscrew a bulb from a socket on a bench stand.",
         "metric": "bulb_in_socket", "op": "==", "threshold": 0, "procedure": "Mount an E26 socket at 2.47 m; run step unscrew 10 times; all 10 free the bulb with no crack."},
        {"test_id": "t-site-fit", "kind": "site", "task_id": "bulb", "description": "Drive the route in the real unit.",
         "metric": "min_clearance_m", "op": ">=", "threshold": 0.03, "procedure": "Drive dock to under-light at half speed with a spotter."},
        {"test_id": "t-sim-free", "kind": "sim", "task_id": "bulb", "step_id": "unscrew", "description": "The bulb ends out of the socket.",
         "metric": "bulb_in_socket", "op": "==", "threshold": 0, "criterion": ref("requirements.json", "/tasks/0/success_criteria/3")},
    ],
}

# How each metric is reduced over its window. Postconditions, preconditions and tests all say it.
AGG = {"base_pose_error_m": "final", "ee_pose_error_m": "final", "wrist_roll_turns": "final", "bulb_in_socket": "final",
       "bulb_in_tray": "final", "bulb_in_grip": "final", "socket_views_captured": "final", "socket_findings_count": "count",
       "bulb_slip_rad": "max", "min_clearance_m": "min"}
for st in PROGRAM["tasks"][0]["steps"]:
    for c in st.get("preconditions", []):
        c["aggregate"] = "initial"                           # the state when the step starts
    for c in st["postconditions"]:
        c["aggregate"] = AGG.get(c["metric"], "final")       # grip_force_N at the end of grasp: final
for t in PROGRAM["tests"]:
    t["aggregate"] = AGG.get(t["metric"], "max")             # grip_force_N over the task: max
dump("program", PROGRAM)

# ---------------------------------------------------------------- signals (a stub sim run)
WINDOWS = {"go": (0, 14), "reach": (14, 22), "grasp": (22, 23), "unscrew": (23, 29), "lower": (29, 37), "inspect": (37, 45)}
def ts(name, units, step, values):
    a, b = WINDOWS[step]
    n = len(values)
    return {"name": name, "units": units, "kind": "timeseries", "task_id": "bulb", "step_id": step,
            "t_s": [round(a + (b - a) * i / (n - 1), 3) for i in range(n)], "values": values}
SIGNALS = [
    ts("base_pose_error_m", "m", "go", [0.80, 0.30, 0.05, 0.012]),
    ts("min_clearance_m", "m", "go", [0.40, 0.21, 0.20, 0.35]),
    ts("ee_pose_error_m", "m", "reach", [0.50, 0.10, 0.002]),
    ts("grip_force_N", "N", "grasp", [0.0, 1.2, 2.6]),
    ts("grip_force_N", "N", "unscrew", [3.1, 4.2, 5.4, 4.0, 3.3]),
    ts("bulb_in_grip", "bool", "unscrew", [1, 1, 1, 1]),
    ts("wrist_roll_turns", "turns", "unscrew", [0, 1.0, 2.0, 3.02]),
    ts("bulb_slip_rad", "rad", "unscrew", [0, 0.03, 0.08, 0.05]),
    ts("bulb_in_socket", "bool", "unscrew", [1, 1, 1, 0]),
    ts("bulb_in_tray", "bool", "lower", [0, 0, 1]),
    {"name": "socket_views_captured", "units": "count", "kind": "scalar", "task_id": "bulb", "step_id": "inspect", "value": 2},
    {"name": "socket_findings_count", "units": "count", "kind": "findings", "task_id": "bulb", "step_id": "inspect",
     "findings": [], "synthetic": True},
]
dump("signals", {
    "header": hdr("B", "sim.api"), "program_id": "prog-2", "provenance": "simulated",
    "sim": {"engine": "mujoco", "engine_version": "PLACEHOLDER", "timestep_s": 0.002, "seed": 7,
            "scene": fref("sim/scene.xml", "mjcf"), "robot": fref("robot.xml", "mjcf"), "wall_time_s": 41.0,
            "notes": "Example values, not from a real run. Inspection ran on a clean socket mesh; the bench test plants the defect."},
    "signals": SIGNALS,
})

# ---------------------------------------------------------------- verdict, scored from SIGNALS
def series(metric, step=None):
    pts = []
    for g in SIGNALS:
        if g["name"] == metric and (step is None or g.get("step_id") == step):
            if g["kind"] == "timeseries":
                pts += zip(g["t_s"], g["values"])
            elif g["kind"] == "scalar":
                pts.append((WINDOWS[g["step_id"]][1], g["value"]))
    return [x for _, x in sorted(pts)]
def reduce(agg, xs, metric, step):
    if agg == "count":
        fs = [g for g in SIGNALS if g["name"] == metric and (step is None or g.get("step_id") == step)]
        return len(fs[0]["findings"]) if fs and fs[0]["kind"] == "findings" else sum(1 for x in xs if x == 1)
    return {"initial": lambda v: v[0], "max": max, "min": min, "final": lambda v: v[-1], "mean": lambda v: sum(v) / len(v), "any": lambda v: int(any(x == 1 for x in v))}[agg](xs)
def holds(v, op, t):
    return t[0] <= v <= t[1] if op == "within" else {"<": v < t, "<=": v <= t, "==": v == t, ">=": v >= t, ">": v > t}[op]
steps, tests = [], []
for st in PROGRAM["tasks"][0]["steps"]:
    a, b = WINDOWS[st["step_id"]]
    scored = {}
    for which in ("preconditions", "postconditions"):
        scored[which] = []
        for c in st.get(which, []):
            v = reduce(c["aggregate"], series(c["metric"], st["step_id"]), c["metric"], st["step_id"])
            scored[which].append({"kind": c["kind"], "metric": c["metric"], "aggregate": c["aggregate"], "op": c["op"], "threshold": c["value"],
                                  "value": round(v, 4), "pass": bool(holds(v, c["op"], c["value"]))})
    steps.append({"task_id": "bulb", "step_id": st["step_id"], "status": "done", "t_start_s": a, "t_end_s": b, "retries": 0, **scored})
for t in PROGRAM["tests"]:
    if t["kind"] != "sim":
        continue
    v = reduce(t["aggregate"], series(t["metric"], t.get("step_id")), t["metric"], t.get("step_id"))
    tests.append({"test_id": t["test_id"], "metric": t["metric"], "aggregate": t["aggregate"], "op": t["op"], "threshold": t["threshold"],
                  "value": round(v, 4), "pass": bool(holds(v, t["op"], t["threshold"]))})
by_crit = {t["criterion"]["pointer"].rsplit("/", 1)[1]: t["test_id"] for t in PROGRAM["tests"] if t["kind"] == "sim" and "criterion" in t}
crit_ids = ["no-slip", "no-crush", "inspected", "free"]
passed = {t["test_id"]: t["pass"] for t in tests}
criteria = [{"task_id": "bulb", "criterion_id": cid, "test_id": by_crit[str(i)], "pass": passed[by_crit[str(i)]]} for i, cid in enumerate(crit_ids)]
ok = all(passed.values()) and all(p["pass"] for s_ in steps for p in s_["postconditions"]) and all(c["pass"] for c in criteria)
dump("verdict", {
    "header": hdr("B", "sim.api"), "verdict_id": "verdict-2", "program_id": "prog-2", "build_id": "build-2",
    "route_id": "route-2", "trajectory_id": "traj-2", "provenance": "simulated",
    "status": "pass" if ok else "fail", "steps": steps, "tests": tests, "criteria": criteria, "failures": [],
})
print("wrote", sorted(p.name for p in OUT.glob("*.json")))
