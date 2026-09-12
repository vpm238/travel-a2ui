#!/usr/bin/env python3
"""Generates the agent's skills with the official A2UI SkillGenerator.

This used to be `tools/skillgen`, a port of the SDK's catalog crawler and prompt
generator written because the published SDK could not compile the grammar the
skills teach — it rejected `Text("Hi", variant="h3")` outright. That is fixed
upstream: 0.6.0 parses keyword arguments, emits v0.9.1 or v1.0 on request, takes
a surface id, and streams. `SkillGenerator` landed with it.

So the port is gone and this drives the real thing. What survives is the part
upstream does not have:

  **Pruning.** `A2uiCatalog.with_pruning` narrows components; `prune.py` also
  narrows *functions*, which is where the tokens actually were — a catalog of
  check-rule validators for a `checks=` argument this agent never writes. The
  allow-list lives beside the catalog it prunes.

  **Metadata.** `Skill.metadata` carries the fields the Worker reads back out of
  the frontmatter to report which skill is loaded.

    python3 scripts/build_skills.py            # write
    python3 scripts/build_skills.py --check    # fail if what is on disk is stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from prune import Vocabulary, uses_only, with_pruning  # noqa: E402

CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
EXAMPLES = ROOT / "catalogs" / "a2ui-travel" / "examples"
PRUNING = ROOT / "catalogs" / "a2ui-travel" / "agent-components.json"
SKILLS = ROOT / "skills"

PROTOCOL_VERSION = "v0.9.1"
#: The SDK prefixes catalog skills with `a2ui-`, so this is "travel" rather than
#: "a2ui-travel" — naming it the latter produces `a2ui-a2ui-travel`.
CATALOG_NAME = "travel"

DESCRIPTION = (
    "Plans trips as interactive UI: flight and hotel options, day-by-day "
    "itineraries, price breakdowns and trip controls the traveler can act on."
)


#: Messages this agent ever sends. `deleteSurface` is here because releasing a
#: decision can retire a card; the rest are the surface lifecycle. Everything
#: else in the spec's server-to-client schema is somebody else's feature.
ALLOWED_MESSAGES = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"]


def pruned_catalog(schema: dict, scratch: pathlib.Path):
    """The catalog the model is shown, pruned by the SDK's own `with_pruning`.

    This used to build an `A2uiCatalog` by hand with `s2c_schema={}` and
    `common_types_schema={}`, and call the local port instead. That worked, and
    it also meant three of upstream's four pruning passes had nothing to act on:
    message pruning and common-type pruning both read schemas that were not
    there. Loading the catalog the way the SDK intends — `from_config`, which
    pulls the bundled spec schemas for the version — is what makes
    `with_pruning(allowed_components=…, allowed_messages=…)` mean anything.

    Measured afterwards: for Express it is byte-identical, because Express
    renders neither messages nor common types — it has `surface()` and `$path =`
    instead. For direct JSON it is not, because that format prints the message
    schemas, and it had been printing an empty set of them.

    `allowed_functions` stays local. Upstream does not prune functions, and on
    this catalog that axis was worth three times the component one — most of it
    check-rule validators for a `checks=` argument this agent never writes.
    """
    from a2ui.schema.catalog import A2uiCatalog, CatalogConfig

    path = scratch / "catalog.pruned.json"
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    allow = json.loads(PRUNING.read_text(encoding="utf-8"))
    config = CatalogConfig.from_path(CATALOG_NAME, str(path))
    catalog = A2uiCatalog.from_config(config, version=PROTOCOL_VERSION.removeprefix("v"))

    return catalog.with_pruning(
        allowed_components=allow["allowedComponents"],
        allowed_messages=ALLOWED_MESSAGES,
    )


def make_format(inference_format: str, catalog, examples_glob: str):
    """One configured InferenceFormat, over an already-pruned catalog."""
    if inference_format == "express":
        from a2ui.inference_formats.experimental.express.format import ExpressFormat

        return ExpressFormat(
            catalog=catalog, version=PROTOCOL_VERSION, examples_path=examples_glob
        )

    from a2ui.inference_formats.direct_json.format import DirectJsonFormat

    # Direct JSON names spec versions without the `v`; Express keeps it. It
    # builds its own catalogs from configs, so the pruned one is handed over
    # afterwards rather than through the constructor.
    fmt = DirectJsonFormat(version=PROTOCOL_VERSION.removeprefix("v"), catalogs=[])
    fmt._supported_catalogs = [catalog]  # noqa: SLF001 - no public setter yet
    fmt._catalog_example_paths = {catalog.catalog_id: examples_glob}  # noqa: SLF001
    return fmt


#: `<format>-<shape>` → the two axes. Sibling directories rather than different
#: skill names, so a monolithic Express `a2ui` and a monolithic JSON `a2ui` can
#: both exist without either renaming itself to say which it is.
VARIANTS: list[tuple[str, str]] = [
    ("express", "monolithic"),
    ("express", "modular"),
    ("direct_json", "monolithic"),
]


def pruned_schema() -> tuple[dict, set[str], set[str]]:
    """The catalog with functions narrowed — the axis upstream does not have.

    Components are left to `A2uiCatalog.with_pruning`, which also sweeps the
    message and common-type schemas that only it can see. What comes back here
    is what survives *both*, which is what the example filter has to match.
    """
    schema = json.loads(CATALOG.read_text(encoding="utf-8"))
    allow = json.loads(PRUNING.read_text(encoding="utf-8"))

    narrowed = with_pruning(schema, allowed_functions=allow.get("allowedFunctions"))
    return (
        narrowed,
        set(allow["allowedComponents"]) & set(narrowed.get("components", {})),
        set(narrowed.get("functions", {})),
    )


def staged_examples(vocabulary: Vocabulary, into: pathlib.Path) -> str:
    """Copies the examples that survive pruning, and returns a glob for them.

    The SDK loads examples by glob, so the filter has to happen on disk. An
    example calling a pruned component teaches the model a call the prompt no
    longer documents, which is the failure this exists to prevent.
    """
    into.mkdir(parents=True, exist_ok=True)
    kept = 0
    for path in sorted(EXAMPLES.glob("*.express")):
        if not uses_only(path.read_text(encoding="utf-8"), vocabulary):
            continue
        shutil.copy2(path, into / path.name)
        kept += 1
    if kept == 0:
        raise SystemExit("Pruning removed every example — check agent-components.json.")
    return str(into / "*.express")


#: Upstream's grammar rules illustrate `_template` with `itemTemplate =
#: Image($url)`, hardcoded rather than drawn from the catalog. Prune `Image` and
#: the prompt teaches a call it does not document — the exact contradiction the
#: example filter exists to prevent, arriving through the one section pruning
#: cannot reach. Substituted here until the rule takes its example from the
#: catalog it is generated against.
GRAMMAR_FIXUPS = [
    ("itemTemplate = Image($url)", "itemTemplate = Text($name)"),
    ("root = Card(...)", "root = Column(...)"),
]


def repair_grammar(markdown: str, vocabulary: Vocabulary) -> str:
    """Rewrites hardcoded grammar examples that name a pruned component."""
    for stale, replacement in GRAMMAR_FIXUPS:
        if stale in markdown and not uses_only(stale, vocabulary):
            markdown = markdown.replace(stale, replacement)
    return markdown


def metadata(inference_format: str, catalog_id: str, catalogs: list[str]) -> dict:
    """What the Worker reads back out of the frontmatter to report what is loaded."""
    return {
        "protocol_version": PROTOCOL_VERSION.removeprefix("v"),
        "inference_format": inference_format,
        "catalogs": catalogs,
        "catalog_id": catalog_id,
    }


#: The commit that merged SkillGenerator, kept in step with the CI pin.
SDK_REF = "d27d708"

SDK_MISSING = f"""\
The A2UI agent SDK with SkillGenerator is not installed.

