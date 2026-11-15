"""Mesh helpers for the scene import (`pipeline.ingest`): decimate a textured mesh to the headset's
triangle budget without losing its UVs, merge and crop texture atlases, re-encode the texture as a
JPEG of at most the budget size, and build the lighter untextured collision mesh in the same frame.
"""

import io
import logging
import tempfile
from pathlib import Path

import fast_simplification
import numpy as np
import pymeshlab
import trimesh
from PIL import Image


logger = logging.getLogger(__name__)


# --- auto-crop ----------------------------------------------------------------------------


# --- view-centrality auto-crop (§ remaining problem 1: works for orbits AND flybys) -----------


# --- known-dimension scale (§6b) -----------------------------------------------------------


# --- decimation (UV-preserving) ------------------------------------------------------------


def decimate_textured(mesh: trimesh.Trimesh, target_triangles: int) -> trimesh.Trimesh:
    """Decimate a textured mesh to `target_triangles`, preserving UVs (research doc §3:
    fast-simplification/Open3D's quadric decimation both silently drop UVs -- pymeshlab's
    texture-aware quadric edge collapse is the one that doesn't). Routed through a temp OBJ+MTL
    round-trip: MeshLab's texture-aware filter requires *wedge* (per-face-corner) UVs associated
    with a texture file, which is what a plain OBJ export/import naturally carries -- simpler and
    more robust than hand-assembling MeshLab's in-memory wedge-texcoord API. No-op under budget."""
    if len(mesh.faces) <= target_triangles:
        return mesh

    with tempfile.TemporaryDirectory(prefix="pathfinder_decimate_") as tmp:
        tmp_dir = Path(tmp)
        in_path = tmp_dir / "in.obj"
        out_path = tmp_dir / "out.obj"
        mesh.export(in_path)

        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(str(in_path))
        ms.meshing_decimation_quadric_edge_collapse_with_texture(
            targetfacenum=target_triangles, extratcoordw=1.0
        )
        ms.save_current_mesh(str(out_path))

        decimated = trimesh.load(out_path, process=False, force="mesh")

    # OBJ/MTL round-trips the texture as a plain file (usually re-encoded to PNG) -- keep geometry
    # + UVs from the round-trip but reattach the *original* texture image so nothing but the
    # decimation itself changes the visible result.
    material = mesh.visual.material
    decimated.visual = trimesh.visual.TextureVisuals(
        uv=decimated.visual.uv, image=material.baseColorTexture, material=material
    )
    return decimated


# --- texture normalisation -------------------------------------------------------------------


def _tight_crop_scene_textures(scene: trimesh.Scene) -> trimesh.Scene:
    """Crop each sub-geometry's texture to the bounding box of UV space it actually uses, in
    place. A textured mesh can split its texture across *multiple* atlas images, each sparsely
    filling its own canvas. `Scene.to_geometry()`'s packer (`trimesh.visual.objects.pack`) lays
    sub-images out side by side without repacking their content, so combining several sparse
    atlases compounds the waste (78% unused black padding in one measured case). Cropping first
    means the packer works with much smaller, denser images."""
    for geom in scene.geometry.values():
        visual = getattr(geom, "visual", None)
        material = getattr(visual, "material", None)
        image = getattr(material, "baseColorTexture", None) if material else None
        uv = getattr(visual, "uv", None)
        if image is None or uv is None or len(uv) == 0:
            continue
        w, h = image.size
        u0, v0 = np.clip(uv.min(axis=0), 0.0, 1.0)
        u1, v1 = np.clip(uv.max(axis=0), 0.0, 1.0)
        # trimesh UVs are OpenGL-style: v=1 is the image's top row, so rows run over 1 - v.
        left, top = int(u0 * w), int((1.0 - v1) * h)
        right = max(left + 1, int(np.ceil(u1 * w)))
        bottom = max(top + 1, int(np.ceil((1.0 - v0) * h)))
        if right - left >= w and bottom - top >= h:
            continue  # already using the whole canvas, nothing to crop
        cropped = image.crop((left, top, right, bottom))
        new_uv = uv.copy()
        new_uv[:, 0] = (uv[:, 0] * w - left) / (right - left)
        new_uv[:, 1] = 1.0 - ((1.0 - uv[:, 1]) * h - top) / (bottom - top)
        geom.visual = trimesh.visual.TextureVisuals(
            uv=new_uv,
            image=cropped,
            material=trimesh.visual.material.PBRMaterial(baseColorTexture=cropped),
        )
    return scene


