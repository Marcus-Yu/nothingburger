"""Fixtures: two robots baked by fixtures/make_fixtures.py, and a hand-made build dict for each."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
ARM = [f"arm/joint{i}" for i in range(1, 8)]
ARM_STOWED = dict(zip(ARM, [0.0, -0.247, 0.0, 0.909, 0.0, 1.15644, 0.0]))  # the xarm7 model's home pose
SPOT_STANCE = {f"base/{leg}_{j}": v for leg in ("fl", "fr", "hl", "hr") for j, v in (("hx", 0.0), ("hy", 1.04), ("kn", -1.8))}

WHEELED_BUILD = {
    "schema": "build/1",
    "base": {"kind": "wheeled", "support": [[-0.154, -0.134], [0.154, -0.134], [0.154, 0.134], [-0.154, 0.134]]},
    "stowed": {"qpos": {"lift": 0.0, **ARM_STOWED}},
    "joints": [{"name": "lift", "type": "slide", "range": [0.0, 0.5]}],
    "arm_joints": ["lift", *ARM],
    "tool_site": "tool",
}
SPOT_BUILD = {
    "schema": "build/1",
    "base": {"kind": "legged", "support": [[-0.329, -0.166], [0.266, -0.166], [0.266, 0.166], [-0.329, 0.166]]},
    "stowed": {"qpos": {**SPOT_STANCE, **ARM_STOWED}},
    "joints": [],
    "arm_joints": list(ARM),
    "tool_site": "tool",
}


@pytest.fixture(scope="session")
def wheeled_xml():
    return (FIX / "wheeled.xml").read_text()


@pytest.fixture(scope="session")
def spot_xml():
    return (FIX / "spot.xml").read_text()


@pytest.fixture
def wheeled_build():
    return copy.deepcopy(WHEELED_BUILD)


@pytest.fixture
def spot_build():
    return copy.deepcopy(SPOT_BUILD)


@pytest.fixture(scope="session")
def trajectory_schema():
    return json.loads((CONTRACTS / "trajectory.schema.json").read_text())


def target(point, axis):
    return {"point": list(point), "tool_axis": list(axis), "held_axes": ["position", "tool_axis"]}


def reqs(task_id, targets, **more):
    out = [{"id": "r_reach", "task": task_id, "quantity": "reach_targets", "unit": "pose", "value": targets,
            "tolerance": 0.01, "source": "test"},
           {"id": "r_other", "task": "someone_else", "quantity": "reach_targets", "unit": "pose",
            "value": [target([9, 9, 9], [0, 0, 1])], "tolerance": 0.01, "source": "test"}]
    for quantity, value in more.items():
        out.append({"id": "r_" + quantity, "task": task_id, "quantity": quantity, "value": value, "unit": "",
                    "tolerance": 0.0, "source": "test"})
    return {"schema": "requirements/1", "requirements": out}
