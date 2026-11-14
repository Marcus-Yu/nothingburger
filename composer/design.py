"""design: enumerate, check, rank. Parts come in fixed sizes, so sizing is choosing the size."""
from __future__ import annotations

from . import checks as C
from . import parts as P

MAX_BINDING_SEARCH = 40


def design(requirements: dict, exhaustive: bool = False, on_candidate=None) -> dict:
    """The cheapest candidate that passes every check (price, then mass), as a design.json dict.

    Candidates are first tested with the card arithmetic alone; only those with no failure there are
    composed, cheapest first, and the search stops at the first that passes. Price and mass are exact
    before composing, so that one is the cheapest. A candidate whose carrier already failed reach with other
    sensors is skipped without composing. With `exhaustive`, every survivor is composed and the
    design also carries `feasible`, the number that pass. `on_candidate`, when given, is called with a
    progress dict: once with {"stage": "arithmetic", ...counts} and then {"stage": "checked", ...check result}
    for every candidate composed."""
    L = C.Ledger(requirements)
    cands = P.candidates()
    cheap = [(c, C.cheap_failures(c, L)) for c in cands]
    survivors = sorted((c for c, f in cheap if not f), key=lambda c: (P.price(c), P.part_mass(c)))
    if on_candidate:
        by = {}
        for _, f in cheap:
            for k in {x["check"] for x in f}:
                by[k] = by.get(k, 0) + 1
        on_candidate({"stage": "arithmetic", "considered": len(cands), "passed": len(survivors),
                      "eliminated_by": dict(sorted(by.items(), key=lambda kv: -kv[1]))})
    best, n_checked, n_feasible, full_fail = None, 0, 0, []
    no_reach = set()  # carriers (base, lift, arm, gripper, wrist camera) already found to fail reach
    for c in survivors:
        if P.carrier_key(c) in no_reach:
            continue  # reach depends on the carrier alone, so a different lidar or ego camera cannot fix it
        r = C.check(c, requirements)
        n_checked += 1
        if on_candidate:
            on_candidate({"stage": "checked", **r})
        if any(k["check"] == "reach" and k["status"] == "fail" for k in r["checks"]):
            no_reach.add(P.carrier_key(c))
        if r["feasible"]:
            n_feasible += 1
            best = best or r
            if not exhaustive:
                break
        else:
            full_fail.append(r)
    counts = {"considered": len(cands), "passed_arithmetic": len(survivors), "composed_and_checked": n_checked}
    if best:
        out = {"schema": "design/1", "parts": best["parts"], "price_usd": best["price_usd"], "mass_kg": best["mass_kg"],
               "checks": best["checks"], "labels": best["labels"], **counts}
        if exhaustive:
            out["feasible"] = n_feasible
        return out

    # nothing passes: the binding checks are the failures of the candidate that failed fewest. Card
    # failures are a lower bound on a candidate's failures, so compose in that order until the bound
    # says no other candidate can do better.
    def fails(r):
        return [k for k in r["checks"] if k["status"] == "fail"]

    closest = min(full_fail, key=lambda r: (len(fails(r)), r["price_usd"]), default=None)
    rest = sorted(((c, f) for c, f in cheap if f), key=lambda cf: (len(cf[1]), P.price(cf[0])))
    for c, f in rest[:MAX_BINDING_SEARCH]:
        if closest is not None and len(f) >= len(fails(closest)):
            break
        r = C.check(c, requirements)
        n_checked += 1
        if closest is None or len(fails(r)) < len(fails(closest)):
            closest = r
    counts["composed_and_checked"] = n_checked
    return {"schema": "design/1", "parts": None, "price_usd": None, "mass_kg": None, "checks": [], "labels": [],
            "infeasible": {"binding_checks": fails(closest), "closest_parts": closest["parts"],
                           "closest_price_usd": closest["price_usd"]},
            **counts}
