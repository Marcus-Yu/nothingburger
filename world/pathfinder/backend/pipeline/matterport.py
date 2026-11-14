"""Fetch a Matterport model's geometry through the Model API (GraphQL at api.matterport.com,
HTTP basic auth: `MATTERPORT_API_KEY` is the user, `MATTERPORT_API_TOKEN` the password).

A model's MatterPak is one zip: a textured OBJ mesh (metres, Z up), its MTL and JPEGs, a coloured
point cloud and floor-plan renders. The point cloud is most of the zip (hundreds of MB) and
`pipeline.ingest` only needs the mesh, so the zip is opened in place over HTTP range requests and
only the OBJ, MTL and textures are downloaded.
"""

import io
import json
import logging
import os
import zipfile
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger(__name__)

API = "https://api.matterport.com/api/models/graph"
_MESH_SUFFIXES = (".obj", ".mtl", ".jpg", ".jpeg", ".png")

Q_MODEL = """query Model($id: ID!) { model(id: $id) {
  id name
  address { address }
  geolocation { lat long }
  bundle(id: "mp:matterpak") { availability assets { status filename url } }
  assets { resources(format: "matterpak") { status filename url } }
  panoLocations { id label position { x y z } }
  rooms { id classifications { label } dimensions(units: metric) { areaFloor width depth height } }
} }"""


class MatterportError(RuntimeError):
    pass


def secret(name: str) -> str:
    """A key from the environment, else from `.env` in the working directory. Never logged."""
    value = os.environ.get(name)
    if not value and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            key, _, val = line.partition("=")
            if key.strip() == name:
                value = val.strip().strip('"').strip("'")
    if not value:
        raise MatterportError(f"{name} is not set (environment or .env)")
    return value


def graph(query: str, **variables) -> dict:
    """Run a Model API query and return its `data`."""
    auth = (secret("MATTERPORT_API_KEY"), secret("MATTERPORT_API_TOKEN"))
    r = httpx.post(API, json={"query": query, "variables": variables}, auth=auth, timeout=120)
    if r.status_code in (401, 403):
        raise MatterportError(f"Matterport rejected the key (HTTP {r.status_code})")
    r.raise_for_status()
    body = r.json()
    for error in body.get("errors") or []:
        raise MatterportError(f"{variables}: {error.get('message')}")
    return body["data"]


