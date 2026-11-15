"""world: the only door into this module. For now a scenario is a hand-written world.json in world/scenarios/;
the loader from a Matterport scan is not built."""
from __future__ import annotations

import json
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


def scenarios() -> list:
    """Names load() accepts."""
    return sorted(p.stem for p in SCENARIOS.glob("*.json") if not p.name.endswith(".tasks.json"))


def load(scenario: str) -> dict:
    """The world.json dict for a named scenario."""
    path = SCENARIOS / f"{scenario}.json"
    if not path.exists():
        raise ValueError(f"no scenario {scenario!r}; have {scenarios()}")
    return json.loads(path.read_text())
