"""Write the deployment report for a run: what an engineer needs to program the robot.

    python tools/report/deploy_report.py                  # the example run in contracts/draft_0_1/examples
    python tools/report/deploy_report.py runs/<run_id>    # a real run folder

Writes <run>/export/DEPLOY.md. Every number comes from a run file; nothing is written by a model.
The run is validated first. If it fails, the report is not written unless --force is given, and
then it opens with the errors.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contracts" / "draft_0_1"))
from validate import check  # noqa: E402

NEEDED = ("requirements", "build", "route", "trajectory", "program", "signals", "verdict", "grip")


def esc(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join(":--" for _ in head) + " |"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def num(x, unit="") -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        x = round(x, 4)
    return f"{x} {unit}".strip()


def cond(c: dict, value_key: str = "value") -> str:
    t = c[value_key]
    rhs = f"{t[0]} to {t[1]}" if c["op"] == "within" else t
    return f"{c['aggregate']}({c['metric']}) {c['op']} {rhs}"


def band(b: dict | None) -> str:
    if not b:
        return "–"
    src = "measured at home" if b["provenance"] == "measured_at_home" else "simulated"
    tag = f", calibration {b['calibration_id']}" if b.get("calibration_id") else f", glove {b.get('glove_id')} raw counts"
    return f"{b['min']}–{b['max']} {b['units']} ({src}{tag})"


def mark(ok) -> str:
    return "–" if ok is None else ("pass" if ok else "**FAIL**")


def report(run: Path, f: dict[str, dict], errors: list[str], warnings: list[str]) -> str:
    req, build, route, traj, prog, sig, ver, grip = (f.get(k) for k in NEEDED)
    L: list[str] = []
    w = L.append

    w(f"# Deployment report: {build['robot_name']}")
    w("")
    w(f"Run `{prog['header']['run_id']}`, build `{build['build_id']}` rev {build.get('revision', '–')}, "
      f"program `{prog['program_id']}`. Generated from the run files listed at the end.")
    w("")
    if errors:
        w("> [!CAUTION]")
        w(f"> **This run failed validation ({len(errors)} errors). Do not deploy from it.**")
        for e in errors[:20]:
            w(f"> - {esc(e)}")
        w("")
    w("> [!WARNING]")
    w(f"> **Simulated only.** Every result here comes from {sig['sim']['engine']} {sig['sim']['engine_version']} "
      f"(timestep {sig['sim']['timestep_s']} s, seed {sig['sim']['seed']}), not from hardware. "
      "Forces were measured at home on the demonstration object, not in the building. "
      "Controller gains are starting points from simulation.")
    w("")

    # ------------------------------------------------------------ summary
    w("## Summary")
    w("")
    n_sim = len(ver["tests"])
    n_pass = sum(t["pass"] for t in ver["tests"])
    placeholders = sum(1 for b in build["bom"] if b["sourcing_status"] == "placeholder")
    retune = [c["controller_id"] for c in prog["controllers"] if c["tune_on_hardware"]]
    open_q = [q for q in req["open_questions"] if not q.get("answer")]
    w(table(["", ""], [
        ["Simulated verdict", f"**{ver['status'].upper()}**: {n_pass} of {n_sim} sim tests pass"],
        ["Tasks", ", ".join(t["task_id"] for t in prog["tasks"])],
        ["Route", f"{num(route.get('total_length_m'), 'm')}, about {num(route.get('estimated_duration_s'), 's')}, "
                  f"tightest clearance {num(min(s['min_clearance_m'] for s in route['segments']), 'm')}"],
        ["Controllers to retune on hardware", ", ".join(retune) or "none"],
        ["BOM lines not yet sourced", f"{placeholders} of {len(build['bom'])}"],
        ["Open questions", str(len(open_q))],
    ]))
    w("")

    # ------------------------------------------------------------ robot
    w("## The robot")
    w("")
    env = build["envelope"]
    w(table(["Stowed W × L × H", "Mass", "Reach height", "Payload", "Max grip", "Max step"], [[
        f"{env['stowed_width_m']} × {env['stowed_length_m']} × {env['stowed_height_m']} m", num(env["mass_kg"], "kg"),
        f"{env['min_reach_height_m']}–{env['max_reach_height_m']} m", num(env["payload_kg"], "kg"),
        num(env["max_grip_force_N"], "N"), num(env["max_step_m"], "m")]]))
    w("")
    w("Model: `robot.xml` (MuJoCo MJCF) is the source; " + ", ".join(
        f"`{a['file']['path']}`" for a in build["artifacts"] if a["kind"] != "mjcf") + " are generated from it.")
    w("")
    w("### Joints and actuators")
    w("")
    rows = []
    for j in build["joints"]:
        lim = j["limits"]
        rng = "continuous" if lim["lower"] is None else f"{lim['lower']} to {lim['upper']}"
        a = j["actuator"] or {}
        rows.append([j["name"], j["type"], f"{j['parent_link']} → {j['child_link']}", rng, lim["velocity"], lim["effort"],
                     a.get("gear_ratio", "–"), a.get("encoder", "–"), a.get("torque_sensing", "–"), a.get("bom_line", "–")])
    w(table(["Joint", "Type", "Links", "Range (rad or m)", "Max vel", "Max effort", "Gear", "Encoder", "Torque sensing", "BOM line"], rows))
    w("")
    if build.get("sensors"):
        w("### Sensors")
        w("")
        w(table(["Sensor", "Kind", "On link", "Rate", "Range", "BOM line"],
                [[s["name"], s["kind"], s["link"], num(s.get("rate_hz"), "Hz"), s.get("range", "–"), s["bom_line"]] for s in build["sensors"]]))
        w("")

    # ------------------------------------------------------------ tasks
    vsteps = {(s["task_id"], s["step_id"]): s for s in ver["steps"]}
    plan = {t["task_id"]: t for t in req["tasks"]}
    wps = {x["waypoint_id"]: x for x in route["waypoints"]}
    segs = {s["segment_id"]: s for s in traj["segments"]}
    for t in prog["tasks"]:
        pt = plan[t["task_id"]]
        w(f"## Task `{t['task_id']}`")
        w("")
        w(f"> {pt['request_text']}")
        w("")
        w(f"Job: {pt['job']}. Schedule: {t.get('schedule', '–')}.")
        w("")
        rows = []
        texts = {s["step_id"]: s["text"] for s in pt["steps"]}
        for i, st in enumerate(t["steps"], 1):
            where = []
            if st.get("waypoint_id"):
                p = wps[st["waypoint_id"]]["pose"]
                where.append(f"waypoint {st['waypoint_id']} ({p['x_m']}, {p['y_m']}, {p['yaw_rad']} rad)")
            if st.get("segment_id"):
                sg = segs[st["segment_id"]]
                where.append(f"segment {st['segment_id']} ({sg['control_mode']}, {sg['t_s'][-1]} s)")
            done = "; ".join(cond(c) for c in st["postconditions"] if c["kind"] == "action_done") or "–"
            conf = "; ".join(cond(c) for c in st["postconditions"] if c["kind"] == "outcome_confirmed") or "–"
            vs = vsteps.get((t["task_id"], st["step_id"]))
            res = "–" if not vs else f"{vs['status']}, {vs['t_end_s'] - vs['t_start_s']:.1f} s" + (
                "" if all(p["pass"] for p in vs["postconditions"]) else ", **postcondition failed**")
            rows.append([i, f"**{st['step_id']}** ({st['skill']}): {texts.get(st['step_id'], '')}", "; ".join(where) or "–",
                         st["controller_id"], band(st.get("force", {}).get("band")), done, conf,
                         f"{st['timeout_s']} s, then {st['on_failure']}" + (f" (×{st['max_retries']})" if st.get("max_retries") else ""), res])
        w(table(["#", "Step", "Where", "Controller", "Force to hold", "Done when", "Confirmed when", "Timeout / on failure", "Sim result"], rows))
        w("")
        pre = []
        for st in t["steps"]:
            vs = vsteps.get((t["task_id"], st["step_id"])) or {}
            got = {(c["metric"], c["kind"]): c for c in vs.get("preconditions", [])}
            for c in st.get("preconditions", []):
                r = got.get((c["metric"], c["kind"]))
                pre.append(f"{st['step_id']}: {cond(c)} (sim: {mark(r['pass']) if r else '–'})")
        if pre:
            w("Checked before the step starts: " + "; ".join(pre) + ".")
            w("")
        for st in t["steps"]:
            if "inspection" in st:
                ins = st["inspection"]
                findings = [fd for g in sig["signals"] if g["task_id"] == t["task_id"] and g.get("step_id") == st["step_id"]
                            for fd in g.get("findings", [])]
                synthetic = any(g.get("synthetic") for g in sig["signals"] if g.get("step_id") == st["step_id"] and g["kind"] == "findings")
                w(f"**Inspection, step `{st['step_id']}`.** Target: {ins['target']}. Sensor: {ins['sensor']} at {ins['standoff_m']} m, "
                  f"{ins.get('views', 1)} view(s), features down to {num(ins.get('min_resolution_mm'), 'mm')}. "
                  f"Looks for: {', '.join(ins['look_for'])}. On a finding: {ins['on_finding']}. "
                  f"Findings are written to the signal `{ins.get('report', '–')}`.")
                w("")
                w(f"In simulation: {len(findings)} finding(s)" + (" (synthetic scene)" if synthetic else "") +
                  ". A clean result in sim says the step runs, not that it would spot a real defect; the bench test plants one.")
                w("")

    # ------------------------------------------------------------ forces
    w("## Forces")
    w("")
    w(f"From the demonstration `{grip['demo_id']}` on glove `{grip['glove_id']}`"
      + (f", calibration `{grip['calibration_id']}`." if grip["calibration_id"] else ", **not calibrated: raw counts only, do not use on hardware**."))
    w("")
    rows = [[b["phase_id"], ", ".join(b["sensor_ids"]), band(b["hold"]), num(b["peak"]["max"], b["peak"]["units"]),
             num(b.get("hold_duration_s"), "s"), "yes" if b.get("slip_detected") else "no"] for b in grip["bands"]]
    w(table(["Demo phase", "Sensors summed", "Hold band", "Peak", "Held for", "Slip"], rows))
    w("")
    peak = {}
    for g in sig["signals"]:
        if g["units"] == "N" and g["kind"] == "timeseries":
            peak[(g["name"], g.get("step_id"))] = max(g["values"])
    if peak:
        w("Peak simulated forces: " + "; ".join(f"{n} in {s}: {num(v, 'N')}" for (n, s), v in peak.items()) + ".")
        w("")

    # ------------------------------------------------------------ controllers
    w("## Controllers")
    w("")
    rows = [[c["controller_id"], c["kind"], ", ".join(c["joints"]), num(c["rate_hz"], "Hz"),
             ", ".join(f"{k}={v}" for k, v in c["gains"].items()), c.get("gains_source", "–"),
             "**yes**" if c["tune_on_hardware"] else "no", c.get("tuning_notes", "")] for c in prog["controllers"]]
    w(table(["Controller", "Kind", "Joints", "Rate", "Starting gains", "Gains from", "Retune on hardware", "Notes"], rows))
    w("")

    # ------------------------------------------------------------ safety
    s = prog["safety"]
    w("## Safety")
    w("")
    w(table(["Limit", "Value"], [["Base speed", num(s["max_base_speed_mps"], "m/s")], ["End-effector speed", num(s["max_ee_speed_mps"], "m/s")],
                                 ["Contact force", num(s["max_contact_force_N"], "N")], ["E-stop", s["estop"]]]))
    w("")
    w("The robot stops and says why when:")
    w("")
    for r in s["refuse_when"]:
        w(f"- {r}")
    w("")

    # ------------------------------------------------------------ tests
    vt = {t["test_id"]: t for t in ver["tests"]}
    w("## Acceptance tests")
    w("")
    rows = []
    for t in prog["tests"]:
        v = vt.get(t["test_id"])
        rows.append([t["test_id"], t["kind"], f"{t['task_id']}/{t.get('step_id', '*')}", t["description"],
                     cond(t, "threshold"), num(v["value"]) if v else "–", mark(v["pass"]) if v else "not run"])
    w(table(["Test", "Kind", "Task/step", "Checks", "Pass when", "Sim value", "Sim result"], rows))
    w("")
    for kind, title in (("bench", "Bench checklist"), ("site", "Site checklist")):
        items = [t for t in prog["tests"] if t["kind"] == kind]
        if items:
            w(f"### {title}")
            w("")
            for t in items:
                w(f"- [ ] **{t['test_id']}**: {t.get('procedure', t['description'])} Pass when {cond(t, 'threshold')}.")
            w("")
    crit = {c["criterion_id"]: c for c in ver["criteria"]}
    w("### Success criteria from the plan")
    w("")
    w(table(["Task", "Criterion", "Kind", "Checked by", "Sim result"],
            [[t["task_id"], c["text"], c.get("kind", "action_done"), crit.get(c["criterion_id"], {}).get("test_id", "–"),
              mark(crit.get(c["criterion_id"], {}).get("pass"))] for t in req["tasks"] for c in t["success_criteria"]]))
    w("")

    # ------------------------------------------------------------ open
    w("## Before you deploy")
    w("")
    items = []
    for q in open_q:
        items.append(f"Open question ({'blocking' if q['blocking'] else 'not blocking'}): {q['text']}")
    if placeholders:
        items.append(f"{placeholders} BOM lines are placeholders, not sourced parts. See `build.json`.")
    items += [f"Retune `{c}` on the real robot." for c in retune]
    items.append("Not covered by this package: " + ", ".join(build["out_of_scope"]) + ".")
    if ver["failures"]:
        items += [f"Sim failure, {x['what']}: {x['reason']}" for x in ver["failures"]]
    items += [f"Validator warning: {x}" for x in warnings]
    for i in items:
        w(f"- {i}")
    w("")

    # ------------------------------------------------------------ files
    w("## Run files")
    w("")
    rows = []
    for name in sorted(f):
        p = run / f"{name}.json"
        rows.append([f"`{p.name}`", f.get(name, {}).get("header", {}).get("producer", {}).get("module", "–"),
                     hashlib.sha256(p.read_bytes()).hexdigest()])
    w(table(["File", "Written by", "sha256"], rows))
    w("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", nargs="?", default=str(ROOT / "contracts" / "draft_0_1" / "examples"))
    ap.add_argument("--force", action="store_true", help="write the report even if validation fails")
    a = ap.parse_args()
    run = Path(a.run)
    files, errors, warnings = check(run)
    missing = [n for n in NEEDED if n not in files]
    if missing:
        print(f"cannot write the report: missing {', '.join(n + '.json' for n in missing)}")
        return 1
    if errors and not a.force:
        print(f"{len(errors)} validation errors; fix them or pass --force. First: {errors[0]}")
        return 1
    out = run / "export" / "DEPLOY.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report(run, files, errors, warnings))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
