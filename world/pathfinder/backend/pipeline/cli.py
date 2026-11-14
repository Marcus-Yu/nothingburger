"""CLI: build a scene package from data that already exists. `matterport` (a model id, through the
Matterport Model API), `vexcel` (a latitude and longitude, through the Vexcel API) and `import` (a
finished mesh on disk, such as an unzipped MatterPak)."""

import argparse
import json
import logging
from pathlib import Path


def _cmd_import(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from pipeline import ingest  # lazy: needs the `pipeline` extra (pymeshlab)

    report = ingest.import_mesh(
        args.mesh,
        args.site,
        args.out,
        args.work if args.work is not None else Path("work") / args.site,
        source=args.source,
        up=args.up,
        unit=args.unit,
        scale=args.scale,
        bbox=tuple(args.bbox) if args.bbox else None,
        spawn=args.spawn,
        target_triangles=args.target_triangles,
        collision_triangles=args.collision_triangles,
        max_texture_size=args.max_texture_size,
    )
    print(json.dumps(report, indent=2))


def _cmd_matterport(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from pipeline import ingest, matterport  # lazy: needs the `pipeline` extra (pymeshlab)

    work = args.work if args.work is not None else Path("work") / args.site
    extra, views = {}, None
    try:
        obj, _ = matterport.fetch_mesh(args.model, work / "matterpak")
    except matterport.MatterportError as exc:  # no MatterPak: texture the bare mesh ourselves
        logging.getLogger("pipeline").info("%s -- baking the API mesh from its panoramas", exc)
        import trimesh

        from pipeline import panobake

        bare = trimesh.load(
            matterport.fetch_bare_mesh(args.model, work / "mesh"), force="mesh", process=False
        )
        panos, defurnished = matterport.fetch_panos(
            args.model, work / "panos", defurnished=args.panos == "defurnished"
        )
        extra["headings"] = panobake.solve_headings(bare, panos)
        baked, extra["bake"] = panobake.bake(bare, panos, atlas_size=args.max_texture_size)
        extra["panos"] = {"count": len(panos), "defurnished": defurnished}
        obj = work / "baked.glb"
        baked.export(obj)
        views = [
            ingest.SourceView(
                p.faces[k], p.position, *(p.to_mesh @ panobake.FACES[k, i] for i in (1, 2, 0))
            )
            for p in panos
            for k in (1, 2, 3, 4)
        ]
    model = matterport.graph(matterport.Q_MODEL, id=args.model)["model"]
    report = ingest.import_mesh(
        obj,
        args.site,
        args.out,
        work,
        source=f"matterport {args.model}",
        up="z",
        views=views,
        target_triangles=args.target_triangles,
        collision_triangles=args.collision_triangles,
        max_texture_size=args.max_texture_size,
    )
    report.update(extra)
    report["model"] = {k: model.get(k) for k in ("id", "name", "address", "geolocation")}
    print(json.dumps(report, indent=2))


def _cmd_vexcel(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from pipeline import ingest, vexcel  # lazy: needs the `pipeline` extra (pymeshlab)

    work = args.work if args.work is not None else Path("work") / args.site
    glb, built = vexcel.build(
        args.lat, args.lon, work, half_m=args.half_m, default_height_m=args.default_height_m
    )
    report = ingest.import_mesh(
        glb,
        args.site,
        args.out,
        work,
        source=f"vexcel {built['collection']}",
        up="z",
        spawn="outside",
        max_texture_size=args.max_texture_size,
    )
    report["vexcel"] = built
    print(json.dumps(report, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser(
        "import",
        help="a finished textured mesh (Matterport MatterPak OBJ, Vexcel or other aerial mesh "
        "tile, any OBJ/GLB/PLY) -> scene package, no reconstruction",
    )
    p_import.add_argument("mesh", type=Path, help="OBJ (with its MTL and textures), GLB/glTF, PLY")
    p_import.add_argument("--site", required=True)
    p_import.add_argument("--out", type=Path, required=True, help="scene package output dir")
    p_import.add_argument("--work", type=Path, default=None, help="work dir (default work/<site>)")
    p_import.add_argument(
        "--source", default="mesh", help="where it came from, for scene.json: matterport, vexcel"
    )
    p_import.add_argument(
        "--up",
        choices=["auto", "y", "z"],
        default="auto",
        help="the file's up axis. Matterport and georeferenced tiles are z; glTF is y; auto "
        "guesses from which way the flat area faces",
    )
    p_import.add_argument(
        "--unit", choices=["m", "cm", "mm", "ft", "usft", "in"], default="m", help="source units"
    )
    p_import.add_argument("--scale", type=float, default=1.0, help="extra factor on --unit")
    p_import.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_A", "MIN_B", "MAX_A", "MAX_B"),
        help="crop to this box over the file's two horizontal axes, in its own units (easting "
        "and northing for a georeferenced tile): one building out of a city tile",
    )
    p_import.add_argument(
        "--spawn",
        choices=["auto", "inside", "outside"],
        default="auto",
        help="start inside on the biggest floor (room scans) or outside facing the scan "
        "(aerial); auto decides by whether the mesh has ceilings",
    )
    p_import.add_argument("--target-triangles", type=int, default=200_000, dest="target_triangles")
    p_import.add_argument(
        "--collision-triangles", type=int, default=50_000, dest="collision_triangles"
    )
    p_import.add_argument("--max-texture-size", type=int, default=4096, dest="max_texture_size")
    p_import.set_defaults(func=_cmd_import)

    p_mp = sub.add_parser(
        "matterport",
        help="a Matterport model id -> scene package: downloads its MatterPak mesh through the "
        "Model API (MATTERPORT_API_KEY / MATTERPORT_API_TOKEN) and imports it",
    )
    p_mp.add_argument("model", help="Matterport model id (sid), e.g. zvKHR9DHNjJ")
    p_mp.add_argument("--site", required=True)
    p_mp.add_argument("--out", type=Path, required=True, help="scene package output dir")
    p_mp.add_argument("--work", type=Path, default=None, help="work dir (default work/<site>)")
    p_mp.add_argument(
        "--panos",
        choices=["defurnished", "scanned"],
        default="defurnished",
        help="which panoramas texture the API mesh when there is no MatterPak: the defurnished "
        "view (matches the defurnished mesh) or the rooms as scanned",
    )
    p_mp.add_argument("--target-triangles", type=int, default=200_000, dest="target_triangles")
    p_mp.add_argument("--collision-triangles", type=int, default=50_000, dest="collision_triangles")
    p_mp.add_argument("--max-texture-size", type=int, default=4096, dest="max_texture_size")
    p_mp.set_defaults(func=_cmd_matterport)

    p_vx = sub.add_parser(
        "vexcel",
        help="a latitude and longitude -> exterior scene package from the Vexcel API "
        "(VEXCEL_API_KEY): the ortho photo on the ground, footprints extruded into blocks",
    )
    p_vx.add_argument("--lat", type=float, required=True)
    p_vx.add_argument("--lon", type=float, required=True)
    p_vx.add_argument("--site", required=True)
    p_vx.add_argument("--out", type=Path, required=True, help="scene package output dir")
    p_vx.add_argument("--work", type=Path, default=None, help="work dir (default work/<site>)")
    p_vx.add_argument(
        "--half-m", type=float, default=35.0, dest="half_m", help="centre to edge of the square"
    )
    p_vx.add_argument(
        "--default-height-m",
        type=float,
        default=3.5,
        dest="default_height_m",
        help="block height where the API has no believable roof height",
    )
    p_vx.add_argument("--max-texture-size", type=int, default=4096, dest="max_texture_size")
    p_vx.set_defaults(func=_cmd_vexcel)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
