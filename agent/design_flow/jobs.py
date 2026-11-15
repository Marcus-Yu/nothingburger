"""A job in words to the pipeline's task list, by rule: the classified skill on the world's own anchors.

Used when no model reads the job (no ANTHROPIC_API_KEY, or the studio's stand-in mode), and before a
demonstration is asked for, to say early when a job cannot be planned in this space:

    tasks_for("wipe_table", "Wipe a surface", world)   -> ([{"id": "t1", "skill": "wipe", ...}], None)
    tasks_for("change_bulb", "Change a light bulb", w) -> (None, "There is no light fixture in this space's ...")

The pipeline's skills are wipe, pick (with carries/deliver_to), twist_out and twist_in (agent/nodes/intake.py),
and navigate over one of the world's `areas` (mowing: back-and-forth passes from nav.api.cover).
A design-workflow skill maps onto one of them by its name; anything else is not plannable yet.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OBJECT_CARDS = REPO / "catalog" / "object"

# skill-name words -> pipeline skill, verbs before nouns ("pick_up_bottle_on_table" is a pick, not a wipe)
KINDS = [
    (("mow",), "navigate"),  # the verb only: "pick up the toys on the lawn" is a pick
    (("wipe", "clean", "dust", "polish", "scrub"), "wipe"),
    (("carry", "move", "take_out", "garbage", "trash", "bin", "bag", "bottle", "pick", "fetch", "container", "bring"), "pick"),
    (("bulb", "lamp", "light", "unscrew"), "twist_out"),
    (("surface", "table", "counter", "desk"), "wipe"),
]
NOT_YET = "The robot pipeline can wipe, pick up and carry, unscrew bulbs and mow so far; “{job}” isn’t one of those yet."


def needs_demo(skill: str) -> bool:
    """False for a skill the robot does by driving alone (mowing): there is no hand motion or grip to show."""
    return pipeline_skill(skill) != "navigate"


def pipeline_skill(skill: str) -> str | None:
    s = skill.lower()
    for words, kind in KINDS:
        if any(w in s for w in words):
            return kind
    return None


def _object_for(anchor: str) -> str | None:
    """The object card an item anchor holds: bottle_on_table_e2 -> sample_bottle."""
    head = anchor.split("_on_")[0]
    for f in sorted(OBJECT_CARDS.glob("*.json")):
        card = json.loads(f.read_text())
        if head in card["id"] or card["id"] in head:
            return card["id"]
    return None


# words in a job that name a specific object card; a job naming none ("a container", "it") takes any item
NAMED = {"recycling": "recycling_bin", "trash can": "recycling_bin", "trashcan": "recycling_bin", " bin": "recycling_bin",
         "trash": "trash_bag", "garbage": "trash_bag", "bag": "trash_bag", "bottle": "sample_bottle",
         "remote": "tv_remote", "towel": "hand_towel", "pill": "pill_organiser", "drive": "drive_sled", "part": "machined_part", "parcel": "parcel_small"}


def _named(job: str, skill: str) -> str | None:
    text = f"{job} {skill}".lower().replace("_", " ")
    return next((card for word, card in NAMED.items() if re.search(rf"\b{word}s?\b", text)), None)  # whole words: a driveway is not a drive


def _by_words(anchors: list, job: str) -> list:
    """Anchors whose names share a word with the job first ("the table in the kitchen" -> kitchen_top_1)."""
    words = set(re.findall(r"[a-z0-9]+", job.lower())) - {"the", "a", "in", "on", "at", "of", "top", "table", "down"}
    score = lambda a: len(words & set(re.findall(r"[a-z0-9]+", a["id"].lower())))
    return sorted(anchors, key=lambda a: -score(a))


def _wants_all(job: str) -> bool:
    return bool(re.search(r"\b(all|every|both|tables|surfaces|counters|them)\b", job.lower()))


def tasks_for(skill: str, job: str, world: dict) -> tuple[list | None, str | None]:
    """(tasks, None) when the job can be planned on this world, else (None, a reason for the person)."""
    kind = pipeline_skill(skill)
    if kind is None:
        return None, NOT_YET.format(job=job.strip().rstrip(".") or skill.replace("_", " "))
    anchors = world.get("anchors", [])
    place = "this space"
    if kind == "navigate":
        from agent.tools import nav  # nav.api.cover, reached the way every agent step reaches nav

        lawns = [a for a in world.get("areas", []) if a.get("kind") == "lawn"]
        if not lawns:
            return None, f"There’s no lawn marked in {place}’s world file, so mowing can’t be planned here."
        tasks = [t for t in (nav.cover(a, f"t{i + 1}") for i, a in enumerate(lawns if _wants_all(job) else lawns[:1])) if t]
        return (tasks, None) if tasks else (None, f"The lawn in {place}’s world file is too small for a mowing pass.")
    if kind == "wipe":
        surfaces = _by_words([a for a in anchors if a.get("kind") == "surface"], job)
        if not surfaces:
            return None, f"There’s no table or counter in {place}’s world file to wipe."
        chosen = surfaces if _wants_all(job) else surfaces[:1]
        return [{"id": f"t{i + 1}", "skill": "wipe", "anchor": a["id"], "object": "cloth", "carries": False}
                for i, a in enumerate(chosen)], None
    if kind == "twist_out":
        fixtures = [a for a in anchors if a.get("kind") in ("fixture", "ceiling_fixture", "socket")]
        if not fixtures:
            return None, f"There’s no light fixture in {place}’s world file, so a bulb change can’t be planned here."
        return [{"id": "t1", "skill": "twist_out", "anchor": fixtures[0]["id"], "object": "bulb_e26", "carries": False}], None
    items = [(a, _object_for(a["id"])) for a in anchors if a.get("kind") in ("low_item", "counter_item")]
    items = [(a, o) for a, o in items if o]
    items = [(a, o) for a in _by_words([a for a, _ in items], job) for b, o in items if b is a]
    if not items:
        return None, f"There’s nothing in {place}’s world file for the robot to pick up and carry."
    named = _named(job, skill)
    if named:
        matching = [(a, o) for a, o in items if o == named]
        if not matching:
            here = ", ".join(sorted({o.replace("_", " ") for _, o in items}))
            return None, f"There’s no {named.replace('_', ' ')} in {place}’s world file; what’s there to carry: {here}."
        items = matching
    out = (bool(re.search(r"\b(out|outside|away|take out|throw|deliver|to the (front )?(door|kerb|curb|bins?|gate|clubhouse))\b", job.lower()))
           or "take_out" in skill or "garbage" in skill)
    chosen = items if _wants_all(job) else items[:1]
    return [{"id": f"t{i + 1}", "skill": "pick", "anchor": a["id"], "object": o, "carries": out,
             **({"deliver_to": "way_out"} if out else {})} for i, (a, o) in enumerate(chosen)], None
