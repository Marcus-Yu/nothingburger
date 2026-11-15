"""Check run files against the contracts.

    python contracts/validate.py                  # the examples in contracts/examples
    python contracts/validate.py runs/<run_id>    # a real run folder

Checks each <name>.json that has a <name>.schema.json, then the rules a schema
cannot express: refs resolve, ids agree across files, shapes match, and no
uncalibrated force is used to size a robot. Exits 1 on any error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent


def load_schemas() -> tuple[dict[str, dict], Registry]:
    schemas, resources = {}, []
    for p in sorted(HERE.glob("*.schema.json")):
        s = json.loads(p.read_text())
        resources.append((s["$id"], Resource.from_contents(s)))
        schemas[p.name.removesuffix(".schema.json")] = s
    return schemas, Registry().with_resources(resources)


def resolve(doc, pointer: str):
    if pointer == "":
        return doc
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def walk_refs(obj, path=""):
    if isinstance(obj, dict):
        if set(obj) == {"file", "pointer"}:
            yield path, obj
        for k, v in obj.items():
            yield from walk_refs(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_refs(v, f"{path}/{i}")


WARNINGS: set[str] = set()


def walk_objects(obj, path=""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk_objects(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_objects(v, f"{path}/{i}")


def requirement_pointers(spec, path):
    """Every hard requirement in design_spec: each {value, source} leaf and each force band.
    environment is context for the checks, not a requirement of its own."""
    for k, v in spec.items():
        p = f"{path}/{k}"
        if k == "environment":
            continue
        if k == "force_bands":
            yield from (f"{p}/{i}" for i in range(len(v)))
        elif isinstance(v, dict) and set(v) == {"value", "source"}:
            yield p
        elif isinstance(v, dict):
            yield from requirement_pointers(v, p)


def cross_checks(f: dict[str, dict]) -> list[str]:
    err = []
    e = err.append

    # every ref into a file we have must resolve; refs into absent files are only warned about
    for name, doc in f.items():
        for where, r in walk_refs(doc):
            target = r["file"].removesuffix(".json")
            if target in f:
                try:
                    resolve(f[target], r["pointer"])
                except (KeyError, IndexError, ValueError, TypeError):
                    e(f"{name}.json{where}: ref {r['file']}#{r['pointer']} does not resolve")
            else:
                WARNINGS.add(f"{r['file']} not in this folder; refs into it are unchecked")

    # a band copied next to its ref must still equal what the ref points at
    for name, doc in f.items():
        for where, obj in walk_objects(doc):
            r = obj.get("ref")
            if "band" in obj and isinstance(r, dict) and r.get("file", "").removesuffix(".json") in f:
                try:
                    src = resolve(f[r["file"].removesuffix(".json")], r["pointer"])
                except (KeyError, IndexError, ValueError, TypeError):
                    continue
                if src != obj["band"]:
                    e(f"{name}.json{where}/band differs from {r['file']}#{r['pointer']}")

    # one run id across files
    ids = {n: d["header"]["run_id"] for n, d in f.items() if "header" in d}
    if len(set(ids.values())) > 1:
        e(f"run_id differs across files: {ids}")

    req, demo, grip, cal = f.get("requirements"), f.get("demo"), f.get("grip"), f.get("calibration")
    if req and req["approval"]["status"] == "approved":
        for t in req["tasks"]:
            if t["demo"]["required"] and not (t["demo"].get("demo_id") and t["demo"].get("grip_id")):
                e(f"requirements: task {t['task_id']} is approved but its demo is not recorded")
        for b in req["design_spec"]["gripper"]["force_bands"]:
            if b["band"]["units"] != "N":
                e(f"requirements: force band for {b['task_id']}/{b['step_id']} is raw_adc; calibrate the glove before sizing a gripper")
    if demo and grip:
        if grip["demo_id"] != demo["demo_id"]:
            e("grip.demo_id does not match demo.demo_id")
        if grip["glove_id"] != demo["device"]["glove_id"]:
            e("grip.glove_id does not match demo.device.glove_id")
        phases = {p["phase_id"] for p in demo["phases"]}
        for b in grip["bands"]:
            if b["phase_id"] not in phases:
                e(f"grip band phase {b['phase_id']} is not a demo phase")
        names = demo["hands"]["joint_names"]
        for s in grip["sensors"]:
            if s["joint"] not in names:
                e(f"grip sensor {s['sensor_id']} sits on unknown joint {s['joint']}")
    if grip:
        n, s = len(grip["sensors"]), grip["samples"]
        if len(s["t_s"]) != len(s["raw"]) or any(len(r) != n for r in s["raw"]):
            e("grip.samples.raw must be one row per t_s and one column per sensor")
        if "force_N" in s and [len(r) for r in s["force_N"]] != [len(r) for r in s["raw"]]:
            e("grip.samples.force_N must have the same shape as raw")
    if grip and grip["calibration_id"]:
        if not cal:
            e("grip names a calibration but calibration.json is missing")
        elif cal["calibration_id"] != grip["calibration_id"] or cal["glove_id"] != grip["glove_id"]:
            e("grip calibration_id/glove_id do not match calibration.json")
        else:
            missing = {x["sensor_id"] for x in grip["sensors"]} - {x["sensor_id"] for x in cal["sensors"]}
            if missing:
                e(f"calibration.json has no curve for sensors {sorted(missing)}")
    if demo:
        for fr in demo["hands"]["frames"]:
            for hand in ("left", "right"):
                if fr[hand]["tracked"] and len(fr[hand]["joints"]) != len(demo["hands"]["joint_names"]):
                    e(f"demo frame t={fr['t_s']} {hand}: joint count differs from joint_names")

    design, build, route, traj, prog = (f.get(k) for k in ("design", "build", "route", "trajectory", "program"))
    if req and design:
        checked = {c["requirement"]["pointer"] for c in design["checks"] if c["requirement"]["file"] == "requirements.json"}
        for p in requirement_pointers(req["design_spec"], "/design_spec"):
            if p not in checked:
                e(f"design.json has no check for requirements {p}")
    if design and any(not c["pass"] for c in design["checks"]):
        e("design.json contains a failed check; a design is only written after every check passes")
    if build:
        lines = {b["line"] for b in build["bom"]}
        refs = [j["actuator"]["bom_line"] for j in build["joints"] if j["actuator"]]
        refs += [m[k] for m in build["mount_points"] for k in ("parent_bom_line", "child_bom_line")]
        refs += [l for a in build["assembly"] for l in a["bom_lines"]]
        refs += [s["bom_line"] for s in build.get("sensors", [])]
        for r in sorted(set(refs) - lines):
            e(f"build.json refers to BOM line {r}, which does not exist")
        if design and build["design_id"] != design["design_id"]:
            e("build.design_id does not match design.design_id")
    if traj:
        if build:
            unknown = set(traj["joint_names"]) - {j["name"] for j in build["joints"]}
            if unknown:
                e(f"trajectory joints not in build.json: {sorted(unknown)}")
        for s in traj["segments"]:
            if len(s["q"]) != len(s["t_s"]) or any(len(q) != len(traj["joint_names"]) for q in s["q"]):
                e(f"trajectory segment {s['segment_id']}: q must be one row per t_s, one column per joint")
    if build:
        kinds = {x["kind"] for x in build.get("sensors", [])}
        for name, doc in (("requirements", req), ("program", prog)):
            for t in (doc or {}).get("tasks", []):
                for st in t["steps"]:
                    if "inspection" in st and st["inspection"]["sensor"] not in kinds:
                        e(f"{name} step {st['step_id']}: inspects with {st['inspection']['sensor']}, which build.json does not have")
    if req and prog:
        plan = {(t["task_id"], s["step_id"]): s for t in req["tasks"] for s in t["steps"]}
        for t in prog["tasks"]:
            for st in t["steps"]:
                ps = plan.get((t["task_id"], st["step_id"]))
                if ps is None:
                    e(f"program step {t['task_id']}/{st['step_id']} is not in requirements")
                elif ps.get("inspection") != st.get("inspection"):
                    e(f"program step {t['task_id']}/{st['step_id']}: inspection differs from requirements")
    if prog:
        wps = {w["waypoint_id"] for w in route["waypoints"]} if route else None
        segs = {s["segment_id"] for s in traj["segments"]} if traj else None
        ctrls = {c["controller_id"] for c in prog["controllers"]}
        for t in prog["tasks"]:
            for st in t["steps"]:
                if st["controller_id"] not in ctrls:
                    e(f"program step {st['step_id']}: unknown controller {st['controller_id']}")
                if wps is not None and st.get("waypoint_id") and st["waypoint_id"] not in wps:
                    e(f"program step {st['step_id']}: waypoint {st['waypoint_id']} not in route.json")
                if segs is not None and st.get("segment_id") and st["segment_id"] not in segs:
                    e(f"program step {st['step_id']}: segment {st['segment_id']} not in trajectory.json")
                if st.get("force") and st["force"]["band"]["units"] != "N":
                    e(f"program step {st['step_id']}: a deployable program needs forces in N")
        if build:
            joints = {j["name"] for j in build["joints"]}
            for c in prog["controllers"]:
                for j in set(c["joints"]) - joints:
                    e(f"controller {c['controller_id']}: joint {j} not in build.json")
    return err


SUFFIX_UNITS = {"_N": "N", "_m": "m", "_rad": "rad", "_s": "s", "_turns": "turns", "_count": "count"}


def window(signals, metric, task_id, step_id):
    """All samples of metric in a step, or in every step of the task when step_id is None."""
    gs = [g for g in signals if g["name"] == metric and g["task_id"] == task_id and (step_id is None or g.get("step_id") == step_id)]
    return gs


def aggregate(gs, agg):
    if any(g["kind"] == "findings" for g in gs):
        return sum(len(g["findings"]) for g in gs) if agg == "count" else None
    if all(g["kind"] == "timeseries" for g in gs):  # merge steps in time order, not file order
        xs = [x for _, x in sorted((t, x) for g in gs for t, x in zip(g["t_s"], g["values"]))]
    else:
        xs = [x for g in gs for x in (g["values"] if g["kind"] == "timeseries" else [g["value"]])]
    if not xs:
        return None
    return {"initial": xs[0], "max": max(xs), "min": min(xs), "final": xs[-1], "mean": sum(xs) / len(xs),
            "count": sum(1 for x in xs if x == 1), "any": int(any(x == 1 for x in xs))}[agg]


def holds(v, op, t):
    return t[0] <= v <= t[1] if op == "within" else {"<": v < t, "<=": v <= t, "==": v == t, ">=": v >= t, ">": v > t}[op]


def result_checks(f: dict[str, dict]) -> list[str]:
    err = []
    e = err.append
    sig, ver, prog, req = (f.get(k) for k in ("signals", "verdict", "program", "requirements"))
    if sig:
        seen = set()
        for g in sig["signals"]:
            key = (g["name"], g["task_id"], g.get("step_id"))
            if key in seen:
                e(f"signals: {key} appears twice")
            seen.add(key)
            want = next((u for suf, u in SUFFIX_UNITS.items() if g["name"].endswith(suf)), None)
            if want and g["units"] != want:
                e(f"signals: {g['name']} has units {g['units']}, its name says {want}")
            if not want and g["units"] not in ("bool", "count", "fraction"):
                e(f"signals: {g['name']} has no unit suffix, so units must be bool, count or fraction")
            if g["kind"] == "timeseries" and len(g["t_s"]) != len(g["values"]):
                e(f"signals: {g['name']}/{g.get('step_id')}: t_s and values differ in length")
            if g["units"] == "bool" and g["kind"] == "timeseries" and any(x not in (0, 1) for x in g["values"]):
                e(f"signals: {g['name']} is bool but has values other than 0 and 1")
        if prog:
            if sig["program_id"] != prog["program_id"]:
                e("signals.program_id does not match program.json")
            looks = {(t["task_id"], s_["step_id"]): set(s_["inspection"]["look_for"]) for t in prog["tasks"] for s_ in t["steps"] if "inspection" in s_}
            for g in sig["signals"]:
                for fd in g.get("findings", []):
                    allowed = looks.get((g["task_id"], g.get("step_id")))
                    if allowed is None or fd["defect_class"] not in allowed:
                        e(f"signals: finding {fd['defect_class']} is not in the inspection.look_for of {g['task_id']}/{g.get('step_id')}")
            needed = [(t["task_id"], s_["step_id"], c["metric"]) for t in prog["tasks"] for s_ in t["steps"]
                      for c in s_.get("preconditions", []) + s_["postconditions"]]
            needed += [(t["task_id"], t.get("step_id"), t["metric"]) for t in prog["tests"] if t["kind"] == "sim"]
            for task, step, m in needed:
                if not window(sig["signals"], m, task, step):
                    e(f"signals: no {m} for {task}/{step or '*'}, which the program scores")
    if ver and prog:
        for k in ("program_id", "build_id", "route_id", "trajectory_id"):
            if ver[k] != prog[k]:
                e(f"verdict.{k} does not match program.json")
        S = sig["signals"] if sig else []
        if not sig:
            e("verdict.json without signals.json: nothing to check it against")
        all_pass = True

        def score(where, entry, metric, agg, op, thr, task, step):
            nonlocal all_pass
            if (entry.get("metric"), entry.get("aggregate"), entry.get("op", op), entry.get("threshold", thr)) != (metric, agg, op, thr):
                e(f"verdict {where}: metric/aggregate/op/threshold differ from program.json")
            v = aggregate(window(S, metric, task, step), agg)
            if v is None:
                e(f"verdict {where}: cannot recompute {agg}({metric}) from signals")
            elif abs(v - entry["value"]) > 1e-3:
                e(f"verdict {where}: value {entry['value']} but signals give {agg}({metric}) = {round(v, 4)}")
            if entry["pass"] != holds(entry["value"], op, thr):
                e(f"verdict {where}: pass={entry['pass']} contradicts {entry['value']} {op} {thr}")
            all_pass &= entry["pass"]

        sim_tests = {t["test_id"]: t for t in prog["tests"] if t["kind"] == "sim"}
        vt = {}
        for t in ver["tests"]:
            if t["test_id"] in vt:
                e(f"verdict: test {t['test_id']} scored twice")
            vt[t["test_id"]] = t
        for tid in set(sim_tests) ^ set(vt):
            e(f"verdict: sim test {tid} is {'missing' if tid in sim_tests else 'not a sim test in program.json'}")
        for tid in set(sim_tests) & set(vt):
            p_ = sim_tests[tid]
            score(f"test {tid}", vt[tid], p_["metric"], p_["aggregate"], p_["op"], p_["threshold"], p_["task_id"], p_.get("step_id"))
        vsteps = {(s_["task_id"], s_["step_id"]): s_ for s_ in ver["steps"]}
        for t in prog["tasks"]:
            for st in t["steps"]:
                vs = vsteps.get((t["task_id"], st["step_id"]))
                if vs is None:
                    e(f"verdict: step {t['task_id']}/{st['step_id']} has no result")
                    all_pass = False
                    continue
                if vs["status"] != "done":
                    all_pass = False
                if vs["t_end_s"] < vs["t_start_s"]:
                    e(f"verdict: step {st['step_id']} ends before it starts")
                if vs["status"] == "done" and vs["t_end_s"] - vs["t_start_s"] > st["timeout_s"]:
                    e(f"verdict: step {st['step_id']} took {vs['t_end_s'] - vs['t_start_s']} s, over its {st['timeout_s']} s timeout, but is marked done")
                for g in S:
                    if g["task_id"] == t["task_id"] and g.get("step_id") == st["step_id"] and g["kind"] == "timeseries":
                        if g["t_s"] and (min(g["t_s"]) < vs["t_start_s"] - 1e-6 or max(g["t_s"]) > vs["t_end_s"] + 1e-6):
                            e(f"signals: {g['name']} for step {st['step_id']} has samples outside the step's {vs['t_start_s']}-{vs['t_end_s']} s")
                for which in ("preconditions", "postconditions"):
                    got = {(c["metric"], c["kind"]): c for c in vs[which]}
                    for c in st.get(which, []):
                        if which == "preconditions" and c["aggregate"] != "initial":
                            e(f"program step {st['step_id']}: precondition {c['metric']} must use aggregate initial")
                        g = got.get((c["metric"], c["kind"]))
                        if g is None:
                            e(f"verdict: step {st['step_id']} does not score {which[:-1]} {c['metric']}")
                            all_pass = False
                            continue
                        score(f"step {st['step_id']} {which[:-1]} {c['metric']}", g, c["metric"], c["aggregate"], c["op"], c["value"], t["task_id"], st["step_id"])
                        if vs["status"] == "done" and not g["pass"]:
                            e(f"verdict: step {st['step_id']} is done but its {which[:-1]} {c['metric']} failed")
        if req:
            crit_test = {}
            for tid, t in sim_tests.items():
                if "criterion" in t:
                    crit_test[t["criterion"]["pointer"]] = tid
            vc = {(c["task_id"], c["criterion_id"]): c for c in ver["criteria"]}
            for i, t in enumerate(req["tasks"]):
                for j, c in enumerate(t["success_criteria"]):
                    ptr = f"/tasks/{i}/success_criteria/{j}"
                    got = vc.get((t["task_id"], c["criterion_id"]))
                    if ptr not in crit_test:
                        e(f"program.json has no sim test for requirements criterion {t['task_id']}/{c['criterion_id']}")
                    if got is None:
                        e(f"verdict: criterion {t['task_id']}/{c['criterion_id']} not scored")
                        all_pass = False
                    elif ptr in crit_test and (got["test_id"] != crit_test[ptr] or got["pass"] != vt.get(crit_test[ptr], {}).get("pass")):
                        e(f"verdict: criterion {c['criterion_id']} must follow test {crit_test[ptr]}")
                    elif got:
                        all_pass &= got["pass"]
        if ver["status"] != "error" and (ver["status"] == "pass") != all_pass:
            e(f"verdict.status is {ver['status']} but the scored results say {'pass' if all_pass else 'fail'}")
    return err


def file_checks(run_dir: Path, files: dict[str, dict]) -> list[str]:
    """Every file a contract names by path and sha256: wrong hash is an error, missing is a warning."""
    import hashlib
    err, missing = [], set()
    for name, doc in files.items():
        for where, o in walk_objects(doc):
            if set(o) >= {"path", "sha256"} and isinstance(o.get("path"), str) and len(str(o.get("sha256"))) == 64:
                p = run_dir / o["path"]
                if not p.is_file():
                    missing.add(o["path"])
                elif hashlib.sha256(p.read_bytes()).hexdigest() != o["sha256"]:
                    err.append(f"{name}.json{where}: {o['path']} does not match its sha256")
    if missing:
        WARNINGS.add(f"{len(missing)} referenced files are not in the folder, so their hashes are unchecked: {', '.join(sorted(missing)[:6])}{' …' if len(missing) > 6 else ''}")
    return err


def check(run_dir: Path) -> tuple[dict[str, dict], list[str], list[str]]:
    """Load and check every contract file in run_dir. Returns (files, errors, warnings)."""
    WARNINGS.clear()
    schemas, registry = load_schemas()
    files, errors = {}, []
    for name, schema in schemas.items():
        p = run_dir / f"{name}.json"
        if not p.exists():
            continue
        doc = json.loads(p.read_text())
        files[name] = doc
        v = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for er in sorted(v.iter_errors(doc), key=lambda x: list(x.absolute_path)):
            loc = "/" + "/".join(map(str, er.absolute_path))
            errors.append(f"{name}.json{loc}: {er.message[:300]}")
    if not errors:  # cross-file rules assume each file has its schema's shape
        errors += cross_checks(files)
        errors += result_checks(files)
        errors += file_checks(run_dir, files)
    return files, errors, sorted(WARNINGS)


def main(run_dir: Path) -> int:
    files, errors, warnings = check(run_dir)
    for w in warnings:
        print("WARN ", w)
    for er in errors:
        print("ERROR", er)
    print(f"{len(files)} files checked in {run_dir}: {'OK' if not errors else f'{len(errors)} errors'}")
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "examples"))
