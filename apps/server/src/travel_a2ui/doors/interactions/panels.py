"""The standing panels, redrawn when the decisions change shape.

The sidebar and the home surface outlive the turn that drew them, so most of
what happens to them is data: a value the traveller changed reaches them as
`updateDataModel`, with no model in the path. A *rebuild* is for when the panel
needs different controls — a second hop wants a second counter — and that is
what `decision_shape` decides.

Drawn by the fast model, deliberately, whatever is answering the conversation:
the panel is the one surface in this app that is not a judgement call, because
it draws the record rather than deciding anything.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Sequence

from ...brain import trip as model
from ...brain.catalog import (
    CATALOG_ID,
    COMPONENT_NAMES,
    REQUIRED_PROPERTIES,
    VALIDATOR,
    parser_for,
)
from ...brain.express import ExpressStream, Ui
from ...brain.skills import build_system_prompt
from ...brain.finishing import (
    REBUILT_IN_A_TURN,
    STANDING_SURFACES,
    finish,
    on_its_own_surface,
)
from ...brain.macros import panel_composition
from ...gemini import stream_interaction, supported_level
from ..settings import DEFAULT_MODEL, PANEL_EFFORT, PANEL_MODEL, PANEL_REQUEST
from .press import TurnRequest


async def _rebuild_panels(
    request: TurnRequest, trip: dict[str, Any], today: str
) -> AsyncIterator[dict[str, Any]]:
    """Redraws the standing surfaces, if the trip's decisions changed shape.

    One extra model turn, and only when the shape moved — which is the same
    budget the browser was spending, now spent by the thing that knows when it
    is warranted. What counts as a decision is a fact about a trip, not about a
    panel, which is why `decision_shape` lives in the trip model.

    A failure here is silent on purpose: the traveller's answer already arrived
    and painted. A panel that is one turn stale is a much smaller problem than
    an error banner over a conversation that went fine.
    """
    shape = model.decision_shape(trip)
    if shape == request.shape:
        yield {"type": "__shape__", "shape": shape}
        return
    # Nothing to draw a panel *of* yet. The first turn usually ends with a
    # question, and a panel saying "no trip" is a panel nobody wants.
    if not trip.get("destination"):
        yield {"type": "__shape__", "shape": shape}
        return

    async def one(surface_id: str) -> tuple[list[dict[str, Any]], str]:
        """One panel, drawn whole, with the Express it was drawn from.

        The source comes back as well as the messages because the session
        keeps it: `replay` re-renders a stored panel source when the decisions
        change shape, which costs no model call at all. Without it, the only
        record that a panel exists is the shape — and this draw would be asked
        for again on the next turn, which is the per-press rebuild that was
        removed for taking 24.8 seconds.
        """
        system = build_system_prompt(
            variant=request.skill,
            surface=surface_id,
            surface_id=surface_id,
            catalog_id=CATALOG_ID,
            trip=trip,
            today=today,
        )
        stream = ExpressStream(
            parser=parser_for(surface_id),
            components=COMPONENT_NAMES,
            validator=VALIDATOR,
            required=REQUIRED_PROPERTIES,
        )

        def drawn(events: Sequence[Any]) -> list[dict[str, Any]]:
            # The panel's own id, whatever the block wrote: the brief's examples
            # name `sidebar` and `home` literally, and a sidebar block that
            # copied the home one used to draw the sidebar onto the home
            # surface, leaving the panel the client was waiting for empty.
            return [
                {
                    "type": "ui",
                    "surfaceId": surface_id,
                    "messages": finish(
                        on_its_own_surface(event.messages, surface_id), trip
                    ),
                    "done": event.done,
                }
                for event in events
                if isinstance(event, Ui)
            ]

        panel: list[dict[str, Any]] = []
        said: list[str] = []
        try:
            async for event in stream_interaction(
                api_key=request.api_key,
                # The fast model, deliberately, whatever is answering the
                # conversation. The panel is the one surface in this app that
                # is not a judgement call: it draws the record — these
                # decisions, this route, a Change button on each — from rows the
                # host has already composed. That is the work Flash Lite is good
                # at and quick at, and the thing it was measurably *not* good at
                # is deciding what comes next, which is not asked of it here.
                model=PANEL_MODEL,
                # Not chained to the conversation: a panel redraw is not
                # something the traveller said, and threading it through
                # `previous_interaction_id` would put "rebuild the panel" in the
                # transcript as a user turn.
                input=[
                    {"type": "user_input", "content": [{"type": "text", "text": PANEL_REQUEST}]}
                ],
                system_instruction=system,
                thinking_level=supported_level(PANEL_MODEL, PANEL_EFFORT),
                fallback_model=DEFAULT_MODEL,
                client=request.client,
            ):
                if event["type"] == "text":
                    said.append(event["delta"])
                    panel.extend(drawn(stream.push(event["delta"])))
            panel.extend(drawn(stream.end()))
        except Exception:  # noqa: BLE001 - a stale panel beats an error banner
            return [], ""

        # Collected rather than streamed, unlike the main loop: a panel is one
        # surface replaced whole, and a half-drawn record on screen beside a
        # finished answer reads as a bug rather than as progress.
        return panel, "".join(said)

    # Both panels at once. They are two independent model calls with nothing to
    # say to each other, and doing them in sequence meant the sidebar waited for
    # the home summary — measured at about four and a half seconds for the pair,
    # which is most of what is left of a turn once the answer has been sent.
    #
    # `request.client` is a single scripted fake in tests, and two coroutines
    # pulling from one script would interleave into nonsense — so tests, which
    # pass a client, keep the sequential path.
    if request.client is not None:
        drawn = [await one(surface_id) for surface_id in REBUILT_IN_A_TURN]
    else:
        drawn = list(await asyncio.gather(*(one(surface_id) for surface_id in REBUILT_IN_A_TURN)))

    drawn_panels = [events for events, _ in drawn]

    for panel in drawn_panels:
        for event in panel:
            yield event

    # The sources, so the session can replay them without a model next time.
    composed = panel_composition("".join(said for _, said in drawn), STANDING_SURFACES)
    if composed:
        yield {"type": "__panels__", "panels": composed}

    # The shape the panels are *actually* at, which is not the same as the shape
    # of the trip whenever a draw came back empty.
    #
    # A failed panel is silent by design — the traveller's answer already
    # arrived and painted, and an error banner over a conversation that went
    # fine is worse than a panel one turn behind. But this line used to report
    # the new shape regardless, and that is what turned "one turn behind" into
    # "behind until something else changes": the shape is written to the session
    # and handed to the client as a receipt, so the next turn compares the trip
    # against a shape the panels never reached, sees no change, and declines to
    # rebuild. The panel kept saying "Stay in Berlin · Awaiting selection" with
    # the stay booked, on a deployment where the panel model had been busy once.
    #
    # Reporting the shape we came in on costs one extra rebuild attempt on the
    # next turn, and that is exactly what a failed draw should cost. The two
    # `return`s above are different and stay as they are: declining to draw a
    # panel of a trip that has no destination yet is not a failure, and the
    # panels really are current with respect to it.
    yield {"type": "__shape__", "shape": shape if any(drawn_panels) else request.shape}
