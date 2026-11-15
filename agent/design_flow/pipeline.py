"""The design step as the design and pathing pipeline (python -m agent.run), for the design workflow.

    designer = make_pipeline_designer()
    result = designer.invoke({"task": "wipe the tables", "demo": {"demo": {...}, "grip": {...}}, "world": "rabinowitz-hall"})

The pipeline runs as a subprocess through its CLI, so it validates every file and writes its event
log, exactly as a run started by hand would. Its recordings come from the skill store (capture's
demo.json and grip.json). Once it finishes, frontend/robot-design/data/export.py turns the run folder
into the snapshot the Robot Design and route pages read.

Only spaces with a world file can be designed for (WORLDS). Without ANTHROPIC_API_KEY, or with
STUDIO_STANDIN_TASKS=1, no model reads the job: jobs.tasks_for() turns the classified skill and the job's
words into tasks on the world's anchors, and the result says so.

request["options"], when given, steers the design search: {"exclude": [{slot: part}], "require": {slot: part},
"max_price_usd": number}, passed to agent.run as --exclude, --require and --max-price.
stop(session) kills the session's running pipeline (its whole process group, so the composer's workers
too); run_pipeline then raises Stopped, and the run folder keeps what it wrote.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from agent.design_flow import jobs
from agent.design_flow.skills import slug

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs" / "studio"
EXPORT = REPO / "frontend" / "robot-design" / "data" / "export.py"

# The model for the pipeline's own steps in studio runs: Sonnet, as in the rest of the design workflow (the
# command line's default, agent/llm.py, is Opus). AGENT_MODEL in the environment overrides it.
STUDIO_MODEL = "claude-sonnet-5-5"

# Studio space id (web/worlds.json) -> scenario in world/scenarios/
WORLDS = {
    "rabinowitz-hall": "jrr",
    "la-mirada": "la_mirada",  # read from its Matterport scan (world/matterport.py)
    # outdoor lots traced on Vexcel aerial photos (world/scenarios/tools/aerial_worlds.py)
    "lawn-palmetto": "lawn_palmetto",
    "trash-palmetto": "trash_palmetto",
    "pooldeck-lakes": "pooldeck_lakes",
    "parcel-eastland": "parcel_eastland",
    "lawn-sanpedro": "lawn_sanpedro",
}


# Session (LangGraph thread id) -> its run folder, relative to the repo, set as soon as the run starts,
# so the studio can follow the run's events.jsonl while it is still going.
ACTIVE: dict[str, str] = {}

# Session -> the subprocess it is waiting on now (the pipeline, or an export after it), so stop() can kill it.
PROCS: dict[str, subprocess.Popen] = {}
STOPPED: set[str] = set()  # sessions told to stop: run_pipeline raises Stopped at its next step
_LOCK = threading.Lock()
STOP_MESSAGE = "Stopped by you"


class Stopped(RuntimeError):
    """The person stopped the design run (stop())."""

    def __init__(self, message: str = STOP_MESSAGE):
        super().__init__(message)


def running(session: str) -> bool:
    """Whether the session has a pipeline subprocess going right now."""
    proc = PROCS.get(session)
    return proc is not None and proc.poll() is None


def _kill(proc: subprocess.Popen, grace_s: float = 5.0) -> None:
    """TERM the process group (the run and its worker processes), then KILL what is left after `grace_s`."""
    if os.name == "nt":  # Windows has no process groups or SIGKILL: end the process tree with taskkill
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline:  # poll, not wait: the run's own thread is in communicate()
            if proc.poll() is not None:
                try:
                    os.killpg(proc.pid, 0)  # workers can outlive the leader for a moment
                except (ProcessLookupError, PermissionError):
                    return
            time.sleep(0.05)


def stop(session: str) -> bool:
    """Stop the session's design run. True when a subprocess was killed; either way the session is marked, so
    a run between its subprocesses (or about to start one) stops at the next."""
    with _LOCK:
        STOPPED.add(session)
        proc = PROCS.get(session)
    if proc is None or proc.poll() is not None:
        return False
    _kill(proc)
    return True


def clear_stop(session: str) -> None:
    """Forget an earlier stop, before the session's design runs again (a retry)."""
    with _LOCK:
        STOPPED.discard(session)


