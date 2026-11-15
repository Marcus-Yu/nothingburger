"""Fill the reach-envelope cache for every carrier in the catalog, so design runs skip the sampling.

    python -m composer.warm [--workers 8] [--requirements runs/<run>/requirements.json]

The envelope (model.Robot.envelope) is about 80% of the time it takes to check a candidate, and it
depends on the carrier alone (base, lift, arm, gripper, wrist camera), not on the job. Each carrier is
composed with its cheapest sensors, the same candidate a cheapest-first design search composes first.
Already cached carriers are skipped; a changed catalog card or sampler gives new cache keys.
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import model as M
from . import parts as P


def _warm(parts: dict, limits: tuple | None = None) -> tuple:
    t0 = time.perf_counter()
    r = M.robot(parts)
    r.envelope()
    if limits:
        r.stow(*limits)
    return P.carrier_key(parts), round(time.perf_counter() - t0, 1)


def carriers() -> list[dict]:
    first: dict = {}
    for c in sorted(P.candidates(), key=lambda c: (P.price(c), P.part_mass(c))):
        first.setdefault(P.carrier_key(c), c)
    return list(first.values())


def missing(cands: list[dict]) -> list[dict]:
    return [c for c in cands if not M._envelope_file(P.carrier_key(c), 0, 4000).exists()]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m composer.warm", description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--requirements", help="a run's requirements.json: also fold every carrier for that building's "
                                           "doorway width and header (the same for every job in that building)")
    a = ap.parse_args(argv)
    limits = None
    if a.requirements:
        import json
        from pathlib import Path

        from . import checks as C
        L = C.Ledger(json.loads(Path(a.requirements).read_text()))
        limits = (L.number("base_width_max", None, min)[0] or 0.0, L.number("stowed_height_max", None, min)[0] or 0.0)
    todo = carriers() if limits else missing(carriers())
    print(f"{len(todo)} carriers to sample ({a.workers} workers)", flush=True)
    t0, done = time.perf_counter(), 0
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for fut in as_completed([pool.submit(_warm, c, limits) for c in todo]):
            done += 1
            if done % 25 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} in {round(time.perf_counter() - t0)} s", flush=True)
    print(f"cache: {M.ENVELOPE_CACHE}")


if __name__ == "__main__":
    main()
