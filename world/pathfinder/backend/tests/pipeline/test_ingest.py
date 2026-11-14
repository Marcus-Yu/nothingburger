import json

import numpy as np
import pytest
import trimesh
from PIL import Image

pytest.importorskip("pymeshlab")

from pipeline import cli, ingest


def _textured(mesh: trimesh.Trimesh, colour) -> trimesh.Trimesh:
    image = Image.new("RGB", (8, 8), colour)
    uv = np.random.default_rng(0).random((len(mesh.vertices), 2))
    material = trimesh.visual.material.PBRMaterial(baseColorTexture=image)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, image=image, material=material)
    return mesh


def _room_z_up(offset=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    """A 6 x 4 x 2.6 m room seen from inside (normals point in), Z up, like a MatterPak OBJ."""
    room = trimesh.creation.box(extents=(6.0, 4.0, 2.6))
    room.invert()
    room.apply_translation(np.array(offset) + [0, 0, 1.3])
    return _textured(room, (200, 190, 170))


def _block_z_up() -> trimesh.Scene:
    """Two 10 x 10 x 8 m buildings 40 m apart on a 100 m ground patch at UTM-sized coordinates,
    as an aerial tile gives them: outside faces only, no undersides."""
    origin = np.array([741_200.0, 3_741_900.0, 310.0])
    ground = trimesh.Trimesh(
        [[-50, -50, 0], [50, -50, 0], [50, 50, 0], [-50, 50, 0]], [[0, 1, 2], [0, 2, 3]]
    )
    pieces = [_textured(ground, (90, 110, 80))]
    for x in (-20.0, 20.0):
        box = trimesh.creation.box(extents=(10.0, 10.0, 8.0))
        box.update_faces(box.face_normals[:, 2] > -0.5)  # no bottom
        box.apply_translation([x, 0, 4.0])
        pieces.append(_textured(box, (150, 80, 60)))
    for p in pieces:
        p.apply_translation(origin)
    return trimesh.Scene(pieces)


def test_guess_up_reads_floors_and_ground():
    assert ingest.guess_up(trimesh.Scene([_room_z_up()])) == "z"
    y_up = _room_z_up()
    y_up.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    assert ingest.guess_up(trimesh.Scene([y_up])) == "y"


def test_to_package_frame_is_metric_y_up_and_keeps_handedness():
    v, origin = ingest.to_package_frame(
        np.array([[100.0, 200.0, 50.0], [110.0, 220.0, 53.0]]), "z", 0.3048
    )
    assert origin == [105.0, 210.0, 50.0]
    np.testing.assert_allclose(v[:, 1], [0.0, 3 * 0.3048])  # height is Y, lowest point at 0
    np.testing.assert_allclose(v[:, 0], [-5 * 0.3048, 5 * 0.3048])
    np.testing.assert_allclose(v[:, 2], [10 * 0.3048, -10 * 0.3048])  # z = -northing
    # east x north = up before and after: still a right-handed frame
    east, north, upv = np.eye(3)
    f = lambda p: ingest.to_package_frame(np.array([[0, 0, 0.0], p]), "z", 1.0)[0]
    e, n, u = (f(p)[1] - f(p)[0] for p in (east, north, upv))
    np.testing.assert_allclose(np.cross(e, n), u, atol=1e-12)


def test_room_obj_imports_with_a_spawn_inside(tmp_path):
    src = tmp_path / "src" / "room.obj"
    src.parent.mkdir()
    _room_z_up(offset=(12.0, -7.0, 3.0)).export(src)

    report = ingest.import_mesh(
        src, "flat", tmp_path / "scene", tmp_path / "work", source="matterport"
    )

    assert report["problems"] == []
    assert report["up"] == "z" and report["interior"] is True
    assert report["size_m"] == {"x": 6.0, "y": 2.6, "z": 4.0}
    pos = np.array(report["spawn"]["pos"])
    assert abs(pos[0]) < 3.0 and abs(pos[2]) < 2.0  # inside the walls
    assert pos[1] == pytest.approx(1.6, abs=0.1)  # eyes above the floor at y = 0
    scene = json.loads((tmp_path / "scene" / "scene.json").read_text())
    assert scene["revision"] == 1 and scene["scale_method"] == "survey"
    assert scene["structure"] is None
    assert json.loads((tmp_path / "scene" / scene["cameras"]).read_text()) == []
    mesh = trimesh.load(tmp_path / "scene" / scene["mesh"]["file"], force="mesh")
    np.testing.assert_allclose(mesh.bounds, [[-3, 0, -2], [3, 2.6, 2]], atol=1e-6)


def test_aerial_tile_crops_to_one_building_and_spawns_outside(tmp_path):
    src = tmp_path / "tile.glb"
    _block_z_up().export(src)
    e, n = 741_200.0, 3_741_900.0

    report = ingest.import_mesh(
        src,
        "east-building",
        tmp_path / "scene",
        tmp_path / "work",
        source="vexcel",
        up="z",  # a GLB that kept its map axes
        bbox=(e + 8, n - 12, e + 32, n + 12),
    )

    assert report["problems"] == []
    assert report["interior"] is False
    assert report["size_m"]["y"] == pytest.approx(8.0)
    # the other building is gone (and the 100 m ground triangles, whose centroids are outside)
    assert report["size_m"]["x"] == pytest.approx(10.0) and report["size_m"]["z"] == pytest.approx(
        10.0
    )
    assert report["origin_source_units"] == pytest.approx([e + 20, n, 310.0])
    pos = np.array(report["spawn"]["pos"])
    assert max(abs(pos[0]), abs(pos[2])) > 5.0  # outside the building's walls
    scene = json.loads((tmp_path / "scene" / "scene.json").read_text())
    assert "vexcel" in scene["scale_notes"]


def test_reimport_publishes_the_next_revision_in_the_same_frame(tmp_path):
    src = tmp_path / "room.glb"
    _room_z_up().export(src)
    args = (src, "flat", tmp_path / "scene", tmp_path / "work")
    first = ingest.import_mesh(*args, up="z")
    second = ingest.import_mesh(*args, up="z", unit="ft")
    assert (first["revision"], second["revision"]) == (1, 2)
    assert second["size_m"]["y"] == pytest.approx(2.6 * 0.3048, abs=0.01)
    scene = json.loads((tmp_path / "scene" / "scene.json").read_text())
    assert scene["mesh"]["file"] == "mesh.r2.glb"
    assert scene["frame"]["id"].startswith("flat-")


def test_empty_bbox_and_point_clouds_are_refused(tmp_path):
    src = tmp_path / "room.glb"
    _room_z_up().export(src)
    with pytest.raises(ValueError, match="nothing inside"):
        ingest.import_mesh(src, "x", tmp_path / "s", tmp_path / "w", up="z", bbox=(90, 90, 99, 99))
    cloud = tmp_path / "cloud.ply"
    trimesh.PointCloud(np.random.default_rng(0).random((50, 3))).export(cloud)
    with pytest.raises(ValueError, match="no triangles"):
        ingest.import_mesh(cloud, "x", tmp_path / "s2", tmp_path / "w2")


def test_cli_import(tmp_path, capsys):
    src = tmp_path / "room.glb"
    _room_z_up().export(src)
    cli.main(["import", str(src), "--site", "flat", "--out", str(tmp_path / "scene"),
              "--work", str(tmp_path / "work"), "--up", "z", "--source", "matterport"])  # fmt: skip
    report = json.loads(capsys.readouterr().out)
    assert report["site"] == "flat" and report["problems"] == []


def test_obj_with_one_texture_per_material_becomes_one_jpeg_atlas(tmp_path):
    """A MatterPak is one OBJ whose MTL names dozens of JPEGs. Two here: floor and ceiling."""
    Image.new("RGB", (64, 64), (200, 40, 40)).save(tmp_path / "a.jpg")
    Image.new("RGB", (32, 32), (40, 40, 200)).save(tmp_path / "b.jpg")
    (tmp_path / "pak.mtl").write_text(
        "newmtl a\nKd 1 1 1\nmap_Kd a.jpg\nnewmtl b\nKd 1 1 1\nmap_Kd b.jpg\n"
    )
    (tmp_path / "pak.obj").write_text(
        "mtllib pak.mtl\n"
        "v 0 0 0\nv 4 0 0\nv 4 3 0\nv 0 3 0\nv 0 0 2.5\nv 4 0 2.5\nv 4 3 2.5\nv 0 3 2.5\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl a\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
        "usemtl b\nf 5/1 7/3 6/2\nf 5/1 8/4 7/3\n"
    )
    report = ingest.import_mesh(tmp_path / "pak.obj", "pak", tmp_path / "scene", tmp_path / "work")

    assert report["problems"] == []
    assert report["input"]["pieces"] == 2 and report["up"] == "z"
    assert report["texture_px"] == 128  # two 64 px cells side by side
    mesh = trimesh.load(tmp_path / "scene" / "mesh.r1.glb", force="mesh")
    # each face still samples its own picture: the floor (y = 0) red, the ceiling blue
    atlas = np.asarray(mesh.visual.material.baseColorTexture.convert("RGB")).astype(int)
    uv = mesh.visual.uv[mesh.faces].mean(axis=1)
    px = (uv[:, 0] * atlas.shape[1]).astype(int)
    py = ((1 - uv[:, 1]) * atlas.shape[0]).astype(int)
    colours = atlas[py, px]
    floor = mesh.triangles_center[:, 1] < 0.1
    assert floor.sum() == 2 and (~floor).sum() == 2
    assert (colours[floor, 0] > colours[floor, 2] + 100).all()
    assert (colours[~floor, 2] > colours[~floor, 0] + 100).all()
