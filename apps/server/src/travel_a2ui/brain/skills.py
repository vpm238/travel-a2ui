"""The agent's system prompt, assembled.

Nothing in it is written here. The travel half is markdown in `prompts/`; the
A2UI half is the SDK processor's own `prompt_snippet` (`brain/catalog.py`): the
Express grammar, the pruned catalog with its macros, and the worked examples,
generated from the same configuration that parses what the model writes. The
skills in `skills/` are that same configuration exported for other agents, by
`SkillGenerator(PROCESSOR.format)`, and a test holds the two together.

A prompt has two halves:

  stable     role, flow, journey, inventory, controls, data, and the A2UI
             snippet — identical on every turn, so it caches
  volatile   the surface brief, today's date, the surface to draw into, what is
             on screen, and the trip so far — sent with each message
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Literal

from .. import ROOT
from . import trip as model
from .catalog import PROCESSOR, PROTOCOL_VERSION

SurfaceKind = Literal["inline", "sidebar", "home"]

#: The skill set this app ships: Express, as the SDK's modular skills.
SKILL_VARIANTS: list[str] = ["express-modular"]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text("utf-8").strip()


ROLE = _read("prompts", "role.md")
FLOW = _read("prompts", "flow.md")
JOURNEY = _read("prompts", "journey.md")
DATA = _read("prompts", "data.md")
SURFACE_BRIEFS: dict[str, str] = {
    kind: _read("prompts", f"surface-{kind}.md") for kind in ("inline", "sidebar", "home")
}

#: How a spoken turn draws: the same Express, passed to a tool.
#: How a typed reply puts something on the screen.
WRITTEN_DRAWING = """\
## Putting something on the screen

To draw, write an `<a2ui>` block of A2UI Express in your reply, exactly as the
rules below describe. Everything outside the block is shown as prose."""

#: How a spoken reply puts something on the screen.
SPOKEN_DRAWING = """\
## Putting something on the screen

