"""world.api, traced: the one way the agent gets a world for a Matterport model."""
from __future__ import annotations

import world.api as _api

from .trace import traced


@traced("world.for_model", lambda w: f"{w['id']}: {len(w['rooms'])} rooms, {len(w['doorways'])} doorways, "
                                     f"{len(w['obstacles'])} obstacles, {len(w['anchors'])} anchors")
def for_model(model_id: str, name: str) -> dict:
    return _api.for_model(model_id, name)
