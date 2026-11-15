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
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from agent.design_flow import jobs
from agent.design_flow.skills import slug

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs" / "studio"
EXPORT = REPO / "frontend" / "robot-design" / "data" / "export.py"

# Studio space id (web/worlds.json) -> scenario in world/scenarios/
WORLDS = {"rabinowitz-hall": "jrr"}


# Session (LangGraph thread id) -> its run folder, relative to the repo, set as soon as the run starts,
# so the studio can follow the run's events.jsonl while it is still going.
ACTIVE: dict[str, str] = {}


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
    if scenario is None:
        raise NoWorld(f"No world file for the space \"{world_id}\" yet, so the robot can't be designed or pathed there. "
                      f"Spaces with one: {', '.join(sorted(WORLDS))}.")
    return scenario, json.loads((REPO / "world" / "scenarios" / f"{scenario}.json").read_text())


def model_reads_jobs() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("STUDIO_STANDIN_TASKS") != "1"


def can_plan(skill: str, task: str, world_id: str | None) -> str | None:
    """None when the job can be planned in this space, else why not (checked before asking for a demo).
    With a model reading the job there is nothing to check up front."""
    try:
        _, world = world_for(world_id)
    except NoWorld as e:
        return str(e)
    if model_reads_jobs():
        return None
    return jobs.tasks_for(skill, task, world)[1]


def run_pipeline(request: dict, runs: Path = RUNS, standin_tasks: bool | None = None, timeout_s: int = 1800,
                 session: str | None = None) -> dict:
    world_id = request.get("world") or "rabinowitz-hall"
    scenario, world_doc = world_for(world_id)
    if standin_tasks is None:
        standin_tasks = not model_reads_jobs()
    task = request["task"]
    out = runs / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(task)[:40]}"
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if session:
        ACTIVE[session] = _rel(out)

    world = REPO / "world" / "scenarios" / f"{scenario}.json"
    cmd = [sys.executable, "-m", "agent.run", "--world", str(world), "--out", str(out)]
    if standin_tasks:  # no model reads the job: tasks by rule from the skill and the job's words
        tasks, why_not = jobs.tasks_for(request.get("skill") or task, task, world_doc)
        if tasks is None:
            raise NoWorld(why_not)
        (inputs / "tasks.json").write_text(json.dumps({"tasks": tasks}, indent=1))
        cmd += ["--tasks", str(inputs / "tasks.json"), "--no-model"]
    else:
        cmd += ["--job", task]
    for kind, rec in (request.get("demo") or {}).items():
        path = inputs / f"{kind}.json"
        path.write_text(json.dumps(rec))
        cmd += [f"--{kind}", str(path)]

    env = {**os.environ, "PYTHONPATH": str(REPO)}
    done = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout_s)
    (out / "pipeline.log").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
    if not (out / "design.json").exists():
        raise RuntimeError(f"The design and pathing pipeline stopped (exit {done.returncode}):\n{_tail(done.stderr or done.stdout)}")

    design = json.loads((out / "design.json").read_text())
    lines = done.stdout.strip().splitlines()
    result = {
        "kind": "pipeline",
        "run": _rel(out),
        "world": world_id,
        "scenario": scenario,
        "tasks_source": "rule (the classified skill on this space's anchors)" if standin_tasks else "the job, read by the model",
        "valid": done.returncode == 0,
        "infeasible": not (out / "route.json").exists(),
        "parts": design.get("parts"),
        "price_usd": design.get("price_usd"),
        "mass_kg": design.get("mass_kg"),
        "summary": lines[1:] if lines and lines[0].startswith("run folder:") else lines,
        "snapshot": None,
    }
    if not result["infeasible"]:
        snap = out / "snapshot.json"
        exported = subprocess.run([sys.executable, str(EXPORT), "--run", str(out), "--scenario", scenario, "--out", str(snap)],
                                  cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
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