You are answering out loud, and everything you write is spoken. To draw, call
`render_a2ui_express` with the A2UI Express block as its `express` argument,
written exactly as the rules below describe. Never write a block, a
`surface(...)` line or a component name in a reply: it would be read aloud."""

#: The jobs whose readiness is worth reporting, in the order they come up.
_GOALS = [
    ("priceFlights", "pricing flights"),
    ("priceStay", "pricing a stay"),
    ("totalTrip", "totalling the trip"),
    ("planDays", "planning the days"),
]


def describe_skill(variant: str = "express-modular") -> dict[str, Any]:
    """What a client can show about the A2UI skill the agent is given."""
    directory = ROOT / "skills" / variant
    names = sorted(path.name for path in directory.iterdir() if path.is_dir()) if directory.is_dir() else []
    return {
        "variant": variant,
        "skills": names,
        "inferenceFormat": "express",
        "protocolVersion": PROTOCOL_VERSION,
        "characters": len(PROCESSOR.prompt_snippet),
    }


def describe_all_skills() -> list[dict[str, Any]]:
    return [describe_skill(variant) for variant in SKILL_VARIANTS]


def is_skill_variant(value: Any) -> bool:
    return isinstance(value, str) and value in SKILL_VARIANTS


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def describe_trip(trip: dict[str, Any], today: str, surface: str) -> str:
    """The trip as what is settled, what is not, and what that blocks."""
    normalized = model.normalize(trip)
    summary = model.summarize(normalized, today)
    lines: list[str] = []

    decided = summary["decided"]
    if decided:
        settled = ", ".join(f"{entry['key']}={_json(entry['value'])}" for entry in decided)
        lines.append(f"- Settled, and bound for you at `$/trip/…`: {settled}")
    else:
        lines.append("- Nothing is settled yet.")
    if summary.get("nights") is not None:
        lines.append(f"- That is {summary['nights']} nights.")

    missing = summary["missing"]
    if missing:
        lines.append(
            f"- Not yet known: {', '.join(missing)}. Ask for what this turn needs, all of "
            "it at once, in one surface with one button, rather than assuming a value."
        )
        blocked = [
            f"{label} (needs {', '.join(model.missing_for(normalized, goal))})"
            for goal, label in _GOALS
            if not model.can_do(normalized, goal)
        ]
        if blocked:
            lines.append(f"- Blocked until then: {'; '.join(blocked)}.")
    else:
        lines.append(
            "- No tool is blocked: every field the lookups need is known. That is not the "
            "same as the trip being settled; the route below says what still is not."
        )

    if summary["problems"]:
        lines.append(
            "- Wrong with it: "
            + " ".join(problem["message"] for problem in summary["problems"])
            + " Get it corrected before relying on it."
        )
    basis = model.basis_of(normalized)
    if basis:
        lines.append(f'- Any priced surface says so on screen: "{basis}".')
    ruled_out = [stage for stage in (normalized.get("skip") or []) if stage]
    if ruled_out:
        lines.append(f"- Ruled out, do not ask again: {', '.join(ruled_out)}.")

    hops = model.journey(normalized)
    if hops:
        lines.append("- The route, as recorded:")
        for hop in hops:
            where = f"{hop.get('from') or '?'} → {hop['to']}"
            when = hop.get("startDate") or "no dates"
            who = f"{hop['travelers']}×" if hop.get("travelers") is not None else ""
            how = hop.get("mode") or "air"
            wants = f" — wants {', '.join(hop['wants'])}" if hop["wants"] else " — settled"
            detail = " ".join(part for part in (when, who, how) if part)
            lines.append(f"  {hop['hop'] + 1}. {where} ({detail}){wants}")
        home = normalized.get("origin")
        landing = hops[-1]["to"]
        if home:
            lines.append(
                f"- The route as recorded ends at {landing}"
                + (
                    ", which is home."
                    if landing == home
                    else f", and home is {home}. No hop from {landing} to {home} is "
                    "recorded, so as things stand the journey does not come back."
                )
            )
    else:
        lines.append("- No route recorded yet.")

    if surface != "inline":
        lines.append(
            "- **Not this turn.** You are drawing the record, not advancing the plan. "
            "Ask for nothing here; the next step is taken in the conversation."
        )
    return "\n".join(lines)


def _controls() -> str:
    from .controls import as_rules

    return (
        "## Which control to ask with\n\n"
        "A surface that asks with the wrong control is reported back to you to "
        "draw again, so get it right the first time.\n\n"
        f"{as_rules()}\n\n"
        "`Text` is fine anywhere: reading a decision back is not asking for one. "
        "`TextField` is for answers with no fixed set: a note, a hotel they "
        "remember, what the trip is for."
    )


def _inventory() -> str:
    """The places this deployment has real detail for."""
    from .providers.fixture import _DESTINATIONS, _ORIGINS

    cities = ", ".join(f"{entry['city']} ({entry['airport']})" for entry in _DESTINATIONS)
    airports = ", ".join(f"{entry['city']} ({entry['code']})" for entry in _ORIGINS)
    return (
        "## What this deployment has written down\n\n"
        "These places have real detail behind them: actual neighbourhoods, actual "
        "things worth doing, the months the weather turns. Lead with them when the "
        "traveller has not named somewhere.\n\n"
        f"- **Written down**: {cities}\n"
        f"- **Departure airports with detail**: {airports}\n\n"
        "Anywhere else works too: the tools answer with generated fares, stays and "
        "a plausible city, the same every time. Say yes and plan it.\n\n"
        "Never present any of it as real. Every figure carries a provenance label "
        "and the surface shows it. The fares are invented and nothing is bookable."
    )


def _on_screen(surfaces: Iterable[str], surface_id: str) -> str:
    held = sorted(set(surfaces))
    if not held:
        return "- Nothing is on screen yet."
    line = f"- On screen now: {', '.join(f'`{s}`' for s in held)}."
    if "sidebar" not in held:
        line += " There is no panel yet."
    if surface_id in held:
        line += f' `{surface_id}` exists, so change it with `surface("{surface_id}", update=true)`.'
    return line


def build_prompt_parts(
    *,
    surface: str,
    surface_id: str,
    trip: dict[str, Any],
    today: str,
    on_screen: Iterable[str] = (),
    draws: str = "express",
    variant: str = "express-modular",
) -> tuple[str, str]:
    """The prompt in two halves: what never changes, and what does every turn.

    `draws` is how the answer leaves: "express" for the typed channel, where
    blocks are read out of the stream, and "tools" for the spoken one, where
    the same blocks arrive as `render_a2ui_express` calls.
    """
    stable = "\n\n---\n\n".join(
        [
            ROLE,
            FLOW,
            JOURNEY,
            _inventory(),
            _controls(),
            DATA,
            SPOKEN_DRAWING if draws == "tools" else WRITTEN_DRAWING,
            PROCESSOR.prompt_snippet,
        ]
    )
    volatile = "\n".join(
        [
            SURFACE_BRIEFS[surface],
            "## This turn",
            f"- Today's date is {today}. Any date you suggest is after it.",
            (
                "- Each `render_a2ui_express` block with no `surface(...)` line becomes a new card."
                if draws == "tools"
                else f"- Draw into surface `{surface_id}`: a block with no `surface(...)` line lands there."
            ),
            _on_screen(on_screen, surface_id),
            "## The trip so far",
            describe_trip(trip, today, surface),
        ]
    )
    return stable, volatile


def build_system_prompt(**kwargs: Any) -> str:
    """Both halves joined: for a call with no conversation to continue."""
    stable, volatile = build_prompt_parts(**kwargs)
    return f"{stable}\n\n---\n\n{volatile}"
