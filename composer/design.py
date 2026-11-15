"""design: enumerate, check, rank. Parts come in fixed sizes, so sizing is choosing the size."""
from __future__ import annotations

import os

from . import checks as C
from . import parts as P

MAX_BINDING_SEARCH = 40


def default_workers() -> int:
    """Processes that compose and check candidates at once: COMPOSER_WORKERS, else 1 (in process).

    With the reach and stow caches warm (python -m composer.warm), a check is mostly composing the
    MuJoCo model, and extra processes cost more in start-up than they save, so the default is 1."""
    env = os.environ.get("COMPOSER_WORKERS")
    return max(1, int(env)) if env else 1


# A check result is a pure function of the parts, the requirements and this package's code, so it is
# kept on disk too: the same job checked again (a rehearsed demo) skips composing. COMPOSER_CHECK_CACHE=0 turns it off.
_CODE_HASH = None


def _check_file(parts: dict, requirements: dict):
    import hashlib
    import json
    from pathlib import Path

    global _CODE_HASH
    if _CODE_HASH is None:
        h = hashlib.sha256()
        for f in sorted(Path(__file__).parent.glob("*.py")):
            h.update(f.read_bytes())
        _CODE_HASH = h.hexdigest()
    # a task's `why` is the model's own wording, different on every run; no check reads it
    req = {**requirements, "tasks": [{k: v for k, v in t.items() if k != "why"} for t in requirements.get("tasks", [])]}
    key = json.dumps([_CODE_HASH, P.full(parts), req], sort_keys=True, default=str).encode()
    return P.CATALOG_DIR / "_cache" / "checks" / f"{hashlib.sha256(key).hexdigest()[:32]}.json"


def _check(parts: dict, requirements: dict) -> dict:
    import json

    if os.environ.get("COMPOSER_CHECK_CACHE") == "0":
        return C.check(parts, requirements)
    f = _check_file(parts, requirements)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    r = C.check(parts, requirements)
    try:
        text = json.dumps(r)
    except (TypeError, ValueError):
        return r
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text)
        os.replace(tmp, f)
    except OSError:
        pass
    return json.loads(text)  # the same form a cached result comes back in, so cold and warm runs write the same files


def _checked_in_order(survivors, requirements, no_reach, workers: int | None = None):
    """Yield (candidate, check result) in the survivors' order, skipping a candidate whose carrier is in
    `no_reach` at the moment its turn comes, exactly as a one-at-a-time loop would.

    With more than one worker, the next few candidates are checked in other processes ahead of time;
    results are still handed out strictly in order, so the caller sees the same sequence, counts and
    winner as the sequential loop. Checks are pure functions of the parts and requirements."""
    n = workers or default_workers()
    if n <= 1 or len(survivors) < 2:
        for c in survivors:
            if P.carrier_key(c) in no_reach:
                continue  # reach depends on the carrier alone, so a different lidar or ego camera cannot fix it
            yield c, _check(c, requirements)
        return
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=n) as pool:
        pending = {}  # index -> future, for candidates checked ahead of their turn
        try:
            for i, c in enumerate(survivors):
                # keep the pool busy with upcoming candidates: one per carrier at a time, never one whose
                # carrier already failed reach (its result would be thrown away)
                flying = {P.carrier_key(survivors[j]) for j in pending}
                j = i
                while len(pending) < 2 * n and j < min(len(survivors), i + 300):
                    k = P.carrier_key(survivors[j])
                    if j not in pending and k not in no_reach and k not in flying:
                        pending[j] = pool.submit(_check, survivors[j], requirements)
                        flying.add(k)
                    j += 1
                fut = pending.pop(i, None)
                if P.carrier_key(c) in no_reach:
                    if fut:
                        fut.cancel()
                    continue
                r = fut.result() if fut else _check(c, requirements)
                yield c, r
        finally:
            for fut in pending.values():
                fut.cancel()


