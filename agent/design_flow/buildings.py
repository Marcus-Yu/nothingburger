"""The 3D database: the hackathon's Matterport models, found by name or address, loaded into worlds on demand.

    search("5836 La Mirada")      -> [{"sid", "name", "address", "city", "rooms", "floors", "loaded", "space"}, ...]
    load("169F7nENMza")           -> the scenario name, after world.matterport has written its world.json
    resolve(job, studio_space)    -> which building a job is about (the design workflow's find_building step)

The index is docs/probe/models_index.csv (about 15,000 models in Houston and Los Angeles, from the
sponsor's kit). A building has a world when a file in world/scenarios/ carries its model id in
`tour.matterport`; one without a world is read from the Model API and its MatterPak by world/matterport.py
(about 5 s for a small unit). Rabinowitz Hall is not in the index (our key cannot read it); it stays a
studio space with a hand-traced world.
"""
from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INDEX = REPO / "docs" / "probe" / "models_index.csv"
SCENARIOS = REPO / "world" / "scenarios"
STUDIO_WORLDS = REPO / "web" / "worlds.json"
STOP = {"the", "a", "an", "at", "in", "on", "of", "to", "and", "please", "for", "by", "from", "with", "my", "our",
        "this", "that", "it", "is", "us", "unit", "apt", "room", "rooms", "table", "tables", "kitchen", "wipe",
        "down", "clean", "take", "out", "carry", "pick", "up", "bring", "trash", "bag", "floor", "house", "home",
        "building", "do", "can", "you", "me"}
FIND_MIN = 4.0     # an idf score under this is not taken as the job naming a building
FIND_WORDS = 10.0  # without a matching street or unit number, the words alone must score this much,
RARE_WORD = 6.5    # and include one distinctive word ("mirada", "calais"), not just "main street apartment"
_LOCK = threading.Lock()


def _tokens(text: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOP]


@lru_cache(maxsize=1)
def _index() -> tuple:
    rows = list(csv.DictReader(INDEX.open(encoding="utf8"))) if INDEX.exists() else []
    docs = [set(_tokens(f"{r['name']} {r['address']} {r['city']}")) for r in rows]
    df: dict = {}
    for d in docs:
        for t in d:
            df[t] = df.get(t, 0) + 1
    n = max(len(rows), 1)
    idf = {t: math.log(n / c) for t, c in df.items()}
    return rows, docs, idf


def _worlds() -> dict:
    """model id -> scenario name, for every world file that came from a Matterport model."""
    out = {}
    for f in SCENARIOS.glob("*.json"):
        if f.name.endswith((".tasks.json", ".fit.json")):
            continue
        try:
            tour = json.loads(f.read_text()).get("tour") or {}
        except (OSError, ValueError):
            continue
        if tour.get("matterport"):
            out.setdefault(tour["matterport"], f.stem)
    return out


def _studio_spaces() -> dict:
    """model id -> studio space id, for the spaces web/worlds.json already lists."""
    try:
        return {w["matterport"]: w["id"] for w in json.loads(STUDIO_WORLDS.read_text()) if w.get("matterport")}
    except (OSError, ValueError):
        return {}


def space_id(sid: str) -> str:
    return _studio_spaces().get(sid) or f"mp-{sid}"


def sid_for_space(space: str | None) -> str | None:
    if not space:
        return None
    if space.startswith("mp-"):
        return space[3:]
    return next((sid for sid, sp in _studio_spaces().items() if sp == space), None)


def scenario_for(sid: str) -> str | None:
    return _worlds().get(sid)


def _card(r: dict, worlds: dict) -> dict:
    return {"sid": r["sid"], "name": r["name"], "address": r["address"], "city": r["city"], "state": r["state"],
            "segment": r["segment"], "rooms": int(r["room_count"] or 0), "floors": int(r["floor_count"] or 0),
            "lat": float(r["lat"]) if r["lat"] else None, "lon": float(r["lon"]) if r["lon"] else None,
            "loaded": r["sid"] in worlds, "space": space_id(r["sid"])}