class HttpFile(io.RawIOBase):
    """A read-only, seekable file over HTTP range requests, so `zipfile` can list a remote zip
    and read single members without downloading the rest."""

    def __init__(self, url: str, block: int = 4 * 2**20):
        self.url, self.pos, self.block = url, 0, block
        self.client = httpx.Client(timeout=300, follow_redirects=True)
        head = self.client.get(url, headers={"Range": "bytes=0-0"})
        head.raise_for_status()
        self.size = int(head.headers["Content-Range"].split("/")[1])
        self.buf, self.buf_at, self.fetched = b"", -1, 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        out = b""
        while n > 0 and self.pos < self.size:
            if not (self.buf_at <= self.pos < self.buf_at + len(self.buf)):
                end = min(self.size, self.pos + max(self.block, n)) - 1
                r = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
                r.raise_for_status()
                self.buf, self.buf_at = r.content, self.pos
                self.fetched += len(self.buf)
            start = self.pos - self.buf_at
            chunk = self.buf[start : start + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return out

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def fetch_mesh(sid: str, dest: Path) -> tuple[Path, dict]:
    """Download model `sid`'s MatterPak mesh (OBJ, MTL, textures; not the point cloud) into
    `dest`. Returns the OBJ path and the model's record (address, lat/lon, pano positions and
    rooms, also saved as `dest/model.json`). Files already there are kept."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    model = graph(Q_MODEL, id=sid)["model"]
    # the zip is listed twice: under the bundle (where the hackathon keys get a link) and under
    # assets.resources (where the quickstart looks, and these keys get "unavailable")
    resources = (model["bundle"].pop("assets", None) or []) + model.pop("assets")["resources"]
    pak = next((x for x in resources if x.get("url")), None)
    if pak is None:
        raise MatterportError(
            f"the MatterPak of {sid} is {model['bundle']['availability']}: not unlocked for this "
            "key (the models with a splat are)"
        )
    (dest / "model.json").write_text(json.dumps(model, indent=2))

    remote = HttpFile(pak["url"])
    with zipfile.ZipFile(remote) as archive:
        wanted = [
            i
            for i in archive.infolist()
            if i.filename.lower().endswith(_MESH_SUFFIXES) and "colorplan" not in i.filename
        ]
        for info in wanted:
            name = Path(info.filename).name  # flat, and never outside dest
            target = dest / name
            if not (target.exists() and target.stat().st_size == info.file_size):
                target.write_bytes(archive.read(info))
    objs = sorted(dest.glob("*.obj"))
    if not objs:
        raise MatterportError(f"{pak['filename']} has no OBJ")
    logger.info(
        "%s: %d files, %.0f of %.0f MB downloaded",
        pak["filename"],
        len(wanted),
        remote.fetched / 1e6,
        remote.size / 1e6,
    )
    return objs[0], model


Q_VIEW = """query View($id: ID!) { model(id: $id) {
  assets { meshes { filename format status url } }
  view(type: "matterport.model.defurnished") { id }
} }"""

Q_PANOS = """query Panos($id: ID!, $res: String!) { model(id: $id) {
  panoLocations { id label position { x y z } rotation { x y z w }
                  skybox(resolution: $res) { status children } }
} }"""


def _download(job: tuple[str, Path]) -> None:
    url, target = job
    if not (target.exists() and target.stat().st_size > 0):
        r = httpx.get(url, timeout=300, follow_redirects=True)
        r.raise_for_status()
        target.write_bytes(r.content)


def fetch_bare_mesh(sid: str, dest: Path) -> Path:
    """Download the model's untextured OBJ (the defurnished shell where there is one, else the
    first mesh on offer) into `dest`. This is what the API serves when the MatterPak is not."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    meshes = [
        x
        for x in graph(Q_VIEW, id=sid)["model"]["assets"]["meshes"]
        if x.get("url") and x["format"] == "obj" and "planes" not in x["filename"]
    ]
    if not meshes:
        raise MatterportError(f"{sid} has no downloadable mesh")
    pick = next((x for x in meshes if "defurnished" in x["filename"]), meshes[0])
    target = dest / pick["filename"]
    _download((pick["url"], target))
    return target


def fetch_panos(sid: str, dest: Path, *, defurnished: bool = True, resolution: str = "2k"):
    """Download every panorama of `sid` (six skybox faces each) into `dest`. Returns them as
    `panobake.Pano`s, and whether they came from the model's defurnished view (which matches the
    defurnished mesh) or are the rooms as scanned."""
    from concurrent.futures import ThreadPoolExecutor

    from pipeline.panobake import Pano

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    view = graph(Q_VIEW, id=sid)["model"].get("view") if defurnished else None
    locations = graph(Q_PANOS, id=(view or {}).get("id") or sid, res=resolution)["model"]
    panos, jobs = [], []
    for loc in locations["panoLocations"]:
        box = loc.get("skybox") or {}
        urls = box.get("children") or []
        if box.get("status") != "available" or len(urls) != 6:
            continue
        label = "".join(c for c in str(loc["label"]) if c.isalnum()) or loc["id"]
        files = [dest / f"p{label.zfill(3)}_{k}.jpg" for k in range(6)]
        jobs += list(zip(urls, files))
        pos, rot = loc["position"], loc["rotation"]
        panos.append(
            Pano(
                id=loc["id"],
                label=label,
                position=np.array([pos["x"], pos["y"], pos["z"]], dtype=np.float64),
                quat=np.array([rot["x"], rot["y"], rot["z"], rot["w"]], dtype=np.float64),
                faces=files,
            )
        )
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(_download, jobs))
    logger.info("%d panoramas (%d images) in %s", len(panos), len(jobs), dest)
    return panos, bool(view)
