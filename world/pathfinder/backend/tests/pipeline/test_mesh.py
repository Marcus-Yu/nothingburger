import numpy as np
import pytest
import trimesh
from PIL import Image

pytest.importorskip(
    "pymeshlab"
)  # pipeline.mesh needs the `pipeline` extra (uv sync --extra pipeline)

from pipeline.mesh import (
    _merge_atlases,
    _tight_crop_scene_textures,
    build_collision_mesh,
    decimate_textured,
)


def _textured_box(extents=(4.0, 3.0, 2.0), subdivide=2) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=extents)
    for _ in range(subdivide):
        box = box.subdivide()
    image = Image.new("RGB", (8, 8), (180, 90, 40))
    uv = np.random.default_rng(0).random((len(box.vertices), 2))
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=image, baseColorFactor=[1, 1, 1, 1]
    )
    box.visual = trimesh.visual.TextureVisuals(uv=uv, image=image, material=material)
    return box


# --- synthetic tower/ground/floater scene, for crop_to_subject_auto -------------------------
# A tower (subject) sitting on a much wider ground plane, plus a small floater (e.g. a sky blob)
# disconnected from both -- the exact "tower + wide ground + floater" corpus the crop is meant to
# handle, with cameras that orbit or fly by while keeping the tower centred (the pilot's real
# behaviour either way).

_TOWER_LOOK_AT = np.array([0.0, 10.0, 0.0])


# --- camera_target ------------------------------------------------------------------


# --- crop_to_subject ------------------------------------------------------------------


# --- _drop_small_components -------------------------------------------------------------


# --- view_centrality_scores / crop_to_subject_auto ---------------------------------------


# --- scale_from_known_height -----------------------------------------------------------


# --- _tight_crop_scene_textures ----------------------------------------------------------


def test_tight_crop_scene_textures_shrinks_sparse_atlas_and_keeps_colours():
    # the real patches only occupy the top-left quarter of the canvas (a texturer packs charts from
    # the top, UVs are OpenGL-style so that quarter is u<0.5, v>0.5); the rest is fill colour.
    image = np.full((100, 100, 3), (255, 128, 0), dtype=np.uint8)
    image[:25, :25] = (200, 0, 0)
    image[25:50, :50] = (0, 200, 0)
    image[:25, 25:50] = (0, 0, 200)
    uv = np.array([[0.05, 0.95], [0.45, 0.95], [0.45, 0.55], [0.05, 0.55], [0.3, 0.9]])
    patch = trimesh.Trimesh(
        vertices=np.random.default_rng(0).random((5, 3)),
        faces=[[0, 1, 2], [0, 2, 3], [0, 4, 1]],
        visual=trimesh.visual.TextureVisuals(
            uv=uv,
            material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(image)),
        ),
        process=False,
    )
    before = patch.visual.to_color().vertex_colors[:, :3].copy()
    scene = trimesh.Scene({"patch": patch})

    _tight_crop_scene_textures(scene)

    cropped = scene.geometry["patch"]
    assert cropped.visual.material.baseColorTexture.size[0] <= 50
    assert cropped.visual.material.baseColorTexture.size[1] <= 50
    assert cropped.visual.to_color().vertex_colors[:, :3].tolist() == before.tolist()
    assert (255, 128, 0) not in {tuple(c) for c in before.tolist()}  # never samples the fill


def test_tight_crop_scene_textures_is_noop_when_uv_already_fills_canvas():
    mesh = _textured_box(subdivide=1)
    mesh.visual.uv[:] = np.clip(mesh.visual.uv, 0.0, 1.0)
    mesh.visual.uv[0] = [0.0, 0.0]
    mesh.visual.uv[1] = [1.0, 1.0]
    original_size = mesh.visual.material.baseColorTexture.size
    scene = trimesh.Scene({"box": mesh})

    _tight_crop_scene_textures(scene)

    assert scene.geometry["box"].visual.material.baseColorTexture.size == original_size


def test_merge_atlases_keeps_every_face_on_its_own_texels():
    # the kitchen-clip shape trimesh 5.1's packer got wrong: a full atlas plus a shorter one
    rng = np.random.default_rng(1)
    scene = trimesh.Scene()
    for name, (w, h) in {"a": (64, 64), "b": (60, 34)}.items():
        img = Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
        px = rng.integers(0, (w, h), (30, 2)) + 0.5  # texel centres: exact samples
        uv = np.c_[px[:, 0] / w, 1.0 - px[:, 1] / h]
        scene.add_geometry(
            trimesh.Trimesh(
                rng.random((30, 3)),
                rng.integers(0, 30, (20, 3)),
                process=False,
                visual=trimesh.visual.TextureVisuals(
                    uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=img)
                ),
            ),
            geom_name=name,
        )
    before = np.vstack(
        [g.visual.to_color().vertex_colors[:, :3] for g in scene.geometry.values()]
    ).astype(int)

    merged = _merge_atlases(scene)

    assert merged.visual.uv.min() >= 0.0 and merged.visual.uv.max() <= 1.0
    after = merged.visual.to_color().vertex_colors[:, :3].astype(int)
    assert np.abs(after - before).max() <= 2  # random texels: a misplaced uv is off by ~100


# --- decimate_textured ------------------------------------------------------------------


def test_decimate_textured_reduces_faces_and_keeps_uv_and_texture():
    mesh = _textured_box(subdivide=3)
    target = len(mesh.faces) // 4

    decimated = decimate_textured(mesh, target_triangles=target)

    assert (
        len(decimated.faces) <= target * 1.5
    )  # quadric collapse lands close to, not exact, target
    assert len(decimated.faces) < len(mesh.faces)
    assert decimated.visual.uv is not None
    assert len(decimated.visual.uv) == len(decimated.vertices)
    assert decimated.visual.material.baseColorTexture is not None


def test_decimate_textured_is_noop_under_budget():
    mesh = _textured_box(subdivide=1)
    decimated = decimate_textured(mesh, target_triangles=len(mesh.faces) * 10)
    assert len(decimated.faces) == len(mesh.faces)


# --- build_collision_mesh ----------------------------------------------------------------


def test_build_collision_mesh_is_untextured_and_reduced():
    mesh = _textured_box(subdivide=3)
    target = len(mesh.faces) // 4

    collision = build_collision_mesh(mesh, target_triangles=target)

    assert len(collision.faces) <= target * 1.5
    assert (
        not hasattr(collision.visual, "material")
        or getattr(collision.visual, "material", None) is None
        or getattr(collision.visual.material, "baseColorTexture", None) is None
    )


