"""Run the design and pathing workflows end to end and write a run folder.

    python -m agent.run --world contracts/world.example.json --tasks agent/tasks.example.json \
        [--demo contracts/demo.example.json --grip contracts/grip.example.json --demo-task t1] --out runs/scratch/<name>

Each step is a plain function `step(state: dict) -> dict` in agent/nodes/, called here in a fixed order.
Exit code 0 only when every file written validates against contracts/.

When intake has questions for the person, the run stops there (exit code 3) and writes them to intake.json.
Run again with `--answers answers.json` ([{"question", "answer"}]) to go on, or with `--proceed` to go on
without answers; the unanswered questions then stay on record as open.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

from . import observe
from .nodes import design, intake, ledger, pathing, prepass, program
from .tools import trace, viz

REPO = Path(__file__).resolve().parents[1]
MAX_ROBOT_FIXES = 5  # the loop stops after this many redesigns
EXIT_WAITING = 3  # intake asked the person something and nobody said to go on without an answer
OUTPUTS = ["world.json", "tasks.json", "demo.json", "grip.json", "requirements.json", "design.json", "decisions.jsonl",
           "robot.xml", "build.json", "route.json", "trajectory.json", "program.json", "intake.json", "trace.json"]


def _validator():
    spec = importlib.util.spec_from_file_location("contracts_validate", REPO / "contracts" / "validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, doc, compact: bool = False) -> None:
    path.write_text(json.dumps(doc, separators=(",", ":")) if compact else json.dumps(doc, indent=2) + "\n")


def pipeline(state: dict) -> dict:
    """intake -> pre-pass -> ledger -> design and compose -> pathing (skipped when no design is feasible)."""
    if "tasks" not in state:
        state = observe.node("0 intake", intake.step)(state)
    observe.emit("tasks", tasks=state["tasks"], intake=state.get("intake"))
    asked = (state.get("intake") or {}).get("questions") or []
    if asked and not state.get("proceed"):  # the person's turn: nothing is designed on a guess
        observe.emit("awaiting_answers", questions=asked, demos=state["intake"].get("demos", []))
        return {**state, "waiting": True}
    if asked:
        state["intake"] = {**state["intake"], "proceeded_without_answers": True}
    top = viz.room_view(state["world"])  # the rooms from above, for the live view (None when frames are off)
    if top:
        observe.emit("room_view", **top)
    tid = state.get("demo_task") or (state["tasks"][0]["id"] if state["tasks"] else None)
    for key in ("demo", "grip"):  # the demonstration files belong to one task
        if state.get(key) is not None:
            state[key + "s"] = {tid: state[key]}
    for name, node in (("1 building pre-pass", prepass), ("2 requirements ledger", ledger)):
        state = observe.node(name, node.step)(state)
        if node is prepass:
            observe.emit("building", demands=state["building"]["demands"], corridors=state["building"]["corridors"])
        elif node is ledger:
            observe.emit("requirements", rows=[{k: r.get(k) for k in ("id", "task", "quantity", "unit", "source")}
                                               | {"value": r["value"] if not isinstance(r["value"], (list, dict)) or len(str(r["value"])) < 60
                                                  else f"{len(r['value'])} entries"}
                                               for r in state["requirements"]["requirements"]],
                         conflicts=state["requirements"]["conflicts"])
    # The loop: a design that pathing cannot use becomes a new constraint, and the design step runs again.
    # A task with no standoff means the arm on that lift does not reach, so that lift-and-arm pair is ruled out.
    state = {**state, "excluded": [], "robot_fixes": []}
    for attempt in range(MAX_ROBOT_FIXES + 1):
        state = observe.node("3-4 design and compose", design.step)(state)
        if state["infeasible"]:
            break
        state = observe.node("5 pathing", pathing.step)(state)
        stuck = sorted({f["task"] for f in state["route"]["failures"] if f.get("task") and f.get("kind") in ("standoff", "no_standoff", None)}
                       | {t["id"] for t in state["tasks"] if not any(s["task"] == t["id"] for s in state["route"]["standoffs"])})
        if not stuck or attempt == MAX_ROBOT_FIXES:
            break
        p = state["design"]["parts"]
        fix = {"n": attempt + 1, "tasks": stuck, "ruled_out": {"lift": p["lift"], "arm": p["arm"]},
               "why": f"no standoff reaches {', '.join(stuck)} with {p['arm']} on lift {p['lift']}",
               "was": {"parts": p, "price_usd": state["design"]["price_usd"]}}
        state = {**state, "excluded": state["excluded"] + [fix["ruled_out"]], "robot_fixes": state["robot_fixes"] + [fix]}
        observe.emit("robot_fix", **fix)
    if state["robot_fixes"]:
        state["decisions"] = state["decisions"] + [{"slot": "loop", "robot_fix": f} for f in state["robot_fixes"]]
    if not state["infeasible"]:
        state = observe.node("5d program", program.step)(state)
        pr = state["program"]
        observe.emit("program", source=pr["source"], model=pr.get("model"), rejected=pr.get("model_rejected"), steps=pr["steps"])
    return state


def write_run(state: dict, out: Path) -> list:
    """Write the run folder; returns the names written."""
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:  # a rerun must not leave an older run's files to be validated
        (out / name).unlink(missing_ok=True)
    _write(out / "world.json", state["world"])
    _write(out / "tasks.json", {"tasks": state["tasks"]})
    for name, key in (("demo.json", "demo"), ("grip.json", "grip")):
        if state.get(key) is not None:
            _write(out / name, state[key])
    _write(out / "requirements.json", state["requirements"])
    _write(out / "design.json", state["design"])
    (out / "decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in state["decisions"]))
    if not state["infeasible"]:
        (out / "robot.xml").write_text(state["robot_xml"])
        _write(out / "build.json", state["build"])
        _write(out / "route.json", state["route"])
        _write(out / "trajectory.json", state["trajectory"], compact=True)
        _write(out / "program.json", state["program"])
    if state.get("intake"):
        _write(out / "intake.json", state["intake"])
    _write(out / "trace.json", {"calls": trace.entries(), "seconds": round(sum(e["seconds"] for e in trace.entries()), 3)})
    return [n for n in OUTPUTS if (out / n).exists()]


def write_waiting(state: dict, out: Path) -> list:
    """What a run that stopped for answers leaves: the world, the tasks as read so far, and intake.json with
    the questions. Older outputs are removed, so the folder never shows a design the questions could change."""
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        (out / name).unlink(missing_ok=True)
    _write(out / "world.json", state["world"])
    _write(out / "tasks.json", {"tasks": state["tasks"]})
    _write(out / "intake.json", state["intake"])
    return ["world.json", "tasks.json", "intake.json"]


def validate_run(out: Path) -> list:
    """[(file, error or None)] for every file in the folder that has a schema in contracts/."""
    v, results = _validator(), []
    for kind in v.KINDS:
        path = out / f"{kind}.json"
        if not path.exists():
            continue
        try:
            v.validate(kind, json.loads(path.read_text()))
            results.append((path.name, None))
        except Exception as e:  # jsonschema.ValidationError, or a file that is not JSON
            results.append((path.name, getattr(e, "message", str(e))))
    return results


def summary(state: dict) -> list:
    """The lines printed at the end of a run."""
    d, lines = state.get("design") or {}, []
    it = state.get("intake") or {}
    if it.get("source") == "model":
        lines.append(f"intake ({it['model']}): {it['understood_as']}")
        lines += [f"  task {t['id']}: {t['skill']} on {t['anchor']}" + (f" with {t['object']}" if t.get("object") else "") for t in state["tasks"]]
        lines += [f"  demo to record: {m['chore']} ({m['kind']})" for m in it["demos"]]
        lines += [f"  answered: {x['question']} -> {x['answer']}" for x in it.get("answers", [])]
        lines += [f"  question{' (unanswered, went on anyway)' if it.get('proceeded_without_answers') else ''}: {q}" for q in it["questions"]]
        lines += [f"  not covered by the tasks: {u}" for u in it.get("unmet", [])]
    if state.get("waiting"):
        return lines + ["waiting for answers; nothing was designed"]
    if state["infeasible"]:
        inf = d.get("infeasible") or {}
        lines.append("design: INFEASIBLE, no candidate passes every check; pathing skipped")
        for c in inf.get("binding_checks", []):
            lines.append(f"  binding: {c['check']} / {c.get('task') or 'building'}: value {c.get('value')} against limit "
                         f"{c.get('limit')} {c.get('unit') or ''} ({', '.join(c.get('requirements', []))}). {c.get('why', '')}")
        if inf.get("closest_parts"):
            p = inf["closest_parts"]
            lines.append(f"  closest: {p['base']} + {p['lift']} + {p['arm']} + {p['gripper']}, ${inf.get('closest_price_usd')}")
    else:
        p = d["parts"]
        lines.append(f"design: {p['base']} + {p['lift']} + {p['arm']} + {p['gripper']}; lidar {p['lidar']} on {p['lidar_mount']}; "
                     f"wrist cam {'yes' if p['wrist_cam'] else 'no'}; ego cam {p['ego_cam']}")
        lines.append(f"  price ${d['price_usd']}, mass {d['mass_kg']} kg ({d.get('considered')} considered, "
                     f"{d.get('composed_and_checked')} composed and checked)")
        route, traj = state["route"], state["trajectory"]
        for t in state["tasks"]:
            mine = [s for s in route["standoffs"] if s["task"] == t["id"]]
            if not mine:
                lines.append(f"{t['id']} {t['skill']}: no standoff")
            for s in mine:
                e = next((x for x in traj["tasks"] if x["task"] == t["id"] and x["standoff"] == s["pose"]), None)
                arm = "no trajectory" if e is None else (f"FAILED in {e['failure']['segment']}: {e['failure']['why']}"
                                                         if e.get("failure") else
                                                         f"ok ({sum(len(g['samples']) for g in e['segments'])} samples)")
                lines.append(f"{t['id']} {t['skill']}: standoff {s['pose']} tip ratio {s.get('tip_ratio')}"
                             + (f" [{s['covers']}]" if "covers" in s else "") + f"; trajectory {arm}")
        legs = route["legs"]
        lines.append(f"route: {len(legs)} legs, {round(sum(l.get('length_m') or 0 for l in legs), 2)} m: "
                     + " > ".join([legs[0]["from"]] + [l["to"] for l in legs] if legs else []))
    for f in state.get("robot_fixes", []):
        lines.append(f"robot fix {f['n']}: {f['why']}; was ${f['was']['price_usd']}")
    if not state["infeasible"] and state.get("program"):
        pr = state["program"]
        lines.append(f"program: {len(pr['steps'])} steps, written by " + (f"the model ({pr['model']})" if pr["source"] == "model" else "rule")
                     + (f"; the model's program was rejected: {'; '.join(pr['model_rejected']['problems'][:3])}" if pr.get("model_rejected") else ""))
    for c in d.get("checks", []):
        if c["status"] == "not_assessable":
            lines.append(f"not_assessable: {c['check']} / {c.get('task') or 'building'}: {c.get('why', '')}")
    for c in state["requirements"]["conflicts"]:
        lines.append(f"conflict: {c.get('kind')} / {c.get('task')}: {c.get('note', '')}" + (" [ask the user]" if c.get("ask_user") else ""))
    if not state["infeasible"]:
        mine = {f["task"] for f in state["route"]["failures"] if f.get("task")}
        for f in state["route"]["failures"]:
            if f.get("kind") == "no_standoff" and any(f"task {t}" in str(f.get("reason")) for t in mine):
                continue  # nav's echo of a standoff failure listed under its task
            lines.append(f"failure (route): {f.get('task') or f.get('leg') or ''} {f.get('kind', '')}: {f.get('reason') or f.get('why')}")
            reasons = {}
            for n in f.get("notes", []):  # "stroke 3: target 6: out of reach ..." -> one line per distinct reason
                head, _, why = n.partition(": ")
                reasons.setdefault(why.split(": ", 1)[-1] if why.startswith("target ") else why, []).append(head)
            for why, heads in reasons.items():
                lines.append(f"    {heads[0]}" + (f" to {heads[-1]}" if len(heads) > 1 else "") + f" ({len(heads)}): {why}")
        for f in state["trajectory"]["failures"]:
            if f.get("kind") != "standoff":  # standoff failures are already listed under the route
                lines.append(f"failure (trajectory): {f.get('task')} at {f.get('standoff')}, {f.get('segment')}: {f.get('why')}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.run", description=__doc__.split("\n")[0])
    ap.add_argument("--world", required=True)
    ap.add_argument("--tasks", help="a task list in JSON; not needed with --job")
    ap.add_argument("--job", help="the job in words; a model turns it into the task list (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--frames", action="store_true", help="also render the robot as the run goes, for the live view in web/")
    ap.add_argument("--no-model", action="store_true", help="skip every model step; tasks come from --tasks, the program by rule")
    ap.add_argument("--answers", help='the person\'s answers to intake\'s questions: a JSON list of {"question", "answer"}')
    ap.add_argument("--proceed", action="store_true", help="do not stop when intake has questions; they stay on record as unanswered")
    ap.add_argument("--demo")
    ap.add_argument("--grip")
    ap.add_argument("--demo-task", help="the task id the demo and grip files belong to (default: the first task)")
    ap.add_argument("--radius", type=float, default=prepass.DEFAULT_RADIUS_M,
                    help="pre-pass disc radius in metres: half the narrowest base width in the catalog")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    t0 = time.perf_counter()
    trace.reset()
    if not a.tasks and not a.job:
        ap.error("give --tasks or --job")
    if a.no_model:
        __import__("os").environ["AGENT_NO_MODEL"] = "1"
    state = {"world": json.loads(Path(a.world).read_text()), "tasks_file": a.tasks, "prepass_radius_m": a.radius,
             "job": a.job, "use_model": not a.no_model, "proceed": a.proceed,
             "answers": json.loads(Path(a.answers).read_text()) if a.answers else []}
    state["demo_task"] = a.demo_task
    if a.demo:
        state["demo"] = json.loads(Path(a.demo).read_text())
    if a.grip:
        state["grip"] = json.loads(Path(a.grip).read_text())
    out = Path(a.out)
    observe.start_events(out, frames=a.frames)
    observe.emit("run_start", job=a.job, tasks_file=a.tasks, world=state["world"], model_steps=bool(state["use_model"]))

    @observe.span("design and pathing run", "chain", outputs=lambda s: {"summary": summary(s)})
    def traced_run(world: str, job: str, out: str):
        observe.note_url()
        observe.emit("trace", url=observe._state["url"])
        return pipeline(state)

    try:
        state = traced_run(state["world"].get("id"), a.job or f"tasks from {a.tasks}", a.out)
    except Exception as e:
        observe.emit("run_end", ok=False, error=f"{type(e).__name__}: {e}")
        observe.finish()
        raise

    if state.get("waiting"):
        written = write_waiting(state, out)
        qs = state["intake"]["questions"]
        print(f"run folder: {out} ({len(written)} files, {round(time.perf_counter() - t0, 1)} s)")
        print(f"waiting for {len(qs)} answer{'s' if len(qs) != 1 else ''}; nothing was designed:")
        for q in qs:
            print(f"  question: {q}")
        print(f"answer in a JSON list of {{\"question\", \"answer\"}} and run again with --answers, or run again with --proceed")
        observe.emit("run_end", ok=True, waiting=True, seconds=round(time.perf_counter() - t0, 1))
        observe.finish()
        return EXIT_WAITING

    written = write_run(state, out)
    checked = validate_run(out)
    print(f"run folder: {out} ({len(written)} files, {round(time.perf_counter() - t0, 1)} s)")
    for line in summary(state):
        print(line)
    bad = [(n, e) for n, e in checked if e]
    print(f"validation: {len(checked) - len(bad)} of {len(checked)} files fit their schema"
          + "".join(f"\n  FAIL {n}: {e}" for n, e in bad))
    observe.emit("run_end", ok=not bad, summary=summary(state), seconds=round(time.perf_counter() - t0, 1))
    url = observe.finish()
    if observe.enabled():
        print(f"trace: {url or 'sent to LangSmith project ' + repr(__import__('os').environ.get('LANGSMITH_PROJECT', 'default'))}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