def _end_stopped(out: Path) -> None:
    """Close the run's event log the way agent.run would have, if the kill came before its run_end."""
    log = out / "events.jsonl"
    text = log.read_text() if log.is_file() else ""
    if any('"kind": "run_end"' in line for line in text.splitlines()):
        return
    with log.open("a") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + json.dumps({"kind": "run_end", "ok": False, "stopped": True}) + "\n")


def _call(cmd: list, session: str | None, out: Path, env: dict, timeout: int) -> subprocess.CompletedProcess:
    """subprocess.run, but killable through stop(session): the child gets its own process group."""
    if session in STOPPED:
        _end_stopped(out)
        raise Stopped()
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    if session:
        with _LOCK:
            PROCS[session] = proc
        if session in STOPPED:  # stopped between the check above and now
            _kill(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, stdout, stderr)
    finally:
        if session:
            with _LOCK:
                if PROCS.get(session) is proc:
                    PROCS.pop(session, None)
    if session in STOPPED:
        log = out / "pipeline.log"
        if not log.exists():
            log.write_text((stdout or "") + "\n--- stderr ---\n" + (stderr or "") + "\n--- stopped by you ---\n")
        _end_stopped(out)
        raise Stopped()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def steer_flags(options: dict | None) -> list:
    """agent.run's --exclude, --require and --max-price for the steering options (only those set)."""
    o = options or {}
    flags = []
    if o.get("exclude"):
        flags += ["--exclude", json.dumps(o["exclude"])]
    if o.get("require"):
        flags += ["--require", json.dumps(o["require"])]
    if o.get("max_price_usd") is not None:
        flags += ["--max-price", str(float(o["max_price_usd"]))]
    return flags


