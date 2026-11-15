"""Recorded demonstrations, one folder per skill. A skill is complete once it has every recording.

    <root>/<skill>/demo.json   hand path from the Meta Quest headset    (capture.api.latest("demo"))
    <root>/<skill>/grip.json   grip band from the pressure-sensor gloves (capture.api.latest("grip"))
"""

import json
import re
from pathlib import Path

RECORDINGS = ("demo", "grip")
DEFAULT_ROOT = Path(__file__).resolve().parent / "skill_data"


def slug(name: str) -> str:
    """A skill name that is safe as a folder name: lowercase letters, digits and underscores."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not cleaned:
        raise ValueError(f"Not a usable skill name: {name!r}")
    return cleaned[:64]


def chore_name(skill: str) -> str:
    """How a skill is named to the headset and capture: "take_out_garbage" -> "take out garbage".

    The headset stamps this on the recording, and capture.api.latest(kind, chore=...) finds it by it.
    """
    return slug(skill).replace("_", " ")


class SkillStore:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = Path(root)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.exists() else []

    def missing(self, skill: str) -> list[str]:
        """The recordings this skill still needs; empty when it is complete."""
        folder = self.root / slug(skill)
        return [r for r in RECORDINGS if not (folder / f"{r}.json").exists()]

    def load(self, skill: str) -> dict:
        folder = self.root / slug(skill)
        return {r: json.loads((folder / f"{r}.json").read_text()) for r in RECORDINGS if (folder / f"{r}.json").exists()}

    def save(self, skill: str, recordings: dict) -> None:
        """Store the given recordings, keeping any this skill already has."""
        unknown = set(recordings) - set(RECORDINGS)
        if unknown:
            raise ValueError(f"Unknown recordings {sorted(unknown)}; expected {list(RECORDINGS)}.")
        folder = self.root / slug(skill)
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in recordings.items():
            (folder / f"{name}.json").write_text(json.dumps(data, indent=1))
