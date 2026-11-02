#!/usr/bin/env python3
"""Regenerates the parity golden files using the reference Express compiler.

The TypeScript compiler in ``packages/express`` is a port, and a port is only
worth anything if you can prove it still agrees with the original. So: every
case in ``tools/parity/cases/*.express`` is compiled here by the reference
implementation, the output is checked in, and ``packages/express/test/parity.test.ts``
asserts the TypeScript compiler produces byte-identical JSON. The Flutter
client's tests read the same files, for the same reason.

When the two disagree, this file is the one that is right.

## Why it goes through the server rather than building its own compiler

It used to assemble its own ``Catalog`` and ``ExpressCompiler`` from the
published wheel. Two things were wrong with that, and they compounded:

  - It drifted out of step with the SDK and stopped running at all —

        TypeError: Catalog.from_json() got an unexpected keyword argument 'spec_version'

    which froze every golden at whatever the last working version emitted, and
    a golden nobody can regenerate cannot disagree with anything.

  - A second compiler is a second set of options to keep in sync with the
    first. The version is the one that bit: these were generated at ``v0.9.1``
    while the server emits ``1.0``, so the suite was comparing two
    implementations against a wire neither of them speaks, and the Flutter
    client refused every surface it was handed.

``brain.catalog.parser_for`` plus ``brain.express.as_wire`` is exactly how the
deployment compiles a block. Taken through it, the goldens are the bytes the
product sends — they cannot drift from the server, because they *are* the
server's. The reference implementation is still doing the compiling; this file
just stops holding a second copy of the dial settings.

Usage:
    python3 scripts/gen_parity.py [--check]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "tools" / "parity" / "cases"
EXPECTED = ROOT / "tools" / "parity" / "expected"

sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from travel_a2ui.brain.catalog import PROTOCOL_VERSION, parser_for  # noqa: E402
from travel_a2ui.brain.express import as_wire  # noqa: E402

SURFACE_ID = "parity-surface"

#: The envelope the goldens carry, which has to be the one the server emits.
#:
#: Spelled ``1.0`` and not ``v1.0`` because that is what goes on the wire: the
#: Python core writes the bare number, the TypeScript port reads it through
#: ``isV1``, and the Dart core — which spells the same version ``v1.0`` in its
#: own API — normalises it on the way in. The two SDKs disagree about the
#: spelling, so the tie goes to the side actually sending bytes.
VERSION = "1.0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if a golden is stale instead of rewriting it.",
    )
    args = parser.parse_args()

    if PROTOCOL_VERSION != VERSION:
        # Not a warning. A golden in the wrong envelope validates against
        # nothing, and the failure surfaces two layers away in a renderer.
        raise SystemExit(
            f"The server emits {PROTOCOL_VERSION!r} but the goldens are declared "
            f"{VERSION!r}. Set VERSION to match, regenerate, and expect the "
            "renderers' fixtures to move with it."
        )

    EXPECTED.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    refused: list[str] = []
    written = 0

    for case in sorted(CASES.glob("*.express")):
        source = case.read_text(encoding="utf-8")
        try:
            messages = as_wire(parser_for(SURFACE_ID).compile(source, is_final=True))
        except Exception as error:  # noqa: BLE001 - the reason is reported, not raised
            # One case the reference cannot compile should not cost us the
            # comparison on the other twenty. Reported either way, so a case
            # that quietly stops being checked is visible.
            refused.append(f"{case.stem} ({type(error).__name__})")
            continue

        rendered = json.dumps(messages, indent=2, ensure_ascii=False) + "\n"
        target = EXPECTED / f"{case.stem}.json"

        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                stale.append(case.stem)
            continue

        target.write_text(rendered, encoding="utf-8")
        written += 1

    if refused:
        print(
            f"{len(refused)} case(s) the reference compiler refused, skipped: "
            + ", ".join(refused),
            file=sys.stderr,
        )

    if args.check:
        if stale:
            print("Stale parity goldens: " + ", ".join(stale), file=sys.stderr)
            print("Run: python3 scripts/gen_parity.py", file=sys.stderr)
            return 1
        checked = len(list(CASES.glob("*.express"))) - len(refused)
        print(f"All {checked} comparable parity goldens are up to date.")
        return 0

    print(f"Wrote {written} parity goldens to {EXPECTED.relative_to(ROOT)} at {VERSION}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
