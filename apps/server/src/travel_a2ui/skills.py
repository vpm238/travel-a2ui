"""Assembling the agent's system prompt out of generated skills.

Nothing here is written here. The skills are generated from the catalog by the
SDK's `SkillGenerator`; the role and the surface briefs are markdown in
`prompts/`. Both are read as text, so the file reviewed in a diff is byte for
byte the file the model reads, and there is no second copy to drift.

A turn's system prompt is three layers:

  1. **The role** — who the agent is and how it behaves.
  2. **The skill** — how to emit A2UI, and what components exist. One of several
     variants, chosen per request, which is what makes the two skill shapes
     comparable on the same traffic rather than in theory.
  3. **The surface brief** — what *this* surface is for. Inline, sidebar and
     home want genuinely different interfaces from the same catalog, and this is
     where that difference is stated.

Layers 1 and 2 are stable across a conversation and carry the cache breakpoint.
Layer 3 changes per surface and comes last, so switching surfaces costs a cache
miss on a few hundred tokens rather than on all of it.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Literal

from . import trip as model

_ROOT = pathlib.Path(__file__).resolve().parents[4]

SkillVariant = Literal["express-monolithic", "express-modular", "direct-json-monolithic"]
SurfaceKind = Literal["inline", "sidebar", "home"]

SKILL_VARIANTS: list[str] = [
    "express-monolithic",
    "express-modular",
    "direct-json-monolithic",
]

#: Which generated skill files each variant loads, in load order.
_SKILL_FILES: dict[str, list[str]] = {
    "express-monolithic": ["express-monolithic/a2ui/SKILL.md"],
    "express-modular": [
        "express-modular/a2ui-core/SKILL.md",
        "express-modular/a2ui-travel/SKILL.md",
    ],
    "direct-json-monolithic": ["direct-json-monolithic/a2ui/SKILL.md"],
}


def _read(*parts: str) -> str:
    return (_ROOT.joinpath(*parts)).read_text("utf-8")


ROLE = _read("prompts", "role.md").strip()

SURFACE_BRIEFS: dict[str, str] = {
    kind: _read("prompts", f"surface-{kind}.md").strip()
    for kind in ("inline", "sidebar", "home")
}

_SKILL_SOURCES: dict[str, list[str]] = {
    variant: [_read("skills", name) for name in files]
    for variant, files in _SKILL_FILES.items()
}


def _body(skill: str) -> str:
    """Strips YAML frontmatter — the model wants the instructions, not the metadata."""
    if not skill.startswith("---"):
        return skill.strip()
    end = skill.find("\n---", 3)
    if end == -1:
        return skill.strip()
    return skill[end + 4 :].strip()


def _frontmatter_field(skill: str, key: str) -> str | None:
    """Reads one field out of a skill's frontmatter, for reporting what is loaded."""
    if not skill.startswith("---"):
        return None
    end = skill.find("\n---", 3)
    block = skill[3:] if end == -1 else skill[3:end]
    match = re.search(rf'^\s*{re.escape(key)}:\s*"?([^"\n]+)"?\s*$', block, re.MULTILINE)
    return match.group(1).strip() if match else None


def describe_skill(variant: str) -> dict[str, Any]:
    sources = _SKILL_SOURCES[variant]
    return {
        "variant": variant,
        "skills": [
            _frontmatter_field(source, "name") or f"skill-{index}"
            for index, source in enumerate(sources)
        ],
        "inferenceFormat": _frontmatter_field(sources[0], "inference_format") or "express",
        "protocolVersion": _frontmatter_field(sources[0], "protocol_version") or "0.9.1",
        "characters": sum(len(_body(source)) for source in sources),
    }


def describe_all_skills() -> list[dict[str, Any]]:
    return [describe_skill(variant) for variant in SKILL_VARIANTS]


def skill_text(variant: str) -> str:
    """The raw instructions a variant loads, joined.

    For fingerprinting rather than for reading: `describe_skill` reports skill
    *names*, which do not change when the instructions behind them do, so a
    stamp built from those would happily call a rewritten skill unchanged.
    """
    return "\n".join(_SKILL_SOURCES[variant])


def is_skill_variant(value: Any) -> bool:
    return isinstance(value, str) and value in SKILL_VARIANTS


#: The jobs whose readiness is worth reporting, in the order they come up.
_GOALS = [
    ("priceFlights", "pricing flights"),
    ("priceStay", "pricing a stay"),
    ("totalTrip", "totalling the trip"),
    ("planDays", "planning the days"),
]


