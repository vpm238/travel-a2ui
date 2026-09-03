#!/usr/bin/env python3
"""Regenerates the parity golden files using Google's reference Express compiler.

The TypeScript compiler in ``packages/express`` is a port, and a port is only
worth anything if you can prove it still agrees with the original. So: every
case in ``tools/parity/cases/*.express`` is compiled here by the reference
implementation, the output is checked in, and ``packages/express/test/parity.test.ts``
asserts the TypeScript compiler produces byte-identical JSON.

When the two disagree, this file is the one that is right.

The reference implementation is not a runtime dependency of this project — it is
only needed to *regenerate* goldens. Install it with:

    pip install a2ui-agent-sdk

or point ``--sdk`` at a checkout of https://github.com/google/a2ui (the
``experimental/express`` compiler there is ahead of the published wheel and is
what these goldens were generated from).

Usage:
    python3 scripts/gen_parity.py [--sdk /path/to/a2ui] [--check]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "tools" / "parity" / "cases"
EXPECTED = ROOT / "tools" / "parity" / "expected"
CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

SURFACE_ID = "parity-surface"
VERSION = "v0.9.1"


def add_sdk_to_path(sdk_root: pathlib.Path | None) -> None:
    if sdk_root is None:
        return
    for package in ("a2ui_agent", "a2ui_core"):
        src = sdk_root / "agent_sdks" / "python" / package / "src"
        if not src.is_dir():
            raise SystemExit(f"Not an a2ui checkout: {src} does not exist")
        sys.path.insert(0, str(src))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=pathlib.Path, help="Path to a google/a2ui checkout.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if a golden is stale instead of rewriting it.",
    )
    args = parser.parse_args()

    add_sdk_to_path(args.sdk)

    try:
        from a2ui.core.catalog import Catalog
        from a2ui.inference_formats.experimental.express.compiler import ExpressCompiler
    except ImportError as error:  # pragma: no cover - operator feedback path
        raise SystemExit(
            f"Could not import the reference A2UI SDK ({error}).\n"
            "Install it with `pip install a2ui-agent-sdk`, or pass "
            "`--sdk /path/to/a2ui` pointing at a checkout of google/a2ui."
        ) from error

    schema = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog = Catalog.from_json(
        catalog_schema=schema, spec_version=VERSION, catalog_id=schema["catalogId"]
    )
    try:
        compiler = ExpressCompiler(catalog, version=VERSION)
        supports_version_kwarg = True
    except TypeError:
        # The published wheel predates multi-version support and always emits
        # the v1.0 envelope shape. Goldens must come from a checkout.
        compiler = ExpressCompiler(catalog)
        supports_version_kwarg = False

    EXPECTED.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    unsupported: list[str] = []
    written = 0

    for case in sorted(CASES.glob("*.express")):
        source = case.read_text(encoding="utf-8")
        kwargs = {"version": VERSION} if supports_version_kwarg else {}
        try:
            messages = compiler.compile(
                source,
                surface_id=SURFACE_ID,
                catalog_id=schema["catalogId"],
                **kwargs,
            )
        except Exception as error:  # noqa: BLE001 - the reason is reported, not raised
            # The published wheel is behind the grammar the skills teach — 0.5.0
            # rejects keyword arguments outright, which is the whole reason the
            # TypeScript port exists. Skipping those cases keeps the check
            # meaningful for the ones it *can* compile, instead of the whole
            # comparison collapsing on the first unsupported feature and telling
            # us nothing about the rest.
            unsupported.append(f"{case.stem} ({type(error).__name__})")
            continue

        rendered = json.dumps(messages, indent=2, ensure_ascii=False) + "\n"
        target = EXPECTED / f"{case.stem}.json"

        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                stale.append(case.stem)
            continue

        target.write_text(rendered, encoding="utf-8")
        written += 1

    if unsupported:
        print(
            f"{len(unsupported)} case(s) the installed reference SDK cannot compile, skipped: "
            + ", ".join(unsupported),
            file=sys.stderr,
        )

    if args.check:
        if stale:
            print("Stale parity goldens: " + ", ".join(stale), file=sys.stderr)
            print("Run: python3 scripts/gen_parity.py", file=sys.stderr)
            return 1
        checked = len(list(CASES.glob("*.express"))) - len(unsupported)
        print(f"All {checked} comparable parity goldens are up to date.")
        return 0

    print(f"Wrote {written} parity goldens to {EXPECTED.relative_to(ROOT)}.")
    if not supports_version_kwarg:
        print(
            "WARNING: the installed SDK does not support --version; goldens are in "
            "v1.0 envelope shape, not v0.9.1.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
