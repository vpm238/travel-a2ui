"""Components the model writes in one line and the host expands into many.

A macro is a component the catalog advertises and no renderer ever sees: the
model writes `Itinerary()`, and before the surface goes out the host replaces
that node with the day plan it already holds — four `ItineraryDay`s, twelve
`ActivityItem`s, every field filled in.

**It is here for latency, and the latency is output tokens.** The day plan is
the largest thing this agent writes, and until now it wrote it twice: once into
`save_trip({days: […]})`, because a plan that lives only on a card cannot be
shared or edited or survive the turn, and once again as components, because the
card had to be drawn. The second copy is the same data in a different notation,
and it is about eight hundred tokens the traveller waits through — measured at
25.8 seconds for the interface alone on a four-day trip.

The macro removes the second copy. The model records the days and then says
`Itinerary()`.

**Why this is not the host deciding what to draw.** The agent chooses whether
to draw an itinerary at all, when, with what heading, and beside what else. It
can still write `ItineraryDay` and `ActivityItem` by hand, and should when it
wants something this does not do — they stay in the catalog. What the macro
takes away is re-typing data the agent itself recorded one tool call ago. The
host is not choosing the content; it is the agent's own `days`, read back.

The expansion runs per turn against that turn's trip, which is what `for_trip`
carries. A macro function is a plain function to the SDK, so the trip reaches
it through a context variable rather than an argument the model could pass.
"""

from __future__ import annotations

import contextvars
from typing import Any, Optional, Sequence

from a2ui.builder.core import ComponentBuilderNode
from a2ui.builder.v0_9.catalogs.basic import ChildList, Column, Text
from a2ui.transformers.macros import MacroExpander, macro

#: The trip the current turn is expanding against.
#:
#: A `ContextVar` rather than a module global because turns run concurrently —
#: two travellers on one instance — and a global would hand one of them the
#: other's day plan. Context variables are per-task, so each turn's expansion
#: sees its own.
_TRIP: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("trip", default={})


class for_trip:
    """Expand this turn's macros against this trip."""

    def __init__(self, trip: dict[str, Any]) -> None:
        # The dict itself, not a copy: a turn mutates its trip in place as
        # tools run, and a macro has to see the `days` that `save_trip` wrote
        # a moment ago rather than the trip as it was when the turn began.
        self._trip = trip if isinstance(trip, dict) else {}
        self._token: Any = None

    def __enter__(self) -> "for_trip":
        self._token = _TRIP.set(self._trip)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._token is not None:
            _TRIP.reset(self._token)


class ActivityItem(ComponentBuilderNode):
    """One scheduled thing: a meal, a museum, a transfer, a check-in."""

    component: str = "ActivityItem"
    title: str
    time: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    duration: Optional[str] = None
    note: Optional[str] = None
    done: Optional[bool] = None
    onRemove: Optional[dict[str, Any]] = None


class ItineraryDay(ComponentBuilderNode):
    """One day of the plan, and the things in it."""

    component: str = "ItineraryDay"
    title: str
    children: ChildList
    date: Optional[str] = None
    summary: Optional[str] = None
    onAdd: Optional[dict[str, Any]] = None


def _event(name: str, context: dict[str, Any]) -> dict[str, Any]:
    return {"event": {"name": name, "context": context}}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@macro
def itinerary(heading: str = "") -> Column:
    """The day plan already recorded on this trip, drawn in full.

    Write it once in `save_trip({days: [...]})` and then draw it with this,
    rather than writing every day and every activity a second time as
    components. Pass a heading to put a line of your own above it.

    Args:
        heading: Optional line above the plan, e.g. 'Four days in Berlin'.
    """
    trip = _TRIP.get()
    days = trip.get("days")
    rows: list[Any] = []
    drew_a_day = False
    if isinstance(heading, str) and heading.strip():
        rows.append(Text(text=heading, variant="h3"))

    for index, day in enumerate(days if isinstance(days, list) else []):
        if not isinstance(day, dict):
            continue
        activities = [
            ActivityItem(
                title=_text(activity.get("title")),
                time=activity.get("time"),
                category=activity.get("category"),
                location=activity.get("location"),
                duration=activity.get("duration"),
                note=activity.get("note"),
                done=activity.get("done"),
                # Every activity gets one: a day plan is the traveller's to
                # edit, and `drop_activity` edits the trip rather than the card.
                onRemove=_event("drop_activity", {"day": index, "index": position}),
            )
            for position, activity in enumerate(day.get("activities") or [])
            if isinstance(activity, dict)
        ]
        drew_a_day = True
        rows.append(
            ItineraryDay(
                title=_text(day.get("title")) or f"Day {index + 1}",
                date=day.get("date"),
                summary=day.get("summary"),
                children=activities,
                onAdd=_event("add_activity", {"day": index}),
            )
        )

    if not drew_a_day:
        # Nothing recorded yet. Saying so is better than an empty box, and
        # better than refusing to compile a surface the traveller is waiting
        # for: the agent's prose above it still arrives.
        #
        # Counted rather than inferred from `rows` being empty, because a
        # heading is a row: `Itinerary("Four days in Berlin")` over a trip with
        # no days would otherwise draw the promise and nothing under it.
        rows.append(Text(text="No day plan recorded yet."))

    return Column(children=rows)


#: Every macro this catalog advertises.
MACROS = (itinerary,)

#: One expander, built once: the schemas it synthesises do not depend on the
#: trip, only the expansion does — which is why the prompt can be cached and
#: still be true.
EXPANDER = MacroExpander(list(MACROS))


def with_macros(catalog: Any) -> Any:
    """The catalog as the *model* sees it: components plus macros."""
    return EXPANDER.transform_to_inference_catalog(catalog)


def expand(messages: Any, trip: dict[str, Any] | None = None) -> Any:
    """The same messages with every macro replaced by what it stands for.

    Runs on the way out, after compiling and before any pass that reads
    components — so the checks, the commit binder and the renderer all see the
    real tree and none of them needs to know macros exist.

    The trip is passed rather than ambient. It was a context variable first,
    which reads better and is wrong here: a turn is an async generator, and the
    context a generator resumes in is the caller's, not the one it was started
    in. A macro would have expanded against whatever trip the *client's* last
    `__anext__` happened to carry.

    Takes and returns whatever the compiler handed over — typed models, as of
    agent-sdk 0.9 — rather than the plain dicts the rest of this app passes
    around, because the expander reads the models. So this runs *before*
    `as_wire`, not after it, and the messages are untouched when no macro is in
    them, which is most surfaces and every surface the host composes itself.
    """
    if not any(_holds_a_macro(_as_dict(message)) for message in messages):
        return messages
    with for_trip(trip or {}):
        return EXPANDER.transform_to_transport(list(messages))


def _holds_a_macro(message: Any) -> bool:
    from .wire import components_of

    names = {str(node.get("component") or "") for node in components_of(message)}
    return any(meta.name in names for meta in EXPANDER.macros)


def _as_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    return message.model_dump(exclude_none=True, by_alias=True)
