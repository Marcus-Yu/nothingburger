"""Stream C's entry point for demonstrations: `latest(kind)`.

Raw recordings arrive from the Quest app as JSON files in the inbox (the Pathfinder backend's
`POST /demos` writes them there). `latest("demo")` and `latest("grip")` process the newest one
that has what that kind needs and return the dict that goes into a run folder as `demo.json` or
`grip.json`. Recorded demos stay on disk, so the pipeline never needs the headset live.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from capture import process

_REPO = Path(__file__).resolve().parent.parent
KINDS = ("demo", "grip")


def inbox() -> Path:
    """Where raw recordings land: `CAPTURE_INBOX`, else the Pathfinder backend's data folder."""
    return Path(os.environ.get("CAPTURE_INBOX") or _REPO / "world" / "pathfinder" / "backend" / "data" / "demos")


def recordings(folder: Path | None = None) -> list[Path]:
    """Recording files, newest first."""
    folder = Path(folder) if folder else inbox()
    return sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []


def build(recording: dict, kind: str) -> dict:
    if kind == "demo":
        return process.build_demo(recording)
    if kind == "grip":
        return process.build_grip(recording)
    raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")


def latest(kind: str, folder: Path | None = None, chore: str | None = None) -> dict | None:
    """The newest `demo.json` or `grip.json` (a dict), or None when no recording can give one.
    `chore` narrows it to recordings of that chore. A "squeeze" recording is preferred for the
    grip and skipped for the demo; a "path" recording still gives a grip band when the person
    held something in it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    fallback = None
    for path in recordings(folder):
        try:
            recording = json.loads(path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            continue
        if chore and recording.get("chore") != chore:
            continue
        is_squeeze = recording.get("kind") == "squeeze"
        if kind == "demo" and is_squeeze:
            continue
        try:
            built = build(recording, kind)
        except ValueError:
            continue
        if kind == "grip" and not is_squeeze:
            fallback = fallback or built
            continue
        return built
    return fallback


def ingest(recording: dict, run_dir: Path) -> dict:
    """Write what this recording gives (`demo.json`, `grip.json`) into `run_dir`. Returns
    `{kind: path}` for the files written."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for kind in KINDS:
        if kind == "demo" and recording.get("kind") == "squeeze":
            continue
        try:
            doc = build(recording, kind)
        except ValueError:
            continue
        path = run_dir / f"{kind}.json"
        path.write_text(json.dumps(doc, indent=1), encoding="utf8")
        written[kind] = str(path)
    return written


if __name__ == "__main__":  # python -m capture.api <recording.json> <run dir>
    import sys

    print(json.dumps(ingest(json.loads(Path(sys.argv[1]).read_text(encoding="utf8")), Path(sys.argv[2])), indent=1))
