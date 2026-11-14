#!/usr/bin/env python3
"""Probe what the hackathon keys return, for the questions the plan depends on.

Usage:  python3 docs/probe/sponsor_probe.py [N_MODELS]
Keys:   MATTERPORT_API_KEY, MATTERPORT_API_TOKEN, VEXCEL_API_KEY in the
        environment or in a git-ignored .env at the repo root.
Needs:  models_index.csv next to this script or in the current directory
        (download it from the hackathon quickstart page).
Writes: docs/probe/out/probe.json and one Vexcel image. Standard library only.
"""
import base64, csv, json, os, random, sys, time, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
GRAPH = "https://api.matterport.com/api/models/graph"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def graph(query, variables=None):
    auth = base64.b64encode(
        f"{os.environ['MATTERPORT_API_KEY']}:{os.environ['MATTERPORT_API_TOKEN']}".encode()
    ).decode()
    req = urllib.request.Request(
        GRAPH,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"errors": [{"message": f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"}]}


ROOMS = """query($id: ID!) { model(id: $id) {
  floors { id label edges { id type thickness openings { id type label %s height lowerElevation relativeCenter } } }
  rooms { id classifications { label } dimensions(units: metric) { areaFloor width depth height } }
  bundle(id: "mp:matterpak") { availability }
} }"""
OBJECTS = """query($id: ID!) { model(id: $id) {
  objectAnnotations { label confidence classification { label } room { id } }
} }"""


def probe_model(sid):
    out = {"sid": sid}
    r = graph(ROOMS % "width", {"id": sid})
    if r.get("errors"):  # the opening width field name is a guess from the schema page
        out["rooms_error_with_width"] = r["errors"][0]["message"][:200]
        r = graph(ROOMS % "", {"id": sid})
    if r.get("errors"):
        out["rooms_error"] = r["errors"][0]["message"][:200]
    m = (r.get("data") or {}).get("model") or {}
    rooms = m.get("rooms") or []
    dims = [x.get("dimensions") or {} for x in rooms]
    labels = [(x.get("classifications") or [{}])[0].get("label") for x in rooms]
    heights = [d["height"] for d in dims if d.get("height")]
    hall = [min(d["width"], d["depth"]) for d, l in zip(dims, labels)
            if l == "Hallway" and d.get("width") and d.get("depth")]
    openings = [o for f in m.get("floors") or [] for e in f.get("edges") or [] for o in e.get("openings") or []]
    doors = [o.get("width") for o in openings if o.get("type") == "doorway" and o.get("width")]
    out.update(
        rooms=len(rooms),
        rooms_with_height=len(heights),
        ceiling_min=min(heights, default=None),
        ceiling_max=max(heights, default=None),
        hallway_narrowest=min(hall, default=None),
        openings=len(openings),
        doorways_with_width=len(doors),
        doorway_narrowest=min(doors, default=None),
        opening_sample=openings[:2],
        matterpak=(m.get("bundle") or {}).get("availability"),
    )
    r = graph(OBJECTS, {"id": sid})
    if r.get("errors"):
        out["objects_error"] = r["errors"][0]["message"][:200]
    else:
        objs = ((r.get("data") or {}).get("model") or {}).get("objectAnnotations") or []
        out["objects"] = len(objs)
        out["object_labels"] = sorted({o.get("label") or (o.get("classification") or {}).get("label") for o in objs} - {None})[:40]
    return out


def vexcel(lat, lon):
    d = 0.0006
    wkt = (f"POLYGON(({lon-d} {lat-d},{lon+d} {lat-d},{lon+d} {lat+d},"
           f"{lon-d} {lat+d},{lon-d} {lat-d}))")
    body = {"wkt": wkt, "srid": 4326, "layer": "urban,urban-r,wide-area,urban-g",
            "crop": "bounding_box", "image-format": "jpeg",
            "destination-dimensions": "1000,1000", "attribution": "false"}
    req = urllib.request.Request(
        "https://api.vexcelgroup.com/v2/ortho/extract", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-KEY": os.environ["VEXCEL_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        (OUT / "vexcel_ortho.jpg").write_bytes(data)
        return {"ok": True, "bytes": len(data)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}


def main():
    load_env()
    missing = [k for k in ("MATTERPORT_API_KEY", "MATTERPORT_API_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}. Put them in {ROOT / '.env'} (git-ignored).")
    index = next((p for p in (HERE / "models_index.csv", Path("models_index.csv")) if p.exists()), None)
    if not index:
        sys.exit("models_index.csv not found; download it from the quickstart page.")
    rows = list(csv.DictReader(index.open()))
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    random.seed(0)
    pool = [r for r in rows if r["lat"] and int(r["room_count"] or 0) >= 3]
    picks = random.sample([r for r in pool if r["segment"] == "commercial"], n * 3 // 4) \
        + random.sample([r for r in pool if r["segment"] == "residential"], n - n * 3 // 4)
    OUT.mkdir(exist_ok=True)
    result = {"models": []}
    for r in picks:
        p = probe_model(r["sid"])
        p.update(name=r["name"], segment=r["segment"], floor_count=r["floor_count"])
        result["models"].append(p)
        print(json.dumps({k: p.get(k) for k in ("sid", "rooms", "ceiling_max", "hallway_narrowest",
                                                "openings", "doorway_narrowest", "objects", "matterpak")}))
        time.sleep(0.5)  # everyone shares these keys
    ms = result["models"]
    result["summary"] = {
        "probed": len(ms),
        "with_room_heights": sum(1 for m in ms if m.get("rooms_with_height")),
        "with_openings": sum(1 for m in ms if m.get("openings")),
        "with_doorway_widths": sum(1 for m in ms if m.get("doorways_with_width")),
        "with_objects": sum(1 for m in ms if m.get("objects")),
        "matterpak_unlocked": sum(1 for m in ms if m.get("matterpak") == "unlocked"),
    }
    if os.environ.get("VEXCEL_API_KEY"):
        result["vexcel"] = vexcel(float(picks[0]["lat"]), float(picks[0]["lon"]))
    (OUT / "probe.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result["summary"], indent=1), result.get("vexcel", "vexcel: no key"))


if __name__ == "__main__":
    main()
