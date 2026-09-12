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


def _controls() -> str:
    """Which control each decision is asked for in.

    Rendered from `data/controls.json`, which is also what the host checks a
    finished surface against — so this is the rule being taught rather than a
    second copy of it that can drift out of step with the one enforced.

    In the stable half: it comes from a file and does not change between turns.
    """
    from .controls import as_rules

    return (
        "## Which control to ask with\n\n"
        "Checked before anything is drawn. A surface that asks with the wrong "
        "control is rejected and you are told to write it again, so this is "
        "worth getting right the first time.\n\n"
        f"{as_rules()}\n\n"
        "`Text` is fine anywhere — reading a decision back is not asking for one. "
        "`TextField` is for answers with no fixed set: a note, a hotel they "
        "remember, what the trip is for."
    )


def _inventory() -> str:
    """What this deployment can actually answer about.

    The agent was never told. It would take "a week in Ulaanbaatar", start
    planning it, call `search_flights`, and only then be handed
    `unknown-destination` with the list of nine cities attached — having already
    said it was looking. Discovering the inventory by failing against it is a
    turn wasted and a promise broken, and the traveller watched both.

    It belongs in the *stable* half, before the cache breakpoint: it comes from
    `data/` and does not change between turns, so it is paid for once per
    conversation rather than on every one.

    Deliberately not the whole of `data/`. Airlines, lodging words and
    currencies are how a fixture is *assembled* — the agent never picks from
    them and naming them would be a thousand tokens of noise. Destinations and
    departure airports are the two lists a request can fail against, so they are
    the two the agent needs.
    """
    from .providers.fixture import _DESTINATIONS, _ORIGINS

    cities = ", ".join(f"{entry['city']} ({entry['airport']})" for entry in _DESTINATIONS)
    airports = ", ".join(f"{entry['city']} ({entry['code']})" for entry in _ORIGINS)
    return (
        "## What this deployment has written down\n\n"
        "These places have real detail behind them — actual neighbourhoods, actual "
        "things worth doing, the months the weather turns. Lead with them when the "
        "traveller has not named somewhere, because they are the ones you can be "
        "specific about.\n\n"
        f"- **Written down**: {cities}\n"
        f"- **Departure airports with detail**: {airports}\n\n"
        "Anywhere else works too. Ask for Boston or Reykjavík and the tools answer "
        "with generated fares, stays and a plausible city — the same made-up place "
        "every time, so a trip you plan today is the trip you find tomorrow. Say "
        "yes and plan it; do not apologise for a list and do not offer a "
        "substitute city nobody asked for.\n\n"
        "What you must never do is present any of it as real. Every figure here "
        "carries a provenance label and the surface shows it. The fares are "
        "invented, nothing is bookable, and a traveller who might act on a price "
        "is owed that in the same breath."
    )


def build_prompt_parts(
    *,
    variant: str,
    surface: str,
    surface_id: str,
    catalog_id: str,
    trip: dict[str, Any],
    today: str,
) -> tuple[str, str]:
    """The prompt in its two halves: what never changes, and what always does.

    The stable half is the role, the inventory and the skill — about thirteen
    thousand tokens, byte-identical on every turn of a conversation. The
    volatile half is a few dozen tokens: today's date, which surface to draw
    into, and what has been decided so far.

    They are returned separately because the Interactions API is stateful and
    the difference is not small. Measured, on a 5,411-token system instruction:

        turn 1, system_instruction sent              5,411 input tokens
        turn 2, previous_interaction_id, no system      44 input tokens
        turn 3, previous_interaction_id, no system      83 input tokens

    `total_cached_tokens` was 0 throughout, so this is not implicit caching
    quietly working — the context genuinely lives on Google's side, and sending
    it again is paying twice for the same thing. Every round inside a turn was
    doing exactly that.

    So the stable half is the system instruction, sent once when a conversation
    starts, and the volatile half rides in with each message. What makes that
    safe is that the volatile half has to arrive *anyway*: the surface id and
    the trip change every turn, and a model told once, ten turns ago, which
    surface to draw into would draw into the wrong one.
    """
    stable = "\n\n---\n\n".join(
        [ROLE, _inventory(), _controls(), *(_body(source) for source in _SKILL_SOURCES[variant])]
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
    # Empty entries drop out rather than becoming blank lines.
    return stable, "\n".join(part for part in parts if part)


def build_system_prompt(**kwargs: Any) -> str:
    """Both halves, joined — the whole prompt as one string.

    What a door with no conversation to continue sends: MCP, where every call is
    self-contained, and the voice relay's panel redraws. The goldens are over
    this, because it is the only place the two halves are both visible.
    """
    stable, volatile = build_prompt_parts(**kwargs)
    return f"{stable}\n\n---\n\n{volatile}"