def _merge_atlases(scene: trimesh.Scene) -> trimesh.Trimesh:
    """One mesh with one texture from a multi-atlas scene: each (already tight-cropped) atlas
    pasted unscaled into its own cell of a near-square grid, UVs remapped. Replaces
    `Scene.to_geometry()`, whose packer (trimesh 5.1) misplaces some atlas combinations: on the
    kitchen clip, a 4093x4091 + 4071x2196 pair left 7k faces with v > 1, which render black
    (bench E1 §7)."""
    geoms = list(scene.geometry.values())
    images = [getattr(getattr(g.visual, "material", None), "baseColorTexture", None) for g in geoms]
    if len(geoms) < 2 or any(im is None for im in images):
        return scene.to_geometry()
    cw, ch = max(im.size[0] for im in images), max(im.size[1] for im in images)
    cols = int(np.ceil(np.sqrt(len(geoms))))
    rows = int(np.ceil(len(geoms) / cols))
    atlas = Image.new("RGB", (cols * cw, rows * ch))
    parts = []
    for k, (g, im) in enumerate(zip(geoms, images)):
        r, c = divmod(k, cols)
        atlas.paste(im.convert("RGB"), (c * cw, r * ch))
        w, h = im.size
        uv = np.asarray(g.visual.uv, dtype=np.float64)
        u = (c * cw + uv[:, 0] * w) / (cols * cw)
        v = 1.0 - (r * ch + (1.0 - uv[:, 1]) * h) / (rows * ch)  # v=1 is the image's top row
        parts.append(
            trimesh.Trimesh(
                g.vertices,
                g.faces,
                process=False,
                visual=trimesh.visual.TextureVisuals(np.c_[u, v]),
            )
        )
    merged = trimesh.util.concatenate(parts)
    material = trimesh.visual.material.PBRMaterial(baseColorTexture=atlas)
    merged.visual = trimesh.visual.TextureVisuals(merged.visual.uv, material=material)
    return merged


def _ensure_jpeg_texture(mesh: trimesh.Trimesh, max_size: int) -> trimesh.Trimesh:
    """Re-encode the mesh's base color texture as JPEG (whatever the source or pymeshlab produced --
    trimesh only embeds-without-re-encoding when the PIL `Image.format` is already `'JPEG'`,
    confirmed in the research pass) and cap it to `max_size`px on the long edge."""
    material = mesh.visual.material
    image = getattr(material, "baseColorTexture", None)
    if image is None:
        return mesh
    image = image.convert("RGB")
    if max(image.size) > max_size:
        image.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    jpeg_image = Image.open(buf)
    jpeg_image.load()  # materialize pixels now -- buf is about to go out of scope

    new_material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=jpeg_image, baseColorFactor=[1.0, 1.0, 1.0, 1.0]
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=mesh.visual.uv, image=jpeg_image, material=new_material
    )
    return mesh


# --- collision mesh -------------------------------------------------------------------------


def build_collision_mesh(mesh: trimesh.Trimesh, target_triangles: int) -> trimesh.Trimesh:
    """Lighter, untextured collision proxy in the same frame as `mesh` (plan: "for tool snapping").
    `fast_simplification` (already a base project dep) is geometry-only/no-UV, which is exactly
    right here since collision.glb is deliberately untextured -- no UV-preservation problem to
    solve, unlike the visible mesh."""
    if len(mesh.faces) <= target_triangles:
        vertices, faces = mesh.vertices, mesh.faces
    else:
        target_reduction = 1.0 - target_triangles / len(mesh.faces)
        vertices, faces = fast_simplification.simplify(
            mesh.vertices, mesh.faces, target_reduction=target_reduction
        )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# --- orchestration ---------------------------------------------------------------------------
