"""The contract every travel data source answers, and why it is shaped this way.

The code this replaced called a fixture module directly, under a comment
promising you could swap it for real API calls and nothing above would change.
That was an assertion rather than a seam, and being an assertion it hid four
ways to answer a question with something untrue:

  asked                  answered
  ---------------------  ------------------------------------------------
  flights under $1       an empty list, under a heading that said flights
  flights to Reykjavik   four flights to REY, an airport code taken from
                         the first three letters
  hotels in Reykjavik    four Madrid hotels in Lavapiés, priced in euros,
                         captioned "4 stay(s) in MAD"
  anything               nothing anywhere said the numbers were invented

All four are one bug: a function that could not say "I don't know" said
something else instead. So not-knowing is the only alternative to knowing here,
and `found()` refuses to build a success with nothing in it.

Python cannot express the TypeScript's `[T, ...T[]]` — a list type that cannot
be empty — so the guarantee that was the compiler's there is a runtime check
here. Which is why `found()` raises rather than returning: reaching it with an
empty list means a provider decided it had succeeded at finding nothing, and
there is no sensible way to render that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Sequence


@dataclass(frozen=True)
class Provenance:
    """Where an answer came from, carried with the answer rather than assumed."""

    #: Stable id for the source: `fixture`, `amadeus`.
    source: str
    #: True when these numbers describe the real world.
    live: bool
    #: Short enough for a badge on a card.
    label: str
    #: A sentence for a tooltip, a footer, or the model to repeat.
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "live": self.live, "label": self.label, "detail": self.detail}


@dataclass(frozen=True)
class Found:
    """A provider found something. Never empty."""

    items: list[Any]
    provenance: Provenance
    #: Filters dropped to have anything to show, in the traveller's words.
    #:
    #: Relaxing silently would be its own dishonesty — a cheaper flight with a
    #: stop is not the flight that was asked for — so the surface says what it
    #: widened.
    relaxed: list[str] = field(default_factory=list)
    note: str = ""
    #: The currency the prices are quoted in, when the items carry prices.
    currency: str | None = None
    ok: Literal[True] = True


@dataclass(frozen=True)
class NotFound:
    """Why a provider has nothing, in a form the agent can act on."""

    reason: Literal["unknown-destination", "unknown-origin", "no-coverage", "upstream-error"]
    provenance: Provenance
    #: Said to the traveller as-is. Never a stack trace, never a code.
    message: str
    #: Concrete things that would make this work. Rendered as choices.
    recover: list[str] = field(default_factory=list)
    ok: Literal[False] = False


Outcome = Found | NotFound


def found(
    items: Sequence[Any],
    provenance: Provenance,
    note: str,
    relaxed: Sequence[str] = (),
    currency: str | None = None,
) -> Found:
    """Builds a `Found`, or raises.

    The raise is deliberate and is not defensive programming. Failing loudly in
    the tool call gets the model a real error it can relay, which is strictly
    better than a surface with a heading and no rows.
    """
    if not items:
        raise ValueError(
            f"{provenance.source} reported success with no results. "
            "A provider with nothing to show must return `not_found` and say why."
        )
    return Found(
        items=list(items),
        provenance=provenance,
        relaxed=list(relaxed),
        note=note,
        currency=currency,
    )


def not_found(
    reason: str,
    provenance: Provenance,
    message: str,
    recover: Sequence[str],
) -> NotFound:
    return NotFound(
        reason=reason,  # type: ignore[arg-type]
        provenance=provenance,
        message=message,
        recover=list(recover),
    )


class TravelProvider(Protocol):
    """A source of travel data.

    Async throughout, including in the fixture implementation that has nothing
    to await. A synchronous interface would have meant every caller changing
    shape the day a real provider arrived — which is exactly the kind of "swap
    it and nothing above changes" claim this contract exists to stop making on
    credit.
    """

    provenance: Provenance

    async def resolve_destination(self, query: str) -> dict[str, Any] | None:
        """Resolves free text to a place, or nothing. Nothing is a real answer."""
        ...

    async def destinations(self) -> list[dict[str, Any]]:
        """Everywhere this provider can talk about. Used to offer alternatives."""
        ...

    async def origins(self) -> list[dict[str, Any]]: ...

    async def search_flights(self, query: dict[str, Any]) -> Outcome: ...

    async def search_hotels(self, query: dict[str, Any]) -> Outcome: ...

    async def get_weather(
        self, destination: str, start_date: str | None = None, days: int = 5
    ) -> Outcome:
        """The forecast from `start_date`, which the caller is expected to fill in.

        It is optional in the signature and should not be in practice. Every
        caller in this app knows the day its turn is happening on — the tools
        from `ToolContext.day()`, the surfaces from `build_surface(today=…)` —
        and a provider left to read the clock itself is a provider whose answer
        depends on the day it runs. That is untestable by construction: the
        golden for "no date given" passed on the weekday it was recorded on and
        failed on the other six.
        """
        ...