`SkillGenerator` is merged upstream but not yet in a published wheel, so it has
to be built from source — which regenerates an ANTLR parser and therefore wants
antlr4-tools and a JDK:

  pip install antlr4-tools hatchling
  pip install --no-build-isolation \\
    "a2ui-agent-sdk @ git+https://github.com/a2ui-project/a2ui@{SDK_REF}#subdirectory=agent_sdks/python/a2ui_agent"

Swap that for `pip install a2ui-agent-sdk` the day a release carries a2ui.skill.
"""


def build(out: pathlib.Path) -> list[pathlib.Path]:
    try:
        from a2ui.skill import SkillGenerator
    except ImportError as error:  # pragma: no cover - environment, not logic
        raise SystemExit(SDK_MISSING) from error

    schema, components, functions = pruned_schema()
    vocabulary = Vocabulary(
        allowed_components=components,
        known_components=set(json.loads(CATALOG.read_text("utf-8"))["components"]),
        allowed_functions=functions,
        known_functions=set(json.loads(CATALOG.read_text("utf-8"))["functions"]),
    )

    catalog_id = str(schema.get("catalogId") or schema.get("$id") or "")
    written: list[pathlib.Path] = []

    with tempfile.TemporaryDirectory() as scratch:
        glob = staged_examples(vocabulary, pathlib.Path(scratch) / "examples")

        catalog = pruned_catalog(schema, pathlib.Path(scratch))

        for inference_format, shape in VARIANTS:
            fmt = make_format(inference_format, catalog, glob)
            generator = SkillGenerator(fmt)

            if shape == "monolithic":
                skills = [generator.generate_skill(name="a2ui", description=DESCRIPTION)]
                catalogs = [f"a2ui-{CATALOG_NAME}"]
            else:
                skillset = generator.generate_skillset()
                skills = list(skillset.values())
                # The SDK derives a catalog skill's name from the catalog *id*,
                # and ours is a URL whose last segment is already `a2ui-travel`
                # — so its `a2ui-` prefix lands on top of one. What the package
                # is called is ours to decide; the content is what came from the
                # generator.
                for skill in skills:
                    if skill.name.startswith("a2ui-a2ui-"):
                        skill.name = skill.name.replace("a2ui-a2ui-", "a2ui-", 1)
                        skill.filename = f"{skill.name}/SKILL.md"
                catalogs = [skill.name for skill in skills if skill.name != "a2ui-core"]

            directory = out / f"{inference_format.replace('_', '-')}-{shape}"
            for skill in skills:
                skill.metadata = metadata(inference_format, catalog_id, catalogs)
                target = directory / skill.name / "SKILL.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    repair_grammar(skill.to_markdown(), vocabulary), encoding="utf-8"
                )
                written.append(target)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any generated skill differs from disk.",
    )
    args = parser.parse_args()

    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            probe = pathlib.Path(scratch)
            stale = []
            for path in build(probe):
                target = SKILLS / path.relative_to(probe)
                if not target.exists() or target.read_text("utf-8") != path.read_text("utf-8"):
                    stale.append(str(path.relative_to(probe)))
            if stale:
                print("Stale skills: " + ", ".join(stale), file=sys.stderr)
                print("Regenerate with: python3 scripts/build_skills.py", file=sys.stderr)
                return 1
        print("All generated skills are up to date.")
        return 0

    written = build(SKILLS)
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"\n{len(written)} skill file(s) written to {SKILLS.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