def _scored(query: str) -> list:
    rows, docs, idf = _index()
    q = set(_tokens(query))
    if not q:
        return []
    out = []
    for r, d in zip(rows, docs):
        hit = q & d
        if hit:
            named_by = "number" if any(t.isdigit() for t in hit) else "rare" if any(idf[t] >= RARE_WORD for t in hit) else ""
            out.append((sum(idf[t] * (2.0 if t.isdigit() else 1.0) for t in hit), r, named_by))
    out.sort(key=lambda sr: (-sr[0], -int(sr[1]["room_count"] or 0)))
    return out


def _named(s: float, by: str) -> bool:
    """Whether a match is strong enough to say the job names that building."""
    return s >= FIND_MIN and (by == "number" or (by == "rare" and s >= FIND_WORDS))


def search(query: str, limit: int = 8) -> list:
    worlds = _worlds()
    return [_card(r, worlds) | {"score": round(s, 2)} for s, r, _ in _scored(query)[:limit]]


def get(sid: str) -> dict | None:
    rows, _, _ = _index()
    r = next((x for x in rows if x["sid"] == sid), None)
    return _card(r, _worlds()) if r else None


def _scenario_name(card: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (card["name"] or "model").lower()).strip("_")[:32] or "model"
    return f"{base}_{card['sid'][:4].lower()}"


def load(sid: str, timeout_s: int = 300) -> str:
    """Read the model into world/scenarios/<name>.json (or reuse it); returns the scenario name."""
    with _LOCK:
        have = scenario_for(sid)
        if have:
            return have
        card = get(sid)
        if card is None:
            raise LookupError(f"{sid} is not in the 3D database")
        name = _scenario_name(card)
        done = subprocess.run([sys.executable, "-m", "world.matterport", sid, name], cwd=REPO, capture_output=True,
                              text=True, timeout=timeout_s, env={**__import__("os").environ, "PYTHONPATH": str(REPO)})
        if done.returncode != 0 or not (SCENARIOS / f"{name}.json").exists():
            tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
            raise RuntimeError(f"Could not read {card['name']} from Matterport: {' '.join(tail) or 'no world written'}")
        return name


# --- the design workflow's find_building step ------------------------------------------------------

def _snap_pick(job: str, cands: list) -> str | None:
    """SubQ Snap chooses which candidate the job means, or none; None when Snap is not available."""
    from agent.design_flow.fast import SnapError, snap_decide_choice

    options = {c["sid"]: f"{c['name']}, {c['address'] or c['city']}" for c in cands}
    options["none"] = "The job does not name any of these buildings"
    try:
        pick, conf = snap_decide_choice(job, "Which building does this job take place in?", options)
    except SnapError:
        return None
    return pick if pick != "none" and conf >= 0.6 else ""


def resolve(job: str, studio_space: str | None) -> dict:
    """{"space", "building", "how"} when the building is settled, {"ask", "candidates"} when it is not.

    A building named in the job wins over the studio's space (the person said where); several close matches
    are settled by Snap; with nothing named, the studio's space is used; with no space either, ask."""
    scored = _scored(job)
    strong = [(s, r) for s, r, number in scored if _named(s, number)]
    if strong:
        worlds = _worlds()
        top = [(_card(r, worlds), s) for s, r in strong[:5]]
        close = [c for c, s in top if s >= top[0][1] - 1.0]
        pick = close[0] if len(close) == 1 else None
        how = "named in the job"
        if pick is None:
            chosen = _snap_pick(job, [c for c, _ in top])
            if chosen:
                pick, how = next(c for c, _ in top if c["sid"] == chosen), "named in the job (SubQ Snap chose among close matches)"
            elif chosen is None:
                pick, how = top[0][0], "named in the job (best match)"
        if pick:
            return {"space": pick["space"], "building": pick, "how": how}
        # the job names a building but several fit: ask, even with a space open (the person meant another place)
        return {"ask": "Which of these buildings is it?", "candidates": [c for c, _ in top]}
    if studio_space:
        sid = sid_for_space(studio_space)
        building = (get(sid) if sid else None) or {"name": studio_space, "sid": sid, "loaded": True, "space": studio_space}
        return {"space": studio_space, "building": building, "how": "chosen in the studio"}
    return {"ask": "Which building is this in? Give its address or name.", "candidates": []}
