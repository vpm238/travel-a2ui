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
from ...brain.finishing import REBUILT_IN_A_TURN, finish, on_its_own_surface
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

    async def one(surface_id: str) -> list[dict[str, Any]]:
        """One panel, drawn whole, or nothing if drawing it failed."""
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
                    panel.extend(drawn(stream.push(event["delta"])))
            panel.extend(drawn(stream.end()))
        except Exception:  # noqa: BLE001 - a stale panel beats an error banner
            return []

        # Collected rather than streamed, unlike the main loop: a panel is one
        # surface replaced whole, and a half-drawn record on screen beside a
        # finished answer reads as a bug rather than as progress.
        return panel

    # Both panels at once. They are two independent model calls with nothing to
    # say to each other, and doing them in sequence meant the sidebar waited for
    # the home summary — measured at about four and a half seconds for the pair,
    # which is most of what is left of a turn once the answer has been sent.
    #
    # `request.client` is a single scripted fake in tests, and two coroutines
    # pulling from one script would interleave into nonsense — so tests, which
    # pass a client, keep the sequential path.
    if request.client is not None:
        drawn_panels = [await one(surface_id) for surface_id in REBUILT_IN_A_TURN]
    else:
        drawn_panels = list(
            await asyncio.gather(*(one(surface_id) for surface_id in REBUILT_IN_A_TURN))
        )

    for panel in drawn_panels:
        for event in panel:
            yield event

    yield {"type": "__shape__", "shape": shape}