def _same(have, want) -> bool:
    """A pattern value against a candidate's part: wrist_cam is a bool, and a pattern may say "true"/"yes"."""
    if isinstance(have, bool) and not isinstance(want, bool):
        return have == (str(want).strip().lower() in ("true", "yes", "1", "on"))
    return have == want


def _matches(parts: dict, pat: dict) -> bool:
    return all(_same(parts.get(k), v) for k, v in pat.items())


def _steer_checks(left_out_price, left_out_require, n_total, require, max_price_usd) -> list:
    """Binding entries, shaped like checks, for the limits the person set when they leave the search empty-handed."""
    out = []
    if require and left_out_require:
        said = ", ".join(f"{k} {v}" for k, v in require.items())
        out.append({"check": "required parts", "task": None, "status": "fail", "value": None, "limit": said, "unit": None,
                    "requirements": [], "why": f"You required {said}; {left_out_require} of {n_total} candidates without "
                                               f"{'it' if len(require) == 1 else 'them'} were left out."})
    if max_price_usd is not None and left_out_price:
        cheapest = min(left_out_price)
        out.append({"check": "price limit", "task": None, "status": "fail", "value": cheapest, "limit": max_price_usd, "unit": "USD",
                    "requirements": [], "why": f"You capped the price at ${max_price_usd:,.0f}; {len(left_out_price)} of {n_total} "
                                               f"candidates cost more (the cheapest of them ${cheapest:,.0f}) and were left out."})
    return out


def design(requirements: dict, exhaustive: bool = False, on_candidate=None, exclude=None, require=None,
           max_price_usd=None) -> dict:
    """The cheapest candidate that passes every check (price, then mass), as a design.json dict.

    Candidates are first tested with the card arithmetic alone; only those with no failure there are
    composed, cheapest first, and the search stops at the first that passes. Price and mass are exact
    before composing, so that one is the cheapest. A candidate whose carrier already failed reach with other
    sensors is skipped without composing. With `exhaustive`, every survivor is composed and the
    design also carries `feasible`, the number that pass. `on_candidate`, when given, is called with a
    progress dict: once with {"stage": "arithmetic", ...counts} and then {"stage": "checked", ...check result}
    for every candidate composed. `exclude` is a list of part patterns, e.g. [{"lift": "none", "arm": "xarm7"}]:
    a candidate matching every key of any pattern is left out (constraints added by the pathing loop).
    `require` ({slot: part id}) keeps only candidates with every one of those parts, and `max_price_usd` drops
    candidates that cost more: limits the person set. Both apply before anything is composed; when they leave
    nothing that passes, the infeasible form's binding checks name them."""
    L = C.Ledger(requirements)
    cands = [c for c in P.candidates() if not any(_matches(P.full(c), pat) for pat in (exclude or []))]
    n_total, left_out_require, left_out_price = len(cands), 0, []
    if require:
        kept = [c for c in cands if _matches(P.full(c), require)]
        left_out_require, cands = len(cands) - len(kept), kept
    if max_price_usd is not None:
        kept = [c for c in cands if P.price(c) <= max_price_usd]
        left_out_price, cands = [P.price(c) for c in cands if P.price(c) > max_price_usd], kept
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
    for c, r in _checked_in_order(survivors, requirements, no_reach, workers=1 if exhaustive else None):
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
        r = _check(c, requirements)
        n_checked += 1
        if closest is None or len(fails(r)) < len(fails(closest)):
            closest = r
    counts["composed_and_checked"] = n_checked
    steer = _steer_checks(left_out_price, left_out_require, n_total, require, max_price_usd)
    return {"schema": "design/1", "parts": None, "price_usd": None, "mass_kg": None, "checks": [], "labels": [],
            "infeasible": {"binding_checks": steer + (fails(closest) if closest else []),
                           "closest_parts": closest["parts"] if closest else None,
                           "closest_price_usd": closest["price_usd"] if closest else None,
                           **({"steer": {"require": require or None, "max_price_usd": max_price_usd}} if steer else {})},
            **counts}
