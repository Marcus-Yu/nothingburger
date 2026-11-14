"""composer: the only door into this module. Every argument and return value is a plain dict or list in
the shape of the matching file in contracts/. Nothing here reads or writes a run folder."""
from __future__ import annotations

from . import build as _build
from . import checks as _checks
from . import design as _design
from . import parts as _parts


def candidates() -> list:
    """Every valid combination of the cards in catalog/, as `parts` dicts (the eight keys of design.json)."""
    return _parts.candidates()


def check(candidate: dict, requirements: dict) -> dict:
    """Judge one candidate against the ledger: {"parts", "feasible", "price_usd", "mass_kg", "checks", "labels"}.
    Each check is pass, fail or not_assessable, with its number, its limit and the requirement ids it read."""
    return _checks.check(candidate.get("parts") or candidate, requirements)


def design(requirements: dict, *, exhaustive: bool = False, on_candidate=None) -> dict:
    """The cheapest feasible candidate as a design.json dict, or the infeasible form with the binding checks.
    `on_candidate(progress: dict)` is called as the search goes, for a caller that wants to show it."""
    return _design.design(requirements, exhaustive=exhaustive, on_candidate=on_candidate)


def compose(design: dict, *, requirements: dict | None = None) -> dict:
    """{"robot_xml": MJCF text with absolute mesh paths, "build": the build.json dict}. The stowed pose is
    folded to the width and height limits `check` used: read from `requirements` when given, otherwise from
    the doorway and door header entries in the design's own `checks`."""
    return _build.compose(design, requirements)
