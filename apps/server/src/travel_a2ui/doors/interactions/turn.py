"""One turn of the conversation: ask the model, draw what it answers.

The loop, in order:

  1. Ask the model, streaming. Split prose from A2UI as it arrives, so the
     surface paints while the model is still typing.
  2. When it calls a tool: draw the shape of the answer first, run the tool,
     then fill the shape. The screen is busy for the whole wait rather than
     empty for it.
  3. Hand back the receipt — the interaction to resume from, and the trip as it
     now stands — before the panels are redrawn, because a traveller who
     presses something cancels everything after this point.
  4. Bring the standing panels up to date.

What the traveller did before any of this is `press.py`; the panels are
`panels.py`. This is the part that talks to the model.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, AsyncIterator, Sequence

from ...brain import trip as model
from ...brain.catalog import (
    CATALOG_ID,
    COMPONENT_NAMES,
    PROTOCOL_VERSION,
    REQUIRED_PROPERTIES,
    VALIDATOR,
    parser_for,
)
from ...brain.express import ExpressStream, Failed, FenceGate, Text, Ui, as_wire
from ...brain.promises import TYPED_NUDGE, promised
from ...brain.providers.fixture import FixtureProvider
from ...brain.macros import (
    airport_choices,
    currency_for,
    closing_express,
    expand as expand_macros,
    file_rows,
    clear_placeholders,
    landing_for,
    opening_express,
    placeholder_rows,
    panel_composition,
    replay,
    rows_in,
    without_the_rows,
)
from ...brain.skills import build_prompt_parts, panel_is_stale
from ...brain.finishing import (
    STANDING_SURFACES,
    finish,
    on_its_own_surface,
    panel_events,
    stack_blocks,
)
from ...brain.tools import ToolContext, gemini_tools, grounding_tools, run_tool
from ...gemini import describe_api_error, stream_interaction
from ..settings import FALLBACK_MODEL, MAX_TOOL_ROUNDS, PANEL_REQUEST, _today
# Safe to import: `panels` reaches into `press` and never back into this module.
from .panels import _rebuild_panels
from .press import (
    TurnRequest,
    TurnResult,
    _commit,
    _leg_pressed,
    _party_paths,
    as_trip_fields,
    describe_action,
    stop_of_fare,
)


async def run_turn(request: TurnRequest) -> AsyncIterator[dict[str, Any]]:
    """Runs one turn, yielding events as they happen.

    An async generator rather than a callback, because the transport is SSE and
    a generator is what FastAPI's streaming response wants — and because it
    makes the whole loop testable by iterating it.
    """
    today = _today(request.client_hints)
    provider = request.provider or FixtureProvider()

    # Values the traveller set on screen are facts, and the host records them
    # rather than depending on the model to notice and call `save_trip`. That
    # dependency is what made a second card forget what the first one asked.
    #
    # The action's own context first, then the rest of the surface: the context
    # is what the button declared it was sending, so it wins where they
    # disagree, and the surrounding data model fills in anything the traveller
    # set that no binding named.
    from_surface = model.normalize((request.action.data_model or {}).get("trip") if request.action else None)
    # The press's own keys, plus the ones that are the trip's under another name.
    #
    # A fare's context says `id` and `price`; the trip says `selectedFlight` and
    # `flightPrice`, so normalising alone dropped them and recording the choice
    # fell to the model. See `as_trip_fields` for what that cost on the return
    # hop.
    from_context = {
        **model.normalize(request.action.context if request.action else None),
        **model.normalize(as_trip_fields(request.action)),
    }

    # Which hop was pressed, when the press says so.
    #
    # A fare for the second hop carries its leg, because the second hop keeps
    # its own ticket and the trip's flat `selectedFlight` is the first hop's.
    # Without this the return landed on the trip and overwrote the outbound —
    # see `onto_leg`. Read off the raw context rather than the normalised trip,
    # because `leg` is not a trip field and normalising drops it.
    #
    # The fare's own route decides when it can: a card carries the airports it
    # flies between, which is a fact, where `hop` is whatever the agent passed
    # when it drew the list. See `stop_of_fare`.
    pressed = request.action.context if request.action else None
    stop = await stop_of_fare(pressed, {**request.trip, **from_surface}, provider)
    leg_index = (stop - 1 if stop > 0 else None) if stop is not None else _leg_pressed(pressed)

    proposed = {**request.trip, **from_surface, **from_context}
    if leg_index is not None:
        proposed = model.onto_leg(
            {**request.trip, **from_surface}, dict(from_context), leg_index
        )
    trip, refused = _commit(request.trip, proposed, today)

    # The standing panels, brought up to date with what changed — which is data,
    # and only ever data.
    #
    # Data is enough while the panel's rows stay the same: every value on
    # `Trip()` is bound, so a price or a date arrives as `updateDataModel` and
    # costs nothing. A *new* row is not data — it is a component, and
    # `updateDataModel` cannot add one. Rows became conditional so that a panel
    # shows what is settled rather than a card shimmering at a decision nobody
    # has made, and the cost was that each row's first appearance needs the panel
    # drawn again.
    #
    # The host used to do that itself, re-expanding `Trip()` whenever
    # `decision_shape` moved. It was fast — 0.1s after a fare was pressed — and
    # it was the wrong shape: every other surface in this app goes up because
    # the agent asked for it, and that one went up because the host decided the
    # panel was stale. So it is gone, and the agent is *told* the panel's rows
    # are behind (see `panel_is_stale` in the prompt) and draws it in the turn it
    # is already answering — the sidebar being the one surface a block may
    # address by name, which `on_its_own_surface` exists to allow.
    #
    # It does not take the hint. Measured over a full walk through Chromium with
    # the hint in the turn's notes, `Trip` offered on `save_trip`'s `draw`, and
    # the brief saying to write the block first: zero times. Every panel move
    # came from the client asking for a `sidebar` turn of its own once the answer
    # had landed — one model call, 4 to 6 seconds, and 18.4s after a fare was
    # pressed or 29.6s after a stay by the time the turn it waits for is over.
    #
    # So the host re-renders what the agent already composed. The agent's own
    # block, addressed to the panel in its own words, kept on the session and
    # compiled again against the record as it stands — which is the same
    # interface drawn from newer facts, not an interface the host chose. No model
    # call, and nothing to ignore. See `panel_composition` and `replay`.
    # Against the shape the *panel* was last drawn for, not the trip's shape
    # after the commit above. The press is what adds the row, and the commit has
    # already happened by the time this is read — so baselining on the trip makes
    # the press's own change invisible and the replay never fires for the one
    # thing it exists for. `request.shape` is what the panel on screen is drawn
    # for, which is the question being asked.
    shape_was = request.shape

    def panels() -> list[dict[str, Any]]:
        nonlocal shape_was
        out: list[dict[str, Any]] = list(panel_events(trip))
        shape_now = model.decision_shape(trip)
        if shape_now == shape_was:
            # Every value on the panel is bound, so a price or a date arriving is
            # data and costs nobody anything. Only the *shape* needs components.
            return out
        shape_was = shape_now
        for surface, source in (request.panels or {}).items():
            # `finish`, like every other surface. The replay is a `createSurface`
            # and so carries a data model, and the macro's own bindings declare
            # every path they read — as nulls, until seeding fills them. Sent
            # raw, that `createSurface` landed on top of the `/trip/legs` from
            # `panel_events` just above it and wiped a hop's airline and times
            # back out of the client's data model. See `seed_surface_trip`.
            drawn = finish(replay(source, trip, surface, PROTOCOL_VERSION), trip)
            if drawn:
                out.append(
                    {"type": "ui", "surfaceId": surface, "messages": drawn, "done": True}
                )
        return out

    # Pressing a button *is* saying so. Whatever the surface sent stops being a
    # guess, however it got into the control — the agent's suggestion, a value
    # carried over from an earlier turn, or something typed just now.
    said = [*from_surface.keys(), *from_context.keys()]
    if said:
        # Replaced, not merged. `confirm` returns a trip with the `assumed` key
        # *removed* once nothing is assumed any more, and merging a dict that
        # lacks a key cannot take that key off the target — so the mark
        # survived every press, the host kept the question open, and the agent
        # went on re-asking something the traveller had already pressed.
        confirmed = model.confirm(trip, said)
        trip.clear()
        trip.update(confirmed)
        # And the panels hear about it now, not at the end of the turn.
        #
        # They are bound to `$/trip/...`, so this is one `updateDataModel` and
        # no model call — the same messages the end of the turn sends. Sending
        # them only there meant a traveller who pressed a fare watched the
        # sidebar say nothing about it for as long as the answering turn took,
        # twenty seconds and more.
        #
        # Which is as early as *this* can be, and not as early as a press can
        # be answered: what reaches here is what `confirm` could settle from
        # the press, and the value itself only lands on the trip once something
        # records it. `host_actions.HANDLERS` records exactly one press —
        # `drop_activity` — so a pressed fare waits for the model to call
        # `save_trip`, and the panel moves when that returns: measured at 4.4s,
        # down from 20.8s when the panel was redrawn rather than bound.
        #
        # That 4.4s is chosen, not left over. Recording `select_flight` here
        # would make it a frame, and the price is Python knowing which field a
        # fare press sets and which hop it belongs to — a second thing that
        # writes decisions, disagreeing with `save_trip` the first time a press
        # means something new. One writer is worth the round trip.
        for event in panels():
            yield event

    def save(patch: dict[str, Any]) -> None:
        # `merge` rather than `update`, because one field does not simply
        # overwrite: a patch naming `assumed` is talking about its own fields,
        # and a later patch stating one of them for real has to clear that mark.
        nxt = model.merge(trip, patch)
        trip.clear()
        trip.update(nxt)

    tool_context = ToolContext(trip=trip, provider=provider, save=save, today=today)

    # Pressing something *is* the traveller's turn, so it enters the
    # conversation as one. Typing wins when both arrive: someone can type while
    # a surface is on screen, and then what they said is the turn — the
    # action's values still reached the trip above, which had to happen either
    # way.
    lines = [
        request.message
        or (describe_action(request.action, leg_index) if request.action else PANEL_REQUEST)
    ]
    if refused:
        # Said in the turn rather than left for the model to discover, because
        # it will not: the trip it reads back is simply the old one, and nothing
        # in it says a value was turned away.
        lines.append(
            f"[interface] Refused, and not saved: {' '.join(refused)} "
            "Say so plainly and ask for it again, keeping everything else they set."
        )
    opening = "\n\n".join(line for line in lines if line)

    previous_interaction_id = request.interaction_id

    yield {
        "type": "start",
        "model": request.model,
        "skill": request.skill,
        "surfaceId": request.surface_id,
    }

    # What the turn spent its time on.
    #
    # "The interface does not appear quickly enough" was not answerable before
    # this: there was no number anywhere for how long anything took, so the only
    # way to discuss it was to describe the feeling. The marks below are the
    # three that decide that feeling — when the first word arrives, when the
    # first *pixel* of interface arrives, and how long each lookup took — and
    # they go out on the wire so a slow turn can be read off rather than
    # reproduced.
    #
    # `perf_counter` rather than wall-clock: this measures a duration, and a
    # clock that can be stepped by NTP mid-turn produces negative ones.
    began = time.perf_counter()
    marks: dict[str, float] = {}

    #: A mark worth telling the client about before the turn is over.
    #:
    #: The marks used to go out once, in a `timing` event just before `done`, so
    #: "Interface in 5.4 s" appeared *after* the whole turn had finished — which
    #: on a planning turn is half a minute after the interface it is talking
    #: about. The client already renders the figure without a total when it has
    #: no total yet; it simply had nothing to render until the end.
    unreported_marks = False

    def mark(name: str) -> None:
        """Records the first time something happened, in milliseconds."""
        nonlocal unreported_marks
        if name not in marks:
            marks[name] = round((time.perf_counter() - began) * 1000, 1)
            if name == "firstSurface":
                unreported_marks = True

    def timing() -> list[dict[str, Any]]:
        """A `timing` event, when there is a mark the client has not been told."""
        nonlocal unreported_marks
        if not unreported_marks:
            return []
        unreported_marks = False
        return [{"type": "timing", "ms": dict(marks)}]

    # The prompt in two halves, and only one of them goes on the wire.
    #
    # The prompt is still split in two, and the split still earns its keep: the
    # volatile half — the surface to draw into, the trip so far — has to ride in
    # with the message anyway, because a model told ten turns ago to draw into
    # `inline-1` would still be drawing into `inline-1`.
    #
    # What changed is that the stable half is now sent every turn, resumed or
    # not. It used to be sent only when a conversation started, on the reasoning
    # that `previous_interaction_id` carries the prior context on Google's side
    # — measured at the time as 44 input tokens for a follow-up instead of
    # 5,411, with `total_cached_tokens` at 0 throughout.
    #
    # That measured the bill and not the behaviour, and the behaviour was that
    # the model stopped drawing. Measured on the opening turn, four warmed turns
    # in four drew no surface at all — four and five rounds of tool calls and
    # nothing on screen — against four cold turns in four that drew. Re-send the
    # stable half and the same warmed turn draws three times in three. Whatever
    # the chain carries, it is not the rules: a resumed turn had no catalog, no
    # component signatures and no instruction to answer in a surface, so it did
    # the only thing left and called tools.
    #
    # The saving it was after has since arrived for free. The same turns now
    # report 32,184 cached of 40,135 input — implicit caching covers the stable
    # half, so correctness costs nothing here. Warming is still worth doing; it
    # starts the conversation, not the rulebook.
    stable, volatile = build_prompt_parts(
        variant=request.skill,
        surface=request.surface,
        surface_id=request.surface_id,
        catalog_id=CATALOG_ID,
        trip=trip,
        today=today,
        # Against the trip as it stands *after* the press was committed, which is
        # the point: the press is what moved the shape, and this turn is the one
        # that can draw the new row for nothing. See `panel_is_stale`.
        panel_stale=panel_is_stale(request.shape, trip),
    )

    # A conversation is bound to the setup it started with. Change the skill
    # variant mid-conversation and the stable half is different — so the chain
    # is broken deliberately and the new setup is sent, rather than continuing
    # against rules nobody is reading any more. Same idea as the contract stamp
    # a Live session binds to.
    setup = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    if request.setup and request.setup != setup:
        previous_interaction_id = None
    system: str | None = stable

    # This turn's own history, and why the turn carries it rather than the API.
    #
    # The Interactions API is stateful: answer a round by posting the function
    # results with `previous_interaction_id` set to the interaction that asked
    # for them, and the server supplies everything before it. That is what this
    # loop used to do, and measured over fourteen continuation rounds it did
    # not hold. An interaction's id has two halves — the conversation it
    # belongs to and its own — and in six of those fourteen the reply came back
    # rooted at *itself*: a brand-new conversation, the previous one silently
    # dropped. Two things follow from that, and both were reported as bugs in
    # this app. The model answers the next round having forgotten the trip, so
    # it draws the opening form again at a traveller who settled their dates
    # three rounds ago — "it asks me things I already told it". And a later
    # round, answering a call the server no longer believes it made, dies on
    # "please ensure that function response turn comes immediately after a
    # function call turn", which is the 400 that ended one stays turn in three.
    #
    # It is not a race: a 350ms settle before each continuation round made it
    # worse, not better (eight breaks in thirteen). It is not the system
    # instruction either — sending that only on the first round took the drawn
    # surfaces from five in eight to three.
    #
    # So the turn stops depending on it. Every round sends the whole turn so
    # far — the traveller's message, each call the model made, each result that
    # came back — and `previous_interaction_id` is left pointing at the *last
    # turn*, the one place server-side state is still worth having and the one
    # place a break costs only prior context rather than the turn in hand.
    # A replayed call has to carry its signature, which is why `ToolCall` keeps
    # one.
    history: list[dict[str, Any]] = [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": f"{volatile}\n\n---\n\n{opening}"}],
        }
    ]
    turn_input: list[dict[str, Any]] = list(history)
    #: The interaction to resume this conversation from, next turn.
    last_interaction_id: str | None = previous_interaction_id

    stop_reason: str | None = None
    # A compile failure the model has not been told about yet. Until this
    # existed, Express that did not compile ended the turn with a broken
    # surface and the model none the wiser: it had written something wrong and
    # nothing ever said so.
    unreported: dict[str, str] | None = None
    retried_compile = False
    #: A fenced block the model wrote instead of an `<a2ui>` one.
    #:
    #: Same failure as a compile error, one step earlier: the model meant to
    #: draw and reached for a notation that does not exist. The difference is
    #: that a compile error was caught and this reached the screen — two hundred
    #: lines of JSON where an interface should have been.
    misdrawn: str | None = None
    retried_notation = False
    #: Everything this turn has said, and whether it has done anything.
    #:
    #: A turn that announces an intention and then ends is the failure both
    #: doors share and neither brief stops. Measured on the typed one: a
    #: multi-city opening answered "Let me record your multi-city route and get
    #: your travel dates" with nothing drawn in four runs of five.
    spoken = ""
    did_something = False
    #: A surface actually reached the screen this turn.
    #:
    #: Distinct from `did_something`, which is also true when a tool ran.
    #: Told apart because a message that says "what it drew is below" has to
    #: be about something that is, in fact, below: a turn that called
    #: `save_trip` and then lost the stream set `did_something` and drew
    #: nothing, and said so to a traveller looking at an empty space.
    drew_surface = False
    #: A tool has actually run this turn, so the model owes the API a response.
    #:
    #: Separate from `result.tool_calls`, which is only what the model *asked*
    #: for and is discarded harmlessly when a stream drops. This is the effect:
    #: once `run_tool` has been called, the conversation on Google's side holds
    #: a function call waiting on its response, and restarting the round sends
    #: a fresh turn instead — which the API refuses with "please ensure that
    #: function response turn comes immediately after a function call turn".
    #: Seen exactly that way: search_hotels, save_trip, restart, 400.
    dispatched_a_tool = False
    #: Everything the model wrote this turn, blocks included.
    #:
    #: The split stream deliberately does not carry this: `Text` is the prose
    #: with the Express taken out, and `Ui` is the Express after it compiled. For
    #: a standing surface the *source* is what is worth keeping — `panel =
    #: Trip("Your trip to Madrid")` re-renders against whatever the trip says
    #: next, where the messages it compiled to are a snapshot of the record at
    #: the moment it was written. See `panel_composition`.
    raw: list[str] = []
    retried_promise = False
    #: A surface that drew but left the traveller nothing to answer.
    thin: str | None = None
    retried_thin = False

        #: This turn's blocks on the answering surface, and the paths they ask
    #: about. Both span the turn rather than the block, because a turn that
    #: writes two blocks still owes the traveller one surface and one
    #: button that sends all of it. See `stack_blocks`.
    #:
    #: **Outside the round loop**, which is where the comment above always
    #: said they were and where they were not. Declared per round, every
    #: round started at block zero — so two cards drawn in different
    #: rounds each called their top component `root` and the second
    #: replaced the first. That is the highlights card a planning turn
    #: drew and then lost to the itinerary: `get_destination` and
    #: `save_trip` are two rounds, so nothing composed them.
    blocks: dict[str, Any] = {}
    carried: dict[str, dict[str, None]] = {}
    #: Which slot the next block to land on this turn's surface takes.
    #:
    #: Shared between the agent's blocks and the host's macro draws,
    #: because they land on the same surface and the renderer draws
    #: whichever component is called `root`. Two of them means the second
    #: replaces the first, which is what `stack_blocks` exists to stop —
    #: and the host's two draws were not going through it.
    #:
    #: Seen as a planning turn: `get_destination` pre-drew "Worth your time
    #: in Madrid" as five components, then the `Itinerary` the same turn
    #: asked for landed on the same surface as thirty-eight, and the first
    #: card was simply gone. Not a skeleton filling in — a different card,
    #: replaced wholesale, which reads as the interface changing its mind.
    #: Only the host's own macro draws are counted here. The agent's blocks
    #: keep using the index the stream gives them.
    #:
    #: Sharing one counter between the two was wrong, and measurably: a turn
    #: where the agent asks for a pre-draw *and* writes its own block for the
    #: same thing then drew the flight list twice, once as `rows__*` and again
    #: as `b1_fares__*`. The pre-draw is provisional — it exists so the card is
    #: up while the lookup runs — and the agent's block is the real one, so it
    #: is *meant* to take the same slot and replace it.
    #:
    #: Two host macros in one turn are the opposite: a `Highlights` from
    #: `get_destination` and an `Itinerary` from `save_trip` are two different
    #: cards, and the second replacing the first is what made a planning turn
    #: show a short card and then lose it to a long one.
    #: The highest block slot anything has taken on this turn's surface.
    highest_slot = -1

    def took(slot: int) -> int:
        nonlocal highest_slot
        highest_slot = max(highest_slot, slot)
        return slot

    def provisional_slot() -> int:
        """Slot zero, for the card drawn while a lookup runs.

        Always zero, because the agent's own first block takes zero too and is
        *meant* to replace this: the pre-draw exists so something is on screen
        during the lookup, and the agent's block is the real card.

        Sharing one counter between the two was wrong, and measurably — a turn
        that asked for a pre-draw and then wrote its own block for the same
        fares drew the list twice, once as `rows__*` and again as
        `b1_fares__*`.
        """
        return took(0)

    def next_slot() -> int:
        """A slot after everything already drawn, for a card of its own.

        For the closing draw, which is a *different* card rather than a better
        version of one: a `Highlights` from `get_destination` and an
        `Itinerary` from `save_trip` are two things, and the second replacing
        the first is what made a planning turn show a short card and lose it to
        a long one.
        """
        return took(highest_slot + 1 if highest_slot >= 0 else 0)

    for round_index in range(MAX_TOOL_ROUNDS):
        # A fresh splitter per round: each round is its own stream of prose and
        # Express, and a block left open at the end of one is not continued by
        # the next.
        # What the trip is waiting on, so a surface that asks for none of it is
        # caught before the traveller is left looking at one.
        #
        # `priceFlights` is the goal because it is the first thing every trip is
        # blocked on and its requirements are the boundaries — route, dates,
        # party. Once those are set this is empty and the check does not run,
        # which is right: a flight list answers a question rather than posing
        # one.
        # The airports this provider actually flies, for the pickers `Ask()`
        # draws. Fetched once per turn rather than per macro: both are
        # catalogue calls, and `ChoicePicker.options` is static in the schema,
        # so the choices have to be in hand when the macro expands.
        try:
            where_to = await provider.destinations()
            airports = airport_choices(await provider.origins(), where_to)
            # Off the same list, so the panel says "€69" rather than "69"
            # without a second call to find out which currency that is.
            currency = currency_for(where_to, trip)
            # Kept on the record, because the finishing passes need it and do
            # not have the destination list this was read from. `money_rows`
            # totals in numbers and files the code beside them, so a panel can
            # bind `formatCurrency($/money/total, $/money/currency)` without a
            # model having to infer a currency from a city name — which is how
            # a trip priced in euros gets a total in dollars.
            if currency:
                trip["currency"] = currency
        except Exception:  # noqa: BLE001 - a picker nobody can fill is not a dead turn
            airports, currency = {}, "USD"

        stream = ExpressStream(
            parser=parser_for(request.surface_id),
            components=COMPONENT_NAMES,
            validator=VALIDATOR,
            required=REQUIRED_PROPERTIES,
            airports=airports,
            currency=currency,
            # And a party asked per hop has to be asked of every hop: a route
            # of three asked about twice is a hop flying home with a party
            # nobody confirmed. See `half_asked`.
            hops=_party_paths(trip),
            # What `Itinerary()` expands into: the days this turn recorded.
            trip=trip,
        )

        # Fenced blocks never reach the transcript. This agent answers in
        # interfaces and in a sentence or two of prose; a code fence is neither,
        # so it is always a mistake, and the only question is whether it is one
        # worth telling the model about.
        gate = FenceGate()
        def rendered(events: Sequence[Any], source: str) -> list[dict[str, Any]]:
            """Splitter events, as events for the browser."""
            nonlocal unreported, misdrawn, spoken, did_something, thin, drew_surface
            out: list[dict[str, Any]] = []
            for event in events:
                if isinstance(event, Text):
                    said, fenced = gate.feed(event.delta)
                    for block in fenced:
                        if block.looks_like_a_surface and misdrawn is None:
                            misdrawn = block.source
                    if not said:
                        continue
                    spoken += said
                    mark("firstWord")
                    out.append({"type": "text", "delta": said, "round": round_index})
                elif isinstance(event, Ui):
                    did_something = True
                    drew_surface = True
                    # Drawn either way. A surface that asks for none of what the
                    # trip is waiting on is unhelpful, not invalid, and putting
                    # nothing on screen instead is worse for the traveller than
                    # putting the wrong thing there.
                    if event.incomplete and thin is None:
                        thin = event.incomplete
                    # The number that matters. Everything before this is a blank
                    # space where an interface should be.
                    mark("firstSurface")
                    out.append(
                        {
                            "type": "ui",
                            "surfaceId": request.surface_id,
                            # A block that names another surface is readdressed
                            # to this turn's card before anything else looks at
                            # it — a turn draws its own card and never over a
                            # spent one. See `on_its_own_surface`.
                            #
                            # Then two blocks in one turn compose onto that one
                            # surface instead of the second replacing the first,
                            # and `carried` makes the one button carry what both
                            # asked. See `stack_blocks`.
                            "messages": finish(
                                stack_blocks(
                                    on_its_own_surface(
                                        event.messages, request.surface_id
                                    ),
                                    request.surface_id,
                                    took(event.block_index),
                                    blocks,
                                ),
                                trip,
                                carried=carried,
                            ),
                            "done": event.done,
                        }
                    )
                elif isinstance(event, Failed):
                    unreported = {"message": event.message, "express": event.source}
                    out.append(
                        {
                            "type": "ui_error",
                            "message": event.message,
                            "source": source,
                            "express": event.source,
                        }
                    )
            return out

        result = None
        failure: Exception | None = None
        try:
            # Yielded straight through rather than collected: this generator
            # feeds an SSE response, so a delta that reaches here reaches the
            # browser. Buffering the round and emitting at the end would paint
            # the surface only once the model had stopped typing, which is the
            # thing the streaming exists to avoid.
            async for event in stream_interaction(
                api_key=request.api_key,
                model=request.model,
                input=turn_input,
                tools=[*gemini_tools(), *grounding_tools()],
                system_instruction=system,
                thinking_level=request.effort,
                previous_interaction_id=previous_interaction_id,
                fallback_model=FALLBACK_MODEL,
                # So a dropped stream can be restarted while the screen is
                # still empty. `drew_surface` and not `did_something`: the
                # latter is also true once a tool has run, and the opening
                # turn calls `save_trip` before it draws anything — so on the
                # commonest turn in the app, the restart was refused every
                # time, by a flag that was never about the screen. Replaying
                # a tool is still guarded, by `result.tool_calls` in
                # `_standby`, which is about *this* round rather than the
                # whole turn.
                # Not only "is there a surface": "would starting this round
                # again break something". A drawn surface would be drawn twice;
                # a dispatched tool has left the API waiting for a response that
                # a restarted round never sends. Neither is recoverable, and
                # neither is `result.tool_calls`, which is a request the drop
                # threw away with the rest of the turn.
                has_drawn=lambda: drew_surface or dispatched_a_tool,
                client=request.client,
            ):
                if event["type"] == "text":
                    raw.append(event["delta"])
                    for out in rendered(stream.push(event["delta"]), "stream"):
                        yield out
                    # The interface is on screen; say how long it took now
                    # rather than when the whole turn is over. See `timing`.
                    for out in timing():
                        yield out
                elif event["type"] == "restart":
                    # The model dropped the stream mid-sentence and the turn is
                    # starting again on the standby. What it said belongs to the
                    # abandoned attempt: the client drops it, and so do we — a
                    # splitter still holding half a sentence would glue it to
                    # the front of the new one.
                    stream = ExpressStream(
                        parser=parser_for(request.surface_id),
                        components=COMPONENT_NAMES,
                        validator=VALIDATOR,
                        trip=trip,
                        required=REQUIRED_PROPERTIES,
                        airports=airports,
                        currency=currency,
                                )
                    gate = FenceGate()
                    spoken = ""
                    yield event
                elif event["type"] == "served_by":
                    # Said rather than hidden. The traveller asked for one model
                    # and a different one is answering; a demo that quietly
                    # swaps the thing it is demonstrating is a demo that lies.
                    yield event
                elif event["type"] == "result":
                    result = event["result"]
        except Exception as error:  # noqa: BLE001 - every failure gets a sentence
            failure = error

        # Flushed even on failure: a block that compiled before the stream died
        # is a surface the traveller can still use, and throwing it away to
        # show an error banner is a worse turn than showing both.
        for out in rendered(stream.end(), "final"):
            yield out
        for out in timing():
            yield out

        if failure is not None:
            reported = describe_api_error(failure)
            # Two very different turns end here, and they were reported
            # identically. One drew nothing: the screen is empty and the model
            # being busy is the whole story. The other drew a surface and then
            # lost the stream — the form is on screen, filled in and usable,
            # and "gemini is experiencing high demand" over the top of it reads
            # as though the form is broken. It is not, and the traveller's next
            # move is to use it.
            if drew_surface and reported.get("retryable"):
                reported = {
                    **reported,
                    "message": (
                        "The model dropped out part-way through this turn — "
                        "what it had already drawn is below and still works. "
                        f"Answer it to carry on. ({reported.get('message', '')})"
                    ),
                }
            yield reported
            break
        if result is None:
            yield {
                "type": "error",
                "message": "The model stream ended without a result.",
                "retryable": True,
            }
            break

        # Deliberately *not* `previous_interaction_id = result.interaction_id`.
        # The chain this turn walks is carried in `history` instead; see the
        # note on it. What the round's id is good for is the resume point the
        # client gets at the end, because the last round's interaction holds
        # the whole turn.
        last_interaction_id = result.interaction_id or last_interaction_id
        stop_reason = result.status

        yield {"type": "usage", **result.usage.as_dict()}

        # Nothing left to do but a surface that did not compile: hand the error
        # back and let it write the block again. Once — a model that cannot fix
        # it on the second attempt will not fix it on the fifth, and the
        # traveller is waiting.
        # An unclosed fence is still a fence: a turn that stopped mid-block
        # should not spill the half of it that arrived.
        tail, trailing = gate.flush()
        if tail:
            yield {"type": "text", "delta": tail, "round": round_index}
        for block in trailing:
            if block.looks_like_a_surface and misdrawn is None:
                misdrawn = block.source

        # A surface written in a notation that does not exist. The model is
        # told once, the same way a compile error tells it, because a model
        # that reaches for the wrong notation twice will reach for it a third
        # time and the traveller is waiting.
        if not result.tool_calls and misdrawn and not retried_notation:
            retried_notation = True
            block, misdrawn = misdrawn, None
            yield {"type": "retry", "reason": "the surface was not written in Express"}
            history.append(
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "That was a fenced code block, so nothing was drawn and "
                                "the traveler saw nothing.\n\nThere is one way to draw "
                                "here and it is an `<a2ui>` block of A2UI Express — named "
                                "lines, one component each, ending in `root = ...`, using "
                                "only components this catalog defines. JSON is not it: no "
                                "`call`, no `props`, no component types you invented.\n\n"
                                "What you wrote was:\n\n"
                                f"{block[:2000]}\n\n"
                                "Write it again as Express. Do not repeat the prose — only "
                                "the <a2ui> block."
                            ),
                        }
                    ],
                }
            )
            turn_input = list(history)
            continue

        if not result.tool_calls and unreported and not retried_compile:
            retried_compile = True
            failure = unreported
            unreported = None
            yield {"type": "retry", "reason": failure["message"]}
            history.append(
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "That A2UI block did not compile, so nothing was drawn and "
                                "the traveler is looking at prose with a gap in it.\n\n"
                                f"{failure['message']}\n\nThe block was:\n\n"
                                f"{failure['express'][:4000]}\n\n"
                                "Write the whole block again, corrected. Do not repeat the "
                                "prose — only the <a2ui> block."
                            ),
                        }
                    ],
                }
            )
            turn_input = list(history)
            continue

        # Drew, but left nothing to answer. Ask for the controls, once.
        #
        # The surface is already on screen, so this is a replacement rather than
        # a rescue, and it is worth exactly one round: a second dashboard is a
        # traveller watching the same nothing twice.
        if not result.tool_calls and thin and not retried_thin:
            retried_thin = True
            complaint, thin = thin, None
            yield {"type": "retry", "reason": "the surface asks for nothing"}
            history.append(
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{complaint}\n\nDraw it again into the same surface, "
                                "with those controls on it. Only the <a2ui> block."
                            ),
                        }
                    ],
                }
            )
            turn_input = list(history)
            continue

        # A turn that said what it was about to do, and did not do it.
        #
        # Last of the three retries, deliberately: a compile failure and a
        # fenced block are both *attempts* at a surface and worth correcting
        # first. This one fires when there was no attempt at all — the traveller
        # has a sentence and an empty space.
        #
        # **`drew_surface`, not `did_something`.** The guard used to be "no tool
        # ran", and the commonest way to fail this is to run one: the opening
        # turn records the route with `save_trip`, says "Let me get those
        # details set up for your trip to Berlin", and stops. A tool ran, so
        # `did_something` was true, so the nudge never fired — and the panel
        # quietly filling in on the right is not an answer to somebody who
        # asked for flights. Seen on both 0.9.0 and 0.10.0, in the journey
        # validator and in the browser, roughly half the openings.
        #
        # Saving a trip is not drawing. `drew_surface` is the flag that means a
        # surface actually reached the screen, which is the thing being
        # promised.
        #
        # Once. A model that answers the nudge with another promise will answer
        # the third one the same way, and the traveller is waiting.
        if (
            not result.tool_calls
            and not drew_surface
            and promised(spoken)
            and not retried_promise
        ):
            retried_promise = True
            yield {"type": "retry", "reason": "the turn promised and drew nothing"}
            history.append(
                {"type": "user_input", "content": [{"type": "text", "text": TYPED_NUDGE}]}
            )
            turn_input = list(history)
            continue

        if not result.tool_calls:
            break

        did_something = True

        # Every call this round answered in one go: the next request carries all
        # of their results, which is what keeps the model calling tools in
        # parallel rather than learning to ask one at a time.
        results: list[dict[str, Any]] = []
        for call in result.tool_calls:
            yield {"type": "tool", "name": call.name, "input": call.args, "status": "running"}

            # Draw the shape of the answer before going to look for it. Only on
            # the surface this turn is answering: a standing panel is not what
            # the traveller just asked a question about.
            # What the agent asked to have on screen while this runs.
            #
            # It says so in the call — `draw: {heading, selected, hop}` — and the
            # host expands the macro those arguments name. That is one act
            # rather than two, which is the whole reason it is here: a turn
            # answering a press records the decision and searches in the same
            # round, so there is no gap to emit a separate block into, and two
            # prompt rewrites could not make one. The agent still decides
            # whether there is a list, what is above it and where the choice
            # lands; `opening_express` says what the host does and does not
            # contribute.
            seeded = False
            opening = opening_express(call.name, call.args.get("draw"), request.surface_id)
            if opening:
                try:
                    # `finish`, like every other surface. A host-drawn card
                    # went out raw — no `seed_surface_trip` — so a control on
                    # it opened empty over a trip that knew the answer. See
                    # `seed_surface_trip`.
                    drawn_now = finish(
                        # Through `stack_blocks`, like the agent's own blocks.
                        # A macro the host expands still lands on this turn's
                        # surface and still defines a `root`, so without this
                        # it replaces whatever is already there instead of
                        # composing with it.
                        stack_blocks(
                            as_wire(
                                expand_macros(
                                    parser_for(request.surface_id).compile(
                                        opening, is_final=True
                                    ),
                                    trip,
                                    airports,
                                    currency,
                                )
                            ),
                            request.surface_id,
                            provisional_slot(),
                            blocks,
                        ),
                        trip,
                        carried=carried,
                    )
                except Exception as why:  # noqa: BLE001 - a bad `draw` must not cost the turn
                    # Said out loud. Swallowed in silence, a card the agent
                    # asked for simply was not there, and the only way anyone
                    # found out was a validator reporting "nothing to press".
                    print(f"draw failed for {call.name}: {why!r}", flush=True)
                    drawn_now = []
                if drawn_now:
                    mark("firstSurface")
                    # Counts as a surface on the screen, because it is one.
                    # The promise nudge reads this flag, and a turn whose card
                    # the *host* drew from `draw:` has answered the traveller
                    # as surely as one that wrote the block itself.
                    drew_surface = True
                    yield {
                        "type": "ui",
                        "surfaceId": request.surface_id,
                        "messages": drawn_now,
                        "done": False,
                    }
                    # Blank rows, if the agent asked for blank rows.
                    #
                    # `seed_rows` used to file three of these at every lookup,
                    # whether anybody wanted them or not. That was the host
                    # inventing rows no lookup had returned and choosing how
                    # many — data rather than components, so it composed
                    # nothing, but still the host's opinion about what should
                    # be on screen.
                    #
                    # `draw: {placeholders: n}` makes it the agent's. It knows
                    # whether its own block has a list in it, and a lookup
                    # whose result is not a list gets none.
                    placeholders = placeholder_rows(
                        call.name,
                        (call.args.get("draw") or {}).get("placeholders")
                        if isinstance(call.args.get("draw"), dict)
                        else None,
                        request.surface_id,
                        PROTOCOL_VERSION,
                    )
                    if placeholders:
                        seeded = True
                        yield {
                            "type": "ui",
                            "surfaceId": request.surface_id,
                            "messages": placeholders,
                            "done": False,
                        }

            tool_began = time.perf_counter()
            dispatched_a_tool = True
            before_tool = json.dumps(trip, sort_keys=True, default=str)
            output, is_error = await run_tool(call.name, call.args, tool_context)
            marks[f"tool:{call.name}"] = round((time.perf_counter() - tool_began) * 1000, 1)
            yield {
                "type": "tool_result",
                "name": call.name,
                "result": output,
                "isError": is_error,
            }

            # A tool that moved the trip — `save_trip`, a release — reaches the
            # panels straight away, for the same reason as the press above: the
            # record is what they draw, and they were waiting for the whole
            # turn to end before hearing that it had changed.
            if json.dumps(trip, sort_keys=True, default=str) != before_tool:
                for event in panels():
                    yield event

            # The rows, filed where the brief says they land. One
            # `updateDataModel` and no components: a card bound to this path
            # fills in, and one drawn after the fact finds the rows already
            # there. See `brain/macros.py`, which holds both the address and
            # the `Flights()` macro that reads it.
            drawn: dict[str, Any] | None = None
            on_screen = ""
            rows = (
                file_rows(call.name, output, request.surface_id, PROTOCOL_VERSION)
                if not is_error
                else []
            )
            if rows:
                yield {
                    "type": "ui",
                    "surfaceId": request.surface_id,
                    "messages": rows,
                    "done": False,
                }
                drawn = {
                    "surfaceId": request.surface_id,
                    "path": landing_for(call.name),
                    "rows": len(rows_in(call.name, output) or []),
                }
            elif seeded:
                # Nothing to file, and rows on screen saying otherwise.
                # Whether the lookup refused or errored is the same to them,
                # and rows that went up seconds ago on the promise of a result
                # are nothing anybody is reading.
                yield {
                    "type": "ui",
                    "surfaceId": request.surface_id,
                    "messages": clear_placeholders(
                        call.name, request.surface_id, PROTOCOL_VERSION
                    ),
                    "done": False,
                }

            if not is_error:
                # And the card for a write, which could not be drawn before it.
                #
                # `Itinerary()` reads the trip rather than a path, so at
                # dispatch it would have said "no day plan recorded yet" — the
                # days are still in the arguments. Drawn here it reads the trip
                # the call just wrote.
                #
                # This buys a round, not a head start. A planning turn used to
                # spend 20.6s writing the plan into `save_trip` and then 16.7s
                # more — 1,158 thought tokens — on a further round whose whole
                # output was `Itinerary()` and one sentence. The macro was
                # already doing its job; the round was the cost.
                closing = closing_express(
                    call.name, call.args.get("draw"), request.surface_id
                )
                if closing:
                    try:
                        # `finish`, for the same reason as the pre-draw
                        # above: this is the path that draws `Ask()` from
                        # `save_trip`, which is the opening form, and it was
                        # going out unseeded — so the form asked for what had
                        # just been said in the same sentence.
                        after = finish(
                            # Likewise. This is the path that turned a
                            # highlights card into a seven-day itinerary by
                            # replacing it.
                            stack_blocks(
                                as_wire(
                                    expand_macros(
                                        parser_for(request.surface_id).compile(
                                            closing, is_final=True
                                        ),
                                        trip,
                                        airports,
                                        currency,
                                    )
                                ),
                                request.surface_id,
                                next_slot(),
                                blocks,
                            ),
                            trip,
                            carried=carried,
                        )
                    except Exception as why:  # noqa: BLE001 - a bad `draw` must not cost the turn
                        print(f"draw failed after {call.name}: {why!r}", flush=True)
                        after = []
                    if after:
                        mark("firstSurface")
                        drew_surface = True
                        for out in timing():
                            yield out
                        yield {
                            "type": "ui",
                            "surfaceId": request.surface_id,
                            "messages": after,
                            "done": False,
                        }
                        on_screen = closing

            # Where the rows are, not what they say.
            #
            # This note used to read "Do not draw this surface again", because
            # the host had drawn the cards itself and a block from the model
            # landed over them and blanked the list. Telling the agent the
            # address instead fixes the same collision from the other side: its
            # tree points at the rows the host filed, and the cards are its own.
            #
            # And now the rows go with it. Telling the agent not to re-type four
            # fares while handing it the four fares was asking it to ignore the
            # largest thing in its context — so they are withheld instead, and
            # this sentence is what it gets in their place. See
            # `without_the_rows`.
            #
            # Only when they were filed, which `drawn` is exactly the test for.
            # Withholding rows that never reached the data model would leave
            # nobody holding them: the macro has nothing to bind to and the
            # agent has nothing to fall back on. Filed or handed over, never
            # neither.
            reads_them = (
                f"They are in the data model of surface {drawn['surfaceId']} at "
                f"{drawn['path']}; draw them with "
                f"`{'Flights' if drawn['path'] == '/flights' else 'Stays'}()`, one "
                "macro bound to them."
                if drawn
                else ""
            )
            summarized = without_the_rows(call.name, output, reads_them) if drawn else output
            payload: dict[str, Any] = (
                dict(summarized) if isinstance(summarized, dict) else {"result": summarized}
            )
            if drawn:
                payload["rowsOnScreen"] = drawn
            if on_screen:
                # The card is up. Saying so is the point of drawing it here: the
                # round this saves is the one the agent would otherwise spend
                # deciding to draw what it has already asked for, and an agent
                # that draws it again replaces an identical card and pays for
                # the round anyway.
                payload["onScreen"] = {
                    "surfaceId": request.surface_id,
                    "note": (
                        "Already drawn on that surface, from the heading you sent: "
                        f"`{on_screen.splitlines()[1].split(' = ', 1)[-1]}`. "
                        "Do not draw it again — say your one sentence and end the turn."
                    ),
                }

            results.append(
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                }
            )

        # A block that did not compile, in a round that also called tools.
        #
        # The repair branch above only runs when the model has stopped calling
        # tools, so a round that drew something broken *and* looked something up
        # — the common shape of a first turn, which saves the trip before it
        # draws — went back to the model with the tool results and not a word
        # about the surface. The traveller got a turn with a gap in it and the
        # model never found out.
        #
        # This used to be smuggled in as another `function_result`, named
        # `render_a2ui_express` with a `call_id` of `compile-<round>`. Both were
        # fictions: the model never made that call, and no door has offered that
        # tool since the MCP handler was removed. A result answering a call that
        # was never placed is not a channel, it is a message in a bottle, and
        # "the retries are weak" is what that looks like from the outside.
        #
        # It goes as a user turn instead, after the results, which is the same
        # way every other correction in this file reaches the model.
        repair: list[dict[str, Any]] = []
        if unreported and not retried_compile:
            retried_compile = True
            yield {"type": "retry", "reason": unreported["message"]}
            repair = [
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Your A2UI block did not compile, so nothing was drawn "
                                "and the traveler is looking at a gap.\n\n"
                                f"{unreported['message']}\n\nThe block was:\n\n"
                                f"{unreported['express'][:4000]}\n\n"
                                "Answer the lookups above, then write the whole block "
                                "again, corrected. Do not repeat the prose — only the "
                                "<a2ui> block."
                            ),
                        }
                    ],
                }
            ]
            unreported = None

        # The round, both halves of it: what the model asked for and what came
        # back. The calls have to go in — a result on its own is what the API
        # refuses once it has lost the interaction that asked. The model's own
        # prose does not: a replayed `model_output` step is rejected outright,
        # so what it said this turn is on screen and not in the history.
        history.extend(call.replayable() for call in result.tool_calls)
        history.extend(results)
        history.extend(repair)
        turn_input = list(history)
        yield {"type": "trip", "trip": dict(trip), "shape": model.decision_shape(trip)}

        if round_index == MAX_TOOL_ROUNDS - 1:
            yield {
                "type": "error",
                "message": f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.",
                "retryable": True,
            }

    # The decisions' shape travels with the trip.
    #
    # The panel is redrawn when the trip's *decisions* change — a new control is
    # needed, not just a new value — and that judgement is the trip model's, so
    # it has to reach the client as a fact rather than as a rule the client
    # reimplements. It rides the trip event because that event arrives while the
    # turn is still streaming: the rebuild below happens in the tail, after the
    # answer, and a traveller who presses a fare the moment it appears cancels
    # the stream and the rebuild with it. The client compares this against the
    # shape its panel was drawn for and asks for a redraw on a request of its
    # own — which no press can cancel. Without it the panel was permanently one
    # press behind: nothing until a flight was chosen, then nothing again until
    # a hotel was.
    yield {"type": "trip", "trip": dict(trip), "shape": model.decision_shape(trip)}

    # The panels outlive the turn that drew them, so the trip reaches them as
    # ordinary A2UI rather than as something the client works out for itself.
    # Shared with the voice relay, which does the same thing at the end of its
    # own turns — see `panel_events`.
    for event in panels():
        yield event

    # The receipt, handed over *before* the panels rather than after them.
    #
    # It used to be yielded once, at the very end of this generator — after the
    # second model call that rebuilds the sidebar. Everything that remembers the
    # trip hangs off it: the client keeps it and sends it back, and the door
    # writes the session from it. So a traveller who pressed a fare the moment
    # it appeared — which is the entire point of drawing the fares the moment
    # they land — aborted the stream before either copy was written, and the
    # next turn began with an empty trip. The agent then asked for the route,
    # the dates and the party again, which is exactly what it should do when it
    # has been handed a trip with nothing in it.
    #
    # Measured on the real client: pressing the first fare six seconds after it
    # drew sent `resume.trip: null`, and the turn after it was a boundaries
    # form. The answer is settled here; the panels are decoration that follows.
    # What the agent addressed to a standing panel this turn, if anything.
    #
    # Computed here rather than at the end because both results carry it, and
    # because the shape below is only allowed to move when this says a panel
    # was actually written.
    composed = panel_composition("".join(raw), STANDING_SURFACES)

    yield {
        "type": "__result__",
        "result": TurnResult(
            interaction_id=last_interaction_id,
            trip=trip,
            stop_reason=stop_reason,
            shape=request.shape,
            setup=setup,
            panels=composed,
        ),
    }

    # The traveller's answer is finished here. What follows is the panels, and
    # they are not what was asked for.
    mark("answered")
    yield {"type": "done", "stopReason": stop_reason}

    shape = request.shape
    if request.surface == "inline":
        # A second model call, and it was inside the turn: `done` waited for the
        # panel to be rebuilt, so a turn whose inline card was on screen at 2.3s
        # went on saying "thinking" until 9.3s while a model redrew a sidebar
        # nobody was looking at. Measured across a flights turn, that second
        # call was most of the wall clock.
        #
        # It still happens, and still only when the panel needs *different*
        # controls — values reach it live, without a model — but it happens
        # after the turn is answered. The events are ordinary `ui` messages
        # addressed to `sidebar` and `home`, which a client applies whenever
        # they arrive.
        # No rebuild, and no fallback to one.
        #
        # The panel was redrawn by a second model call whenever a decision gave
        # it something it had no room for — 24.8 seconds, measured, between
        # pressing a fare and the sidebar moving. Letting the agent redraw it
        # in-turn instead made that possible and not reliable: it did not take
        # the instruction up, the rebuild fired every time anyway, and the
        # walkthrough grew four model turns and six thousand output tokens.
        #
        # `Trip()` draws the panel complete — every slot a decision could fill
        # already there, bound to the record, including the empty ones. So a
        # press only ever changes data, and data reaches the panel with no
        # model in the path. That is the reliable version: not a redraw that
        # usually happens, but a panel that cannot go stale.
        #
        # **Only when there is a panel.** This used to advance unconditionally,
        # which told the next turn "the panel on screen is drawn for exactly
        # these decisions" about a panel that had never been drawn at all.
        #
        # That is the whole of "the right-hand panel never updates". `shown` is
        # what `panel_is_stale` compares against, so from the first turn
        # onwards it matched the trip, the "panel is a row behind" note never
        # appeared, the agent was never asked for the sidebar block, and no
        # `Trip()` was ever written. The host then pushed `/trip/startDate` and
        # every other value to a surface with no components bound to them —
        # faithfully, every turn, onto nothing. A panel that does not exist
        # cannot be stale, so the one signal that would have said so was the
        # one being suppressed.
        if composed or request.panels:
            shape = model.decision_shape(trip)

    # The panel has never been drawn. Draw it once, here in the tail.
    #
    # `_rebuild_panels` has been in this package the whole time, exported and
    # never called: it was taken out of the turn because it fired on every
    # shape move, and a model call per press cost 24.8 seconds between
    # pressing a fare and the sidebar moving. That reasoning was about
    # *redrawing* a panel, and it still holds.
    #
    # This is the other case, and it is bounded: not once per press, once per
    # conversation, and only when there is nothing on the panel at all. It
    # runs after `done`, so the traveller's answer is already on screen and
    # this costs them no waiting — the events are ordinary `ui` messages that
    # a client applies whenever they arrive.
    #
    # Why the host asks at all, when the prompt already says to draw it on the
    # turn that first has a trip: because it does not. Measured over a
    # two-turn opening that settled a destination, a party and both dates, no
    # `surface("sidebar")` block was written either time — before the fix
    # above or after it, with the "panel is a row behind" note now reaching
    # the prompt. Two failures of the same instruction is the point at which
    # this project stops rewording it.
    #
    # The panel is still composed by the agent. What the host decides is that
    # there should be one, not what is on it.
    #
    # `request.shape` is in the condition because it is the client's receipt
    # that it *has* a panel: it is the shape its own panel was last drawn for,
    # sent back every turn. A client that reports one has something on screen
    # even when this server holds no source for it — a conversation that began
    # before the source was kept, say — and asking for a redraw there is the
    # per-shape-change rebuild all over again, which is what
    # `test_a_shape_change_costs_no_model_call_at_all` exists to catch. It
    # caught it.
    if (
        request.surface == "inline"
        and not composed
        and not request.panels
        and not request.shape
    ):
        async for event in _rebuild_panels(request, trip, today):
            if event["type"] == "__shape__":
                shape = event["shape"]
            elif event["type"] == "__panels__":
                # Kept, so the next shape move replays this source instead of
                # asking a model for it again.
                composed = {**composed, **event["panels"]}
            else:
                yield event

    mark("done")
    # Sent before `done` so a client can attach it to the turn it describes
    # rather than to whatever comes next.
    yield {"type": "timing", "ms": dict(marks)}
    print(f"turn timing {json.dumps(marks)}", flush=True)

    yield {
        "type": "__result__",
        "result": TurnResult(
            interaction_id=last_interaction_id,
            trip=trip,
            stop_reason=stop_reason,
            shape=shape,
            setup=setup,
            panels=composed,
        ),
    }


async def run_turn_collected(request: TurnRequest) -> dict[str, Any]:
    """Every event of a turn, gathered. Used by MCP, which has no stream."""
    text: list[str] = []
    ui: list[dict[str, Any]] = []
    result: TurnResult | None = None
    errors: list[str] = []

    async for event in run_turn(request):
        kind = event["type"]
        if kind == "text":
            text.append(event["delta"])
        elif kind == "ui":
            ui.extend(event["messages"])
        elif kind == "error":
            errors.append(event["message"])
        elif kind == "__result__":
            result = event["result"]

    return {
        "text": "".join(text).strip(),
        "ui": ui,
        "trip": result.trip if result else dict(request.trip),
        "interactionId": result.interaction_id if result else request.interaction_id,
        "shape": result.shape if result else request.shape,
        "setup": result.setup if result else request.setup,
        "errors": errors,
    }