def _json(value: Any) -> str:
    """`JSON.stringify` for the values that reach it here.

    The prompt prints settled values as JSON, and the two implementations have
    to agree on the text: Python's default renders `True` and `'Madrid'`, which
    would show the model a trip in a notation nothing else in the system uses.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def describe_trip(trip: dict[str, Any], today: str, surface: str) -> str:
    """The trip as three lists rather than one blob.

    `{"destination":"Madrid"}` leaves the model to work out what is absent, and
    what it does when it is not sure is fill the gap in itself. Naming the
    missing fields — and, separately, what each one is currently blocking — is
    what turns "ask before you price" from advice into something it can act on.

    All of it comes from the trip model, which is also what the tools check and
    what the browser pre-fills, so the prompt cannot disagree with the gate.
    """
    normalized = model.normalize(trip)
    summary = model.summarize(normalized, today)

    lines: list[str] = []

    decided = summary["decided"]
    if decided:
        settled = ", ".join(f"{entry['key']}={_json(entry['value'])}" for entry in decided)
        lines.append(
            "- Settled, bound at `$/trip/…` and pre-filled into every surface for you: "
            + settled
        )
    else:
        lines.append("- Nothing is settled yet.")

    if summary.get("nights") is not None:
        lines.append(f"- That is {summary['nights']} nights.")

    missing = summary["missing"]
    if missing:
        lines.append(
            f"- Not yet known: {', '.join(missing)}. Ask for what this turn needs — all of "
            "it at once, in one surface with one button — rather than assuming a value."
        )
        # Naming the consequence, not just the gap: "you cannot price flights"
        # is a reason to ask, where "origin is missing" is a fact to route around.
        blocked = [
            f"{label} (needs {', '.join(model.missing_for(normalized, goal))})"
            for goal, label in _GOALS
            if not model.can_do(normalized, goal)
        ]
        if blocked:
            lines.append(f"- Blocked until then: {'; '.join(blocked)}.")
    else:
        lines.append("- Everything needed is known. Do not ask again; build on it.")

    if summary["problems"]:
        lines.append(
            "- Wrong with it: "
            + " ".join(problem["message"] for problem in summary["problems"])
            + " Get it corrected before relying on it."
        )

    basis = model.basis_of(normalized)
    if basis:
        lines.append(f'- Any priced surface says so on screen: "{basis}".')

    progress = model.plan(normalized)
    ruled_out = [step["stage"] for step in progress["steps"] if step.get("skipped")]
    lines.append(
        f"- Progress: {progress['done']} of {progress['total']} stages settled"
        + (f" ({', '.join(ruled_out)} ruled out)" if ruled_out else "")
        + "."
    )

    # "Lead the trip" and "the panel is read-only" are in direct conflict on a
    # panel turn, and the model resolves it the way it was always going to: it
    # advances the plan, in the panel, with the controls the next step needs —
    # which the host then ignores. So the instruction is scoped: on this turn
    # the next step is somebody else's job.
    next_step = model.next_step_for(normalized)
    if surface == "inline":
        lines.append(f"- **Do this next.** {next_step}")
    else:
        scoped = (
            "You are drawing the record, not advancing the plan. Ask for nothing here. "
            "The next step is asked in the conversation, on the next inline turn."
            if surface == "sidebar"
            else "You are drawing a standing summary, not advancing the plan. Ask for nothing "
            "here; the next step is asked in the conversation."
        )
        lines.append(f"- **Not this turn.** {scoped} For context, what is outstanding is: {next_step}")

    return "\n".join(lines)


def build_system_prompt(
    *,
    variant: str,
    surface: str,
    surface_id: str,
    catalog_id: str,
    trip: dict[str, Any],
    today: str,
    origin_hint: dict[str, str] | None = None,
) -> str:
    """Builds the system prompt, with the stable half first.

    The skill is thousands of tokens and identical on every turn of a
    conversation; the trip state is a few dozen and changes constantly. Stable
    first and volatile second is the whole optimisation: Gemini caches a
    repeated prefix implicitly, so the catalog, the rules and the component
    signatures are paid for once and read back thereafter. Putting the trip's
    current state above them would move the boundary to the top of the prompt
    and cache nothing.
    """
    stable = "\n\n---\n\n".join(
        [ROLE, *(_body(source) for source in _SKILL_SOURCES[variant])]
    )

    parts = [
        SURFACE_BRIEFS[surface],
        "## This turn",
        f"- Today's date is {today}. Any date you suggest is after it.",
        f"- Draw into surface `{surface_id}`.",
        f"- The host's catalog id is `{catalog_id}`.",
        "## The trip so far",
        describe_trip(trip, today, surface),
    ]
    if origin_hint and not trip.get("origin"):
        parts.append(
            f"- The browser's timezone is {origin_hint['timeZone']}, so {origin_hint['city']} "
            f"({origin_hint['code']}) is a reasonable *suggestion* for where they are flying "
            "from. Offer it pre-filled and let them change it. Do not treat it as their answer."
        )

    # Empty entries drop out rather than becoming blank lines — including the
    # origin hint when there is none, which is why this is a filter and not a
    # conditional append.
    volatile = "\n".join(part for part in parts if part)
    return f"{stable}\n\n---\n\n{volatile}"
