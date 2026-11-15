"""Checking candidates in parallel finds the same robot, with the same counts, as one at a time."""
import json
from pathlib import Path

from composer import design as D

REQ = Path(__file__).resolve().parents[2] / "runs" / "gallery" / "jrr" / "requirements.json"


def test_parallel_search_matches_the_sequential_one(monkeypatch):
    req = json.loads(REQ.read_text())
    seen = {}
    for workers in ("1", "4"):
        monkeypatch.setenv("COMPOSER_WORKERS", workers)
        order = []
        out = D.design(req, on_candidate=lambda e: e.get("stage") == "checked" and order.append(e["parts"]))
        seen[workers] = (out["parts"], out["price_usd"], out["composed_and_checked"], order)
    assert seen["1"] == seen["4"]
