#!/usr/bin/env python3
"""Compiles the catalog's Express examples with the official A2UI SDK.

This was `build_examples.mjs`, driving the TypeScript compiler. It is Python
now, and the reason is worth stating because it is the opposite of the reason
the TypeScript compiler still exists.

**Where the SDK belongs.** Anything that runs at build time should use the
reference implementation, because "our compiler agrees with upstream" is a
property you want *asserted*, not assumed. These examples are checked into
`skills/` and taught to the model; compiling them with the SDK means the JSON
the model learns from is JSON the reference produced.

**Where it does not.** The agent's streaming path recompiles the open block on
every chunk — measured at 8 to 62 compiles per surface, 0.14–0.24 ms each,
in-process. Cloudflare does run Python Workers, so "a Worker cannot run Python"
is not the obstacle; the obstacle is that one Worker is one runtime, so a Python
compiler means a second Worker and a service binding, which puts an RPC on every
one of those 62 calls and stops the surface painting as it streams.

So: two compilers, with a clear rule for which is which. Build time is the SDK's,
the request path is the port's, and `tools/parity` diffs them.

    python3 scripts/build_examples.py            # write
    python3 scripts/build_examples.py --check    # fail if what is on disk is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
EXAMPLES = ROOT / "catalogs" / "a2ui-travel" / "examples"
COMPILED = EXAMPLES / "compiled"

SDK_MISSING = """\
The A2UI agent SDK is not installed, and this script is the reference compiler's
half of the build.

  pip install a2ui-agent-sdk
"""


def as_wire(messages):
    """Compiled messages as plain dicts — see `travel_a2ui.brain.express`."""
    from travel_a2ui.brain.express import as_wire as dump

    return dump(messages)


def parser_for(surface_id: str):
    """The server's own parser, which is the point.

    This built its own `ExpressParser` over `load_catalog(CATALOG)` — the
    *transport* catalog. The model is given the inference catalog, which is the
    transport one plus the macros, so an example written the way the brief
    teaches did not compile here: "Unknown component 'Flights'". These examples
    are the brief's worked examples; they have to compile against the catalog
    the brief describes.

    `brain.catalog.parser_for` is that parser, and it also carries the version
    the catalog declares — this script hardcoded `"v0.9.1"` through the whole
    1.0 migration without failing, because the examples are decompiled back to
    Express before they reach the brief and a wire stamp never got in front of
    the model.
    """
    try:
        from travel_a2ui.brain.catalog import parser_for as server_parser
        from travel_a2ui.brain.express import as_wire  # noqa: F401
    except ImportError as error:  # pragma: no cover - environment, not logic
        raise SystemExit(SDK_MISSING) from error

    return server_parser(surface_id)


def compile_all() -> dict[str, str]:
    """Every example, compiled. Keyed by the `.json` filename it belongs in."""
    sources = sorted(EXAMPLES.glob("*.express"))
    if not sources:
        raise SystemExit(f"No .express examples found in {EXAMPLES}")

    out: dict[str, str] = {}
    for source in sources:
        text = source.read_text(encoding="utf-8")
        try:
            # The surface id in the source wins; this is only the fallback for
            # an example that never says `surface(...)`.
            messages = as_wire(parser_for(source.stem).compile(text))
        except Exception as error:  # noqa: BLE001 - the message is the point
            raise SystemExit(
                f"{source.name} does not compile:\n  {type(error).__name__}: {error}\n\n"
                "An example that does not compile is worse than no example: it teaches "
                "the model a mistake, confidently."
            ) from error

        out[f"{source.stem}.json"] = json.dumps(messages, indent=2, ensure_ascii=False) + "\n"
    return out


def main() -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--check", action="store_true", help="Do not write; fail if stale.")
    options = args.parse_args()

    compiled = compile_all()

    if options.check:
        stale = [
            name
            for name, body in compiled.items()
            if not (COMPILED / name).exists() or (COMPILED / name).read_text("utf-8") != body
        ]
        if stale:
            print(f"Stale compiled examples: {', '.join(stale)}", file=sys.stderr)
            print("Regenerate with: python3 scripts/build_examples.py", file=sys.stderr)
            return 1
        print(f"All {len(compiled)} examples compile and their JSON is up to date.")
        return 0

    COMPILED.mkdir(parents=True, exist_ok=True)
    for name, body in compiled.items():
        (COMPILED / name).write_text(body, encoding="utf-8")
    print(f"Compiled {len(compiled)} examples into {COMPILED.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
