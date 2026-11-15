"""Traced wrapper around stream C's capture.api (AGENTS.md rule 2: other streams only through agent/tools/)."""

from langsmith import traceable


class CaptureUnavailable(RuntimeError):
    """capture/ (stream C's PR #2) is not in this checkout."""


@traceable(run_type="tool", name="capture.latest")
def latest(kind: str, chore: str) -> dict | None:
    """The newest demo.json ("demo") or grip.json ("grip") recorded for this chore, or None."""
    try:
        from capture import api
    except ImportError as e:  # also a bare capture/ folder, which imports as an empty namespace package
        raise CaptureUnavailable(
            "capture/ is not in this checkout yet (stream C's PR #2). Pass the recordings in the reply instead."
        ) from e
    return api.latest(kind, chore=chore)
