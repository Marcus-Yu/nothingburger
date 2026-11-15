"""composer.design's steering limits: `require` and `max_price_usd`, with the checks stood in for (fast).

    PYTHONPATH=. uv run --with pytest python -m pytest -q composer/tests/test_steer.py
"""
import jsonschema
import pytest

from composer import checks as C
from composer import design as D
from composer import parts as P
from composer.tests.test_composer import schema


def _fake_check(feasible):
    """A stand-in for the composed check: `feasible(parts) -> bool`, the price and mass from the cards."""
    def check(parts, requirements):
        parts = P.full(parts)
        ok = feasible(parts)
        return {"parts": parts, "price_usd": P.price(parts), "mass_kg": 1.0, "feasible": ok, "labels": [],
                "checks": [{"check": "reach", "task": "t1", "status": "pass" if ok else "fail", "requirements": ["R1"],
                            "value": 1, "limit": 2, "unit": "m"}]}
    return check


@pytest.fixture
def stand_in(monkeypatch):
    """Card arithmetic passes everything; the check passes what `state["feasible"]` says (default: everything)."""
    state = {"feasible": lambda p: True}
    monkeypatch.setattr(C, "Ledger", lambda requirements: None)
    monkeypatch.setattr(C, "cheap_failures", lambda c, L: [])
    monkeypatch.setattr(D, "_check", lambda parts, req: _fake_check(state["feasible"])(parts, req))
    return state


def cheapest(**match):
    cands = [c for c in P.candidates() if all(P.full(c)[k] == v for k, v in match.items())]
    return min(P.price(c) for c in cands)


def test_unsteered_is_the_cheapest(stand_in):
    a = D.design({})
    b = D.design({}, require=None, max_price_usd=None)
    assert a == b
    assert a["price_usd"] == cheapest()
    assert a["considered"] == len(P.candidates())


def test_require_keeps_only_matching_parts(stand_in):
    d = D.design({}, require={"arm": "xarm7", "lidar": "vlp16"})
    assert d["parts"]["arm"] == "xarm7" and d["parts"]["lidar"] == "vlp16"
    assert d["price_usd"] == cheapest(arm="xarm7", lidar="vlp16")


def test_require_wrist_cam_as_text(stand_in):
    assert D.design({}, require={"wrist_cam": "true"})["parts"]["wrist_cam"] is True
    assert D.design({}, require={"wrist_cam": False})["parts"]["wrist_cam"] is False


def test_max_price_drops_dearer_candidates(stand_in):
    stand_in["feasible"] = lambda p: p["arm"] == "ur10e"  # only a dear arm works
    limit = cheapest(arm="ur10e")
    d = D.design({}, max_price_usd=limit)
    assert d["parts"]["arm"] == "ur10e" and d["price_usd"] <= limit
    assert d["considered"] == sum(1 for c in P.candidates() if P.price(c) <= limit)


def test_max_price_below_everything_is_infeasible_naming_the_limit(stand_in):
    d = D.design({}, max_price_usd=10)
    assert d["parts"] is None
    binding = d["infeasible"]["binding_checks"]
    assert binding[0]["check"] == "price limit" and binding[0]["limit"] == 10 and binding[0]["status"] == "fail"
    assert "$10" in binding[0]["why"]
    assert d["infeasible"]["closest_parts"] is None
    jsonschema.validate(d, schema("design"))


def test_limit_that_rules_out_the_only_working_part_is_named(stand_in):
    stand_in["feasible"] = lambda p: p["arm"] == "ur10e"
    d = D.design({}, require={"arm": "piper"}, max_price_usd=cheapest(arm="piper") + 5000)
    assert d["parts"] is None
    checks = [c["check"] for c in d["infeasible"]["binding_checks"]]
    assert checks[:2] == ["required parts", "price limit"] and "reach" in checks
    assert d["infeasible"]["closest_parts"]["arm"] == "piper"
    jsonschema.validate(d, schema("design"))


def test_cache_key_ignores_the_limits():
    """The disk cache is keyed on parts and requirements only; the limits never reach _check."""
    import inspect

    assert list(inspect.signature(D._check_file).parameters) == ["parts", "requirements"]