class NoWorld(ValueError):
    """The space has no world file, so there is nothing to design or path against."""


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def _tail(text: str, n: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def world_for(world_id: str | None) -> tuple[str, dict]:
    """(scenario, world dict) for a studio space, or NoWorld."""
    world_id = world_id or "rabinowitz-hall"
    scenario = WORLDS.get(world_id)
    if scenario is None:  # a building from the 3D database: its world is the scenario carrying its model id
        from agent.design_flow import buildings

        sid = buildings.sid_for_space(world_id)
        scenario = buildings.scenario_for(sid) if sid else None
    if scenario is None:
        raise NoWorld(f"No world file for the space \"{world_id}\" yet, so the robot can't be designed or pathed there. "
                      f"Spaces with one: {', '.join(sorted(WORLDS))}.")
    return scenario, json.loads((REPO / "world" / "scenarios" / f"{scenario}.json").read_text())


def model_reads_jobs() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("STUDIO_STANDIN_TASKS") != "1"


def can_plan(skill: str, task: str, world_id: str | None) -> str | None:
    """None when the job can be planned in this space, else why not (checked before asking for a demo).
    The pipeline's skills and the space's anchors are the same whether or not a model reads the job, so the
    rule check applies either way; a model only maps the words onto them more freely.
    Mowing's tasks always come by rule from the space's marked lawn (a coverage pattern)."""
    try:
        _, world = world_for(world_id)
    except NoWorld as e:
        return str(e)
    return jobs.tasks_for(skill, task, world)[1]


def run_pipeline(request: dict, runs: Path = RUNS, standin_tasks: bool | None = None, timeout_s: int = 1800,
                 session: str | None = None) -> dict:
    world_id = request.get("world") or "rabinowitz-hall"
    scenario, world_doc = world_for(world_id)
    if standin_tasks is None:
        standin_tasks = not model_reads_jobs()
    task = request["task"]
    if jobs.pipeline_skill(request.get("skill") or task) == "navigate":
        standin_tasks = True  # a coverage pattern is geometry (nav.api.cover); the model's intake does not write one
    out = runs / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(task)[:40]}"
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if session:
        ACTIVE[session] = _rel(out)
    options = request.get("options") or {}

    world = REPO / "world" / "scenarios" / f"{scenario}.json"
    cmd = [sys.executable, "-m", "agent.run", "--world", str(world), "--out", str(out)]
    if standin_tasks:  # no model reads the job: tasks by rule from the skill and the job's words
        tasks, why_not = jobs.tasks_for(request.get("skill") or task, task, world_doc)
        if tasks is None:
            raise NoWorld(why_not)
        (inputs / "tasks.json").write_text(json.dumps({"tasks": tasks}, indent=1))
        cmd += ["--tasks", str(inputs / "tasks.json"), "--no-model"]
    else:  # Claude reads the job; its questions stay on record in intake.json instead of stopping the run
        cmd += ["--job", task, "--proceed"]
    for kind, rec in (request.get("demo") or {}).items():
        path = inputs / f"{kind}.json"
        path.write_text(json.dumps(rec))
        cmd += [f"--{kind}", str(path)]
    cmd += steer_flags(options)

    env = {**os.environ, "PYTHONPATH": str(REPO)}
    env.setdefault("AGENT_MODEL", STUDIO_MODEL)  # the pipeline's model steps (intake, program): Sonnet unless set
    done = _call(cmd, session, out, env, timeout_s)
    (out / "pipeline.log").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
    if done.returncode == 3:  # agent.run.EXIT_WAITING: should not happen with --proceed, but say so plainly
        raise RuntimeError("The pipeline stopped to ask questions about the job; see intake.json in " + _rel(out))
    fell_back = False
    tasks_doc = out / "tasks.json"
    if not standin_tasks and tasks_doc.exists() and not json.loads(tasks_doc.read_text()).get("tasks"):
        # the model read the job but named no task (it asked instead, e.g. "which surface?"): designing for an
        # empty job would "succeed" with a robot for nothing, so plan the rule's tasks and keep its questions
        asked = json.loads((out / "intake.json").read_text()) if (out / "intake.json").exists() else {}
        tasks, why_not = jobs.tasks_for(request.get("skill") or task, task, world_doc)
        if tasks is None:
            raise NoWorld(why_not)
        (inputs / "tasks.json").write_text(json.dumps({"tasks": tasks}, indent=1))
        (inputs / "model_intake.json").write_text(json.dumps(asked, indent=1))
        cmd = [c for c in cmd if c not in ("--job", task, "--proceed")] + ["--tasks", str(inputs / "tasks.json")]
        done = _call(cmd, session, out, env, timeout_s)
        (out / "pipeline.log").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
        fell_back = True
    if not (out / "design.json").exists():
        raise RuntimeError(f"The design and pathing pipeline stopped (exit {done.returncode}):\n{_tail(done.stderr or done.stdout)}")

    design = json.loads((out / "design.json").read_text())
    lines = done.stdout.strip().splitlines()
    result = {
        "kind": "pipeline",
        "run": _rel(out),
        "world": world_id,
        "scenario": scenario,
        "tasks_source": ("rule (the classified skill on this space's anchors)" if standin_tasks
                         else "rule, because the model named no task" if fell_back else "the job, read by the model"),
        "valid": done.returncode == 0,
        "infeasible": not (out / "route.json").exists(),
        "parts": design.get("parts"),
        "price_usd": design.get("price_usd"),
        "mass_kg": design.get("mass_kg"),
        "summary": lines[1:] if lines and lines[0].startswith("run folder:") else lines,
        "snapshot": None,
    }
    if options:
        result["options"] = options
    if result["infeasible"]:  # why nothing passed, the person's limits among it
        result["binding"] = [c.get("why") or c.get("check") for c in (design.get("infeasible") or {}).get("binding_checks", [])]
    intake = out / "inputs" / "model_intake.json" if fell_back else out / "intake.json"
    if intake.exists():  # what the model asked and could not cover; the run went on without answers (--proceed)
        said = json.loads(intake.read_text())
        result["questions"] = said.get("questions") or []
        result["unmet"] = said.get("unmet") or []
    if not result["infeasible"]:  # the robot and its motion for the real-room 3D page (agent/tour_export.py, ~3 s)
        exported = _call([sys.executable, "-m", "agent.tour_export", str(out)], session, out, env, 300)
        result["room"] = exported.returncode == 0 and "frames/tour_robot.glb" in exported.stdout
    if not result["infeasible"]:
        snap = out / "snapshot.json"
        exported = _call([sys.executable, str(EXPORT), "--run", str(out), "--scenario", scenario, "--out", str(snap)],
                         session, out, env, 600)
        if exported.returncode == 0:
            result["snapshot"] = _rel(snap)
        else:
            result["snapshot_error"] = _tail(exported.stderr or exported.stdout, 4)
    return result


def make_pipeline_designer(**options):
    def design(request: dict, config: dict) -> dict:
        session = (config.get("configurable") or {}).get("thread_id")
        return run_pipeline(request, session=session, **options)

    return RunnableLambda(design, name="design and pathing pipeline")
