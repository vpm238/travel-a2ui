#!/usr/bin/env python3
"""Exports the agent's A2UI instructions as skills, with the SDK's SkillGenerator.

The skills are generated from the processor the server parses the model with
(`brain/catalog.py`): `SkillGenerator(PROCESSOR.format)`. That format already
holds the pruned catalog, the macros and the worked examples, so the skills
another agent loads teach exactly what this agent's model is taught and held to.
Nothing is patched after generation.

    python3 scripts/build_skills.py            # write
    python3 scripts/build_skills.py --check    # fail if what is on disk is stale
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

from a2ui.skill import SkillGenerator  # noqa: E402

from travel_a2ui.brain.catalog import CATALOG_ID, PROCESSOR, PROTOCOL_VERSION  # noqa: E402

SKILLS = ROOT / "skills"

#: The one shape this app ships: the SDK's modular skill set, a core skill for
#: the notation and one per catalog.
VARIANT = "express-modular"


#: The catalog skill's name. The generator derives one from the catalog id's
#: last path segment, which is already `a2ui-travel`, so it is named here.
CATALOG_SKILL = "a2ui-travel"


def skills() -> list:
    """The core skill and the catalog skill, as `SkillGenerator` writes them."""
    generator = SkillGenerator(PROCESSOR.format)
    return [generator.generate_core_skill(), generator.generate_catalog_skill(name=CATALOG_SKILL)]


def build(out: pathlib.Path) -> list[pathlib.Path]:
    generated = skills()
    catalogs = [skill.name for skill in generated if skill.name != "a2ui-core"]
    written: list[pathlib.Path] = []
    for skill in generated:
        skill.metadata = {
            "protocol_version": PROTOCOL_VERSION,
            "inference_format": "express",
            "catalogs": catalogs,
            "catalog_id": CATALOG_ID,
        }
        target = out / VARIANT / skill.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(skill.to_markdown(), encoding="utf-8")
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero if a skill on disk is stale")
    args = parser.parse_args()

    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            probe = pathlib.Path(scratch)
            generated = {path.relative_to(probe) for path in build(probe)}
            on_disk = {path.relative_to(SKILLS) for path in (SKILLS / VARIANT).rglob("SKILL.md")}
            stale = sorted(
                str(path)
                for path in generated | on_disk
                if path not in generated
                or path not in on_disk
                or (probe / path).read_text("utf-8") != (SKILLS / path).read_text("utf-8")
            )
        if stale:
            print("Stale skills: " + ", ".join(stale), file=sys.stderr)
            print("Regenerate with: python3 scripts/build_skills.py", file=sys.stderr)
            return 1
        print("All generated skills are up to date.")
        return 0

    import shutil

    shutil.rmtree(SKILLS / VARIANT, ignore_errors=True)
    for path in build(SKILLS):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
