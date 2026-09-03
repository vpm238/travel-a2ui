"""Command line for the A2UI skill generator.

    python -m skillgen build --catalog catalogs/a2ui-travel/catalog.json \\
        --examples catalogs/a2ui-travel/examples --out skills

    python -m skillgen build --all           # every format x shape variant
    python -m skillgen build --all --check   # fail if the checked-in skills are stale
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
import tempfile
from typing import Sequence

from .generator import FORMATS, SHAPES, GenerationRequest, generate

DEFAULT_VARIANTS: list[tuple[str, str]] = [
    ("express", "monolithic"),
    ("express", "modular"),
    ("direct_json", "monolithic"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillgen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Generate SKILL.md files from a catalog.")
    build.add_argument("--catalog", type=pathlib.Path, required=True, help="Catalog JSON path.")
    build.add_argument("--examples", type=pathlib.Path, help="Directory of *.express examples.")
    build.add_argument("--out", type=pathlib.Path, required=True, help="Output directory.")
    build.add_argument(
        "--catalog-name",
        default=None,
        help="Catalog name used in metadata and in the catalog skill's name. "
        "Defaults to the catalog directory's name.",
    )
    build.add_argument("--protocol-version", default="0.9.1")
    build.add_argument(
        "--format", dest="inference_format", choices=sorted(FORMATS), default="express"
    )
    build.add_argument("--shape", choices=SHAPES, default="monolithic")
    build.add_argument(
        "--all",
        action="store_true",
        help="Generate every variant: " + ", ".join(f"{f}/{s}" for f, s in DEFAULT_VARIANTS) + ".",
    )
    build.add_argument("--no-examples", action="store_true", help="Omit the examples section.")
    build.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any generated skill differs from disk.",
    )
    return parser


def _requests(args: argparse.Namespace) -> list[GenerationRequest]:
    catalog_name = args.catalog_name or args.catalog.parent.name
    variants = DEFAULT_VARIANTS if args.all else [(args.inference_format, args.shape)]
    return [
        GenerationRequest(
            catalog_path=args.catalog,
            examples_dir=args.examples,
            out_dir=args.out,
            catalog_name=catalog_name,
            protocol_version=args.protocol_version,
            inference_format=inference_format,
            shape=shape,
            include_examples=not args.no_examples,
        )
        for inference_format, shape in variants
    ]


def _check(requests: list[GenerationRequest]) -> int:
    """Renders into a scratch directory and diffs against what is checked in."""
    stale: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for request in requests:
            probe = dataclasses.replace(request, out_dir=pathlib.Path(tmp))
            for skill, path in generate(probe):
                target = request.out_dir / request.variant / skill.name / "SKILL.md"
                rendered = path.read_text(encoding="utf-8")
                if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                    stale.append(f"{request.variant}/{skill.name}")

    if stale:
        print("Stale skills: " + ", ".join(stale), file=sys.stderr)
        print("Regenerate them with: python -m skillgen build --all …", file=sys.stderr)
        return 1

    print("All generated skills are up to date.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requests = _requests(args)

    if args.check:
        return _check(requests)

    written: list[pathlib.Path] = []
    for request in requests:
        for _skill, path in generate(request):
            written.append(path)
            print(f"wrote {path}")

    print(f"\n{len(written)} skill file(s) written to {args.out}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
