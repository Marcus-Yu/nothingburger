"""The tool-call trace: one entry per call into composer, nav or motion. The runner writes it to trace.json,
and each call is also a LangSmith run when tracing is on (see agent/observe.py)."""
from __future__ import annotations

import functools
import time

from .. import observe

TRACE: list[dict] = []


def reset() -> None:
    TRACE.clear()


def entries() -> list[dict]:
    return list(TRACE)


def traced(name: str, summary):
    """Wrap `fn` so each call appends {"n", "name", "seconds", "summary"}; `summary(result)` is one line.
    An exception is recorded (summary starts with "raised") and re-raised."""
    def wrap(fn):
        @functools.wraps(fn)
        def call(*args, **kwargs):
            t0 = time.perf_counter()
            entry = {"n": len(TRACE), "name": name, "seconds": 0.0, "summary": ""}
            TRACE.append(entry)
            try:
                out = fn(*args, **kwargs)
                entry["summary"] = str(summary(out))
                return out
            except Exception as e:
                entry["summary"] = f"raised {type(e).__name__}: {e}"
                raise
            finally:
                entry["seconds"] = round(time.perf_counter() - t0, 4)
                observe.emit("tool", name=name, seconds=entry["seconds"], summary=entry["summary"])
        return observe.span(name, "tool", outputs=lambda r: {"summary": str(summary(r)), "result": observe.shrink(r)})(call)
    return wrap
