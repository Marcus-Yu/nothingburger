"""Fill catalog/_assets (not committed) with the meshes and simulator models the part cards point to.

    python catalog/fetch_assets.py                 # from the network: needs git, and gmsh for the bases
    python catalog/fetch_assets.py --from-local D  # copy from a folder that already holds
                                                   # D/menagerie/<model>/ and D/parts/base/*_mm.stl

Layout written:
    catalog/_assets/menagerie/<model>/...   MuJoCo Menagerie models (legged bases, arms, grippers, camera)
    catalog/_assets/parts/base/<name>_mm.stl  TidyBot++ bases, binary STL in millimetres

Sources, pinned:
    github.com/google-deepmind/mujoco_menagerie  (sparse clone, only the folders in MODELS)
    github.com/jimmyyhwu/tidybot2-resources      (STEP files; meshed here with gmsh, never committed)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "_assets"

MENAGERIE_URL = "https://github.com/google-deepmind/mujoco_menagerie"
MENAGERIE_SHA = "370c43965323c0944b433b202aac5058b5f907a9"
MODELS = ["unitree_go2", "boston_dynamics_spot", "ufactory_lite6", "ufactory_xarm7", "universal_robots_ur5e",
          "robotiq_2f85", "realsense_d435i"]

TIDYBOT_URL = "https://github.com/jimmyyhwu/tidybot2-resources"
TIDYBOT_SHA = "c268c53c4bc32d3e28d3ad34f35021f1dda316a6"
STEP_FILES = {"arx5_mm.stl": "STEP/Mobile Base - ARX5.step",
              "kinova_mm.stl": "STEP/Mobile Base - Kinova.step",
              "franka_mm.stl": "STEP/Mobile Base - Franka.step"}


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def step_to_stl(step: Path, stl: Path, size_mm: float = 12.0) -> None:
    """Surface-mesh a STEP file and write a binary STL. Coordinates stay in the STEP file's millimetres
    and its own frame; the base cards carry the outline measured from the result and a 0.001 scale."""
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_mm)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_mm / 6)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.model.mesh.generate(2)
        stl.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(stl))
    finally:
        gmsh.finalize()


def fetch_menagerie(dst: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "menagerie"
        _git("clone", "--filter=blob:none", "--no-checkout", MENAGERIE_URL, str(repo))
        _git("sparse-checkout", "set", "--cone", *MODELS, cwd=repo)
        _git("checkout", MENAGERIE_SHA, cwd=repo)
        for name in MODELS:
            _copy(repo / name, dst / name)


def fetch_bases(dst: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "tidybot2-resources"
        _git("clone", "--filter=blob:none", "--no-checkout", TIDYBOT_URL, str(repo))
        _git("sparse-checkout", "set", "--cone", "STEP", cwd=repo)
        _git("checkout", TIDYBOT_SHA, cwd=repo)
        for out, step in STEP_FILES.items():
            print("meshing", step)
            step_to_stl(repo / step, dst / out)


def _copy(src: Path, dst: Path) -> None:
    if not src.exists():
        sys.exit(f"missing {src}")
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print("ok  ", dst.relative_to(HERE))


def from_local(root: Path) -> None:
    for name in MODELS:
        _copy(root / "menagerie" / name, ASSETS / "menagerie" / name)
    for out in STEP_FILES:
        _copy(root / "parts" / "base" / out, ASSETS / "parts" / "base" / out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-local", type=Path, help="copy from a folder holding menagerie/ and parts/base/")
    args = ap.parse_args(argv)
    ASSETS.mkdir(exist_ok=True)
    if args.from_local:
        from_local(args.from_local.resolve())
    else:
        fetch_menagerie(ASSETS / "menagerie")
        fetch_bases(ASSETS / "parts" / "base")
    return 0


if __name__ == "__main__":
    sys.exit(main())
