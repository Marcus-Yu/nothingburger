"""LangSmith tracing for a run: one root run, a child per step, and a grandchild per tool call.

Off unless LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set (in the environment or in the repo's
.env) and the `langsmith` package is installed. When off, every helper here is a plain pass-through.
What is sent is a shrunk view of each input and output (long strings, long lists and the robot's MJCF are
cut), not the full run files.
"""
from __future__ import annotations

import functools
import inspect
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_client = None
_state = {"checked": False, "on": False, "url": None}
_events = {"path": None, "t0": 0.0, "frames": None, "n_frames": 0}


def start_events(out_dir, frames: bool = False) -> None:
    """Begin a run's live event log, <out_dir>/events.jsonl (one JSON object per line, appended as the run
    goes; web/ reads it). With `frames`, robot renders go to <out_dir>/frames/."""
    import time

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _events.update(path=out / "events.jsonl", t0=time.perf_counter(), frames=(out / "frames") if frames else None, n_frames=0)
    _events["path"].write_text("")
    if frames:
        (out / "frames").mkdir(exist_ok=True)
        for old in (out / "frames").glob("*.png"):
            old.unlink()


def emit(kind: str, **data) -> None:
    """Append one event. A no-op until start_events is called."""
    if _events["path"] is None:
        return
    import json
    import time

    line = json.dumps({"t": round(time.perf_counter() - _events["t0"], 3), "kind": kind, **data}, default=str)
    with open(_events["path"], "a") as f:
        f.write(line + "\n")


def frame_path(label: str):
    """Where the next render goes, or None when frames are off. Returns (absolute path, name relative to the run)."""
    if _events["frames"] is None:
        return None
    _events["n_frames"] += 1
    name = f"{_events['n_frames']:03d}-{''.join(ch if ch.isalnum() else '-' for ch in label)[:40]}.png"
    return _events["frames"] / name, f"frames/{name}"


def load_env(path: Path | None = None) -> None:
    """Read KEY=VALUE lines from .env into the environment, without overriding what is already set."""
    path = path or REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def enabled() -> bool:
    global _client
    if not _state["checked"]:
        _state["checked"] = True
        load_env()
        want = os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes") and os.environ.get("LANGSMITH_API_KEY")
        if want:
            try:
                import langsmith

                _client = langsmith.Client()
                _state["on"] = True
            except Exception as e:  # not installed, or a bad setting: run without tracing
                print(f"tracing off: {type(e).__name__}: {e}")
    return _state["on"]


def shrink(obj, depth: int = 0):
    """A small, JSON-safe view of `obj` for the trace."""
    if isinstance(obj, str):
        return obj if len(obj) <= 300 else f"<{len(obj)} characters: {obj[:80]}...>"
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        if depth >= 3:
            return f"<dict: {', '.join(list(map(str, obj))[:8])}>"
        return {str(k): shrink(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, (list, tuple)):
        if len(obj) > 8 and not all(isinstance(x, (int, float)) for x in obj):
            return [shrink(x, depth + 1) for x in obj[:3]] + [f"<{len(obj) - 3} more>"]
        return [shrink(x, depth + 1) for x in obj[:16]]
    return str(obj)[:200]


def span(name: str, run_type: str = "chain", outputs=None):
    """Decorator: trace calls to the function as a LangSmith run named `name`. `outputs(result)` gives what
    to record (default: a shrunk view of the result)."""
    def wrap(fn):
        traced_fn = None

        @functools.wraps(fn)
        def call(*args, **kwargs):
            nonlocal traced_fn
            if not enabled():
                return fn(*args, **kwargs)
            if traced_fn is None:
                from langsmith import traceable

                traced_fn = traceable(
                    name=name, run_type=run_type, client=_client,
                    process_inputs=lambda d: {k: shrink(v) for k, v in d.items()},
                    process_outputs=lambda r: _as_dict(outputs(r) if outputs else shrink(r)),
                )(fn)
            return traced_fn(*args, **kwargs)

        call.__signature__ = inspect.signature(fn)
        return call
    return wrap


def _as_dict(v):
    return v if isinstance(v, dict) else {"output": v}


def node(name: str, step):
    """Trace one pipeline step: inputs are the state's keys, outputs are the keys the step added or changed.
    Also writes step_start and step_end events."""
    import time

    def describe(result, before):
        changed = {k: v for k, v in result.items() if k not in before or before[k] is not v}
        return {"wrote": sorted(changed), **{k: shrink(v, 1) for k, v in changed.items()}}

    def run(state: dict) -> dict:
        before = dict(state)

        @span(name, "chain", outputs=lambda r: describe(r, before))
        def inner(state_keys: list):
            return step(state)

        emit("step_start", step=name)
        t0 = time.perf_counter()
        try:
            out = inner(sorted(state))
        except Exception as e:
            emit("step_end", step=name, seconds=round(time.perf_counter() - t0, 2), error=f"{type(e).__name__}: {e}")
            raise
        emit("step_end", step=name, seconds=round(time.perf_counter() - t0, 2),
             wrote=sorted(k for k in out if k not in before or before[k] is not out[k]))
        return out

    return run


def note_url() -> None:
    """Call inside the root run: remember its URL so the runner can print it."""
    try:
        from langsmith.run_helpers import get_current_run_tree

        rt = get_current_run_tree()
        _state["url"] = rt.get_url() if rt else None
    except Exception:
        _state["url"] = None


def finish() -> str | None:
    """Send anything still queued; returns the root run's URL when there is one."""
    if _state["on"] and _client is not None:
        try:
            _client.flush()
        except Exception as e:
            print(f"tracing: could not flush: {type(e).__name__}: {e}")
    return _state["url"]
