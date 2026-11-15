"""world: the only door into this module. A scenario is a world.json in world/scenarios/: hand-written, or
read from a Matterport scan by from_matterport (world/matterport.py, `python -m world.matterport <model> <name>`)."""
from __future__ import annotations

import json
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


def scenarios() -> list:
    """Names load() accepts."""
    return sorted(p.stem for p in SCENARIOS.glob("*.json") if not p.name.endswith((".tasks.json", ".fit.json")))


def load(scenario: str) -> dict:
    """The world.json dict for a named scenario."""
    path = SCENARIOS / f"{scenario}.json"
    if not path.exists():
        raise ValueError(f"no scenario {scenario!r}; have {scenarios()}")
    return json.loads(path.read_text())


def from_matterport(model_id: str, name: str, *, with_mesh: bool = True) -> dict:
    """The world.json dict for a Matterport model: rooms and doorways from the Model API's floor plan, and
    with `with_mesh` the furniture and table tops measured on its MatterPak mesh. Needs MATTERPORT_API_KEY
    and MATTERPORT_API_TOKEN (environment or .env); what it downloads is kept in world/_scans/<name>/.
    Nothing is written to world/scenarios/: the command line does that."""
    from world import matterport
    return matterport.load(model_id, name, with_mesh=with_mesh)


def for_model(model_id: str, name: str) -> dict:
    """The world for a Matterport model, read once: world/scenarios/<name>.json when it is there, else built by
    from_matterport and saved there. This is the one call a space needs; the same world file then serves
    planning, the pictures (its `scan`) and Matterport's own viewer (its `tour`). Raises ValueError when the
    model cannot be read or has no floor plan."""
    from world import matterport
    path = SCENARIOS / f"{name}.json"
    if path.exists():
        world = json.loads(path.read_text())
        scan = world.get("scan")
        if scan and not (SCENARIOS.parents[1] / scan["dir"] / "scan.json").exists():
            try:   # a fresh checkout: the world is committed but its real-room files are not. Fetch them again
                matterport.pictures(model_id, name, world)
            except Exception:
                pass   # the pictures fall back to drawn boxes
        return world
    try:
        world = matterport.load(model_id, name)
    except matterport.NoPlan:
        raise
    except Exception as e:   # the key cannot read the model, its MatterPak is locked, the network is down
        raise ValueError(f"Matterport model {model_id} could not be read: {e}") from e
    path.write_text(json.dumps(world, indent=1) + "\n")
    return world
