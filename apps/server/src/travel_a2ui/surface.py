"""Putting the trip into surfaces, and closing the gaps the model leaves.

Four passes run over every surface before it goes out, and all four exist
because something that was *asked* of the model was sometimes not done:

  `seed_surface_trip`    fills `/trip` and `/plan` so controls open pre-filled
  `bind_commit_context`  makes sure a button carries every value on its surface
  `bind_derived_labels`  replaces a night count the model wrote as literal text
  `strip_panel_actions`  removes a `change` button from anywhere but the panel

Doing them here rather than in the browser is the point. The old versions of
the first and third lived in the React app, which meant the web client knew
what a trip was and a Swift or Flutter client would have had to be taught the
same things to behave the same way — and taught again every time the trip grew
a field. The server already holds the trip and can say all of this in the
protocol's own words, so a thin client gets a surface that is already right.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from . import trip as model

A2uiMessage = dict[str, Any]

VERSION = "v0.9.1"

#: The surfaces that show current state rather than a moment in the past.
STANDING_SURFACES = ("sidebar", "home")

#: How a plan step reads on screen.
_STAGE_LABELS = {
    "route": "Where to, and from",
    "dates": "Dates",
    "party": "Who is going",
    "flight": "Flight",
    "stay": "Somewhere to stay",
    "budget": "Budget",
    "plan": "The days",
}

#: Components that compose an answer rather than commit one.
#:
#: The distinction is the whole interaction model: dragging a slider or typing a
#: name is someone still answering, and only a button means they are done. These
#: are the components whose bound paths a commit button must therefore carry.
VALUE_EDITORS = frozenset(
    {
        "TextField",
        "CheckBox",
        "ChoicePicker",
        "Slider",
        "DateTimeInput",
        "DateRangePicker",
        "TravelerCounter",
    }
)


# --------------------------------------------------------------------------
# The plan, and the trip, as data a surface binds to
# --------------------------------------------------------------------------


def plan_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """The plan, as rows a surface can bind to without computing anything.

    The shape is the agent's and the rows are the server's. Labels, marks and
    notes are resolved here, which keeps a Flutter client from needing an
    opinion about what "stay" is called in English — and means ticking a
    checkbox does not cost a model turn.
    """
    state = model.plan(trip)
    varies = model.party_varies(trip)

    steps: list[dict[str, Any]] = []
    for step in state["steps"]:
        is_next = bool(state.get("next")) and state["next"]["stage"] == step["stage"]
        pending = step.get("pending") or {}
        note = (
            "not needed"
            if step.get("skipped")
            else ", ".join(pending.get("stops", []))
            if pending.get("stops")
            else ""
        )
        # A glyph rather than a state name: the panel is read, not parsed, and
        # this keeps the binding to one component instead of a conditional.
        mark = (
            "–"
            if step.get("skipped")
            else "✓"
            if step.get("done")
            else "→"
            if is_next
            else "·"
        )
        label = _STAGE_LABELS.get(step["stage"], step["stage"])
        steps.append(
            {
                "stage": step["stage"],
                "label": label,
                "mark": mark,
                "state": (
                    "skipped"
                    if step.get("skipped")
                    else "done"
                    if step.get("done")
                    else "next"
                    if is_next
                    else "todo"
                ),
                "note": note,
                # One string, ready to draw. A template row is a single
                # component and its children cannot be declared inline, so a Row
                # of mark/label/note is not something the agent can express
                # here — and composing it server-side is one less thing for the
                # model to get subtly wrong every turn.
                "line": f"{mark} {label}" + (f" — {note}" if note else ""),
            }
        )

    route: list[dict[str, Any]] = []
    for leg in model.stops(trip):
        detail = [
            f"{leg['travelers']}×" if leg.get("travelers") is not None and varies else "",
            leg.get("purpose") or "",
            "no stay needed" if leg.get("needsStay") is False else "",
            "dates?" if not leg.get("startDate") else "",
            "stay?" if leg.get("needsStay") is True and not leg.get("selectedHotel") else "",
        ]
        detail = [part for part in detail if part]
        joined = " · ".join(detail)
        route.append(
            {
                "place": leg["destination"],
                "detail": joined,
                "line": f"{leg['destination']} — {joined}" if detail else leg["destination"],
            }
        )

    next_stage = state.get("next")
    return {
        "done": state["done"],
        "total": state["total"],
        "caption": f"{state['done']} of {state['total']}",
        "complete": state["complete"],
        "nextLabel": (
            _STAGE_LABELS.get(next_stage["stage"], next_stage["stage"]) if next_stage else ""
        ),
        "steps": steps,
        "route": route,
        # So the panel can decide whether the route is worth drawing at all.
        "multiStop": len(route) > 1,
    }


def _stated_facts(trip: dict[str, Any]) -> list[tuple[str, Any]]:
    """Trip fields worth putting on a surface: set, and not empty."""
    facts: list[tuple[str, Any]] = []
    for key in model.TRIP_KEYS:
        value = trip.get(key)
        if value is None or value == "":
            continue
        facts.append((key, value))
    return facts


def seed_surface_trip(messages: list[A2uiMessage], trip: dict[str, Any]) -> list[A2uiMessage]:
    """Fills a newly created surface's `/trip` with what the trip already knows.

    Only fields the surface left unset. A model that deliberately wrote a value
    — a suggested date, a widened budget — is *proposing* something, and a
    proposal should beat the older fact it proposes to replace.

    Written into `createSurface.dataModel` rather than as following
    `updateDataModel` messages, so the surface is complete in the message that
    creates it and never paints once empty and again filled.
    """
    facts = _stated_facts(trip)

    for message in messages:
        if "createSurface" not in message:
            continue
        surface = message["createSurface"]
        data_model = dict(surface.get("dataModel") or {})
        seeded = dict(data_model.get("trip") or {})
        for key, value in facts:
            if key in seeded:
                continue
            seeded[key] = value
        # No early return on an empty trip: `/plan` still has to be here, or a
        # panel drawn before anything is decided binds to nothing and renders
        # blank rather than rendering the sequence it is about to walk through.
        data_model["trip"] = seeded
        data_model["plan"] = plan_rows(trip)
        surface["dataModel"] = data_model

    return messages


def trip_updates(surface_id: str, trip: dict[str, Any]) -> list[A2uiMessage]:
    """`updateDataModel` messages bringing a standing surface up to date.

    For the panels, which outlive the turn that drew them. An inline card is
    deliberately not included: it is the record of what was asked at the time,
    and rewriting history underneath it is worse than letting it be old.
    """
    messages: list[A2uiMessage] = [
        {
            "version": VERSION,
            "updateDataModel": {"surfaceId": surface_id, "path": f"/trip/{key}", "value": value},
        }
        for key, value in _stated_facts(trip)
    ]
    # The checklist moves whenever the trip does, and it moves without a model
    # turn: the agent drew the shape once and the rows arrive as data.
    messages.append(
        {
            "version": VERSION,
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/plan",
                "value": plan_rows(trip),
            },
        }
    )
    return messages


# --------------------------------------------------------------------------
# Making "one surface, one button, everything sent together" a guarantee
# --------------------------------------------------------------------------


def _bound_paths(node: dict[str, Any]) -> list[str]:
    """Every `{path}` binding anywhere inside a component's properties."""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        # A child-list template's `path` points at a collection to repeat over,
        # not at a value someone edited.
        if isinstance(value.get("path"), str) and "componentId" not in value:
            found.append(value["path"])
        for key, nested in value.items():
            if key == "path":
                continue
            walk(nested)

    for key, value in node.items():
        if key in ("id", "component"):
            continue
        walk(value)
    return found


def _key_for(path: str, taken: set[str]) -> str:
    """`/trip/startDate` → `startDate`, kept unique against what is already there."""
    segments = [part for part in path.split("/") if part]
    base = segments[-1] if segments else "value"
    if base not in taken:
        return base
    # `/trip/origin` colliding with `/leg/origin` becomes `tripOrigin`.
    for depth in range(2, len(segments) + 1):
        parts = segments[-depth:]
        candidate = parts[0] + "".join(part[0].upper() + part[1:] for part in parts[1:])
        if candidate not in taken:
            return candidate
    number = 2
    while f"{base}{number}" in taken:
        number += 1
    return f"{base}{number}"


def _root_of(components: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The container everything else hangs off.

    `root` by convention — the Express examples and the generated skill both use
    it — and otherwise the one component nothing else lists as a child, which is
    the same thing said structurally.
    """
    for node in components:
        if node.get("id") == "root":
            return node
    claimed: set[str] = set()
    for node in components:
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, str):
                    claimed.add(child)
    for node in components:
        if node.get("id") not in claimed:
            return node
    return None


def _event_of(node: dict[str, Any]) -> dict[str, Any] | None:
    """The `action.event` object on a component, when it has one."""
    action = node.get("action")
    if not isinstance(action, dict):
        return None
    event = action.get("event")
    return event if isinstance(event, dict) else None


def _components_in(message: A2uiMessage) -> tuple[str, list[dict[str, Any]]] | None:
    if "createSurface" in message:
        surface = message["createSurface"]
        return surface["surfaceId"], surface.get("components") or []
    if "updateComponents" in message:
        update = message["updateComponents"]
        return update["surfaceId"], update.get("components") or []
    return None


def bind_commit_context(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """Adds every editable path on a surface to that surface's commit buttons.

    A2UI already has the canonical mechanism for submitting a form: a button
    whose action declares a *context* of bound paths, which every renderer
    resolves against the data model and posts back. The catch is that it depends
    on the model remembering to bind every field it asked about. Forget one and
    the traveller's answer is silently dropped — the hardest class of bug to
    see, because the surface looks right and the trip is merely wrong.

    So this closes it server-side. Paths the model already bound are left
    exactly as they are, under whatever key it chose: it names things better
    than an algorithm splitting on slashes, and a context that changes shape
    between turns is worse than an ugly key.
    """
    # Components arrive across several messages for one surface, and a button
    # can be created before the field it must carry. So: collect per surface.
    #
    # A dict rather than a set, and the reason is not style. These paths become
    # the keys of the button's context in iteration order, and `_key_for`
    # resolves a collision by qualifying whichever path it reaches *second* —
    # so an unordered set produces `origin`/`legOrigin` one run and
    # `legOrigin`/`origin` the next. The payload a client receives would then
    # change shape between deploys for no reason anybody could see.
    editable: dict[str, dict[str, None]] = {}
    buttons: dict[str, list[dict[str, Any]]] = {}

    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        surface_id, components = found
        for node in components:
            if node.get("component") in VALUE_EDITORS:
                paths = editable.setdefault(surface_id, {})
                for path in _bound_paths(node):
                    paths.setdefault(path, None)
            if _event_of(node):
                buttons.setdefault(surface_id, []).append(node)

    # A surface of editors with nothing to press is a dead end: the traveller
    # has composed an answer and there is no way to send it. The skill says to
    # draw the button, and mostly it does; this is the case where it did not.
    #
    # Adding one here rather than in the browser is what keeps the guarantee
    # portable. The old fix was a bar the React app drew for itself, which meant
    # an iOS client shipped the dead end.
    for surface_id, paths in editable.items():
        if not paths or buttons.get(surface_id):
            continue

        # The components are wherever they actually are: `createSurface` carries
        # them in v1.0 and often nothing in v0.9.1, where they arrive in a
        # following `updateComponents`. Taking the first message for the surface
        # would find an empty one and give up.
        components = None
        root = None
        for message in messages:
            found = _components_in(message)
            if not found or found[0] != surface_id or not found[1]:
                continue
            candidate = found[1]
            maybe_root = _root_of(candidate)
            if maybe_root is not None and isinstance(maybe_root.get("children"), list):
                components = candidate
                root = maybe_root
        if components is None or root is None:
            continue

        commit = {
            "id": "__commit",
            "component": "Button",
            "label": "Send",
            "action": {"event": {"name": "commit_surface", "context": {}}},
        }
        components.append(commit)
        root["children"].append(commit["id"])
        buttons[surface_id] = [commit]

    for surface_id, paths in editable.items():
        if not paths:
            continue
        for node in buttons.get(surface_id, []):
            event = _event_of(node)
            if event is None:
                continue

            context = event.get("context")
            existing = dict(context) if isinstance(context, dict) else {}

            already_bound = {
                value["path"]
                for value in existing.values()
                if isinstance(value, dict) and isinstance(value.get("path"), str)
            }

            keys = set(existing)
            for path in paths:
                if path in already_bound:
                    continue
                key = _key_for(path, keys)
                keys.add(key)
                existing[key] = {"path": path}

            event["context"] = existing

    return messages


# --------------------------------------------------------------------------
# Night counts the model wrote as text
# --------------------------------------------------------------------------

_COUNT_OF_NIGHTS = re.compile(r"^\d+\s*nights?$", re.IGNORECASE)


def _is_path_binding(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("path"), str)


def _is_count_of_nights(value: Any) -> bool:
    """True for a label that is only trying to say how many nights it is.

    Missing entirely, or a bare count the model worked out this turn. A template
    is left alone — that is the right answer already, and rewriting it would
    throw away wording the model chose.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text == "":
        return True
    if "${" in text:
        return False
    return bool(_COUNT_OF_NIGHTS.match(text))


def bind_derived_labels(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """Night counts the model wrote as text, replaced by the call that computes them.

    The interesting failure is not the one that looks broken. A model that
    writes `nightsLabel="7 nights"` produces a label that is correct in the
    screenshot and a lie the moment the traveller moves a date — and nothing
    downstream ever notices, because a string is a string.

    A2UI already has the answer: a `formatString` whose template carries
    `${calcNights(...)}` is resolved by every renderer against the live data
    model, so the label recomputes as the picker moves with no turn in between.
    """
    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        for node in found[1]:
            if node.get("component") != "DateRangePicker":
                continue
            start, end = node.get("start"), node.get("end")
            # Only when both ends are bound: a picker holding literal dates has
            # nothing to recompute against.
            if not _is_path_binding(start) or not _is_path_binding(end):
                continue
            if not _is_count_of_nights(node.get("nightsLabel")):
                continue
            node["nightsLabel"] = {
                "call": "formatString",
                "args": {
                    "value": (
                        "${calcNights(start:${" + start["path"] + "}, "
                        "end:${" + end["path"] + "})} nights"
                    )
                },
            }
    return messages


# --------------------------------------------------------------------------
# Keeping the panel's one interaction out of the conversation
# --------------------------------------------------------------------------


def panel_events(trip: dict[str, Any]) -> list[A2uiMessage]:
    """The standing panels, brought up to date, as events for any transport.

    Every door does this at the end of a turn and each used to do it itself: the
    same loop over `STANDING_SURFACES`, the same `trip_updates`, the same event
    shape, written twice. That is not a lot of code, and duplication of exactly
    this size is how the doors drift — the typed path grew a per-turn surface id
    and a departure-airport hint that the voice path did not, for no reason
    except that nobody was looking at both.

    Returned rather than yielded because one caller is a synchronous generator
    and the other is inside a websocket pump; a list is the shape both can use
    without either pretending to be the other.
    """
    events: list[A2uiMessage] = []
    for surface_id in STANDING_SURFACES:
        updates = trip_updates(surface_id, trip)
        if updates:
            events.append(
                {
                    "type": "ui",
                    "surfaceId": surface_id,
                    "messages": updates,
                    "done": True,
                }
            )
    return events


def strip_panel_actions(
    messages: list[A2uiMessage], standing_surfaces: Iterable[str] = STANDING_SURFACES
) -> list[A2uiMessage]:
    """Removes a `change` action from anywhere that is not a standing panel.

    The split this whole app is built on is that the conversation is where you
    decide and the panel is where decisions live — so the panel is read-only
    except for one thing, a `change` that re-opens a settled decision back in
    the conversation. That direction is enforced: editors drawn on a panel are
    ignored by the host.

    The other direction was only asked for, and a live run showed it being
    ignored: under a card asking for dates, the model drew the panel's own
    record again, so the same decision had two Change buttons on screen at once,
    one of them inside the surface the traveller was still filling in.
    """
    standing = set(standing_surfaces)

    def prune(surface_id: str, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if surface_id in standing:
            return components

        dropped = {
            str(node["id"])
            for node in components
            if (_event_of(node) or {}).get("name") == "change"
        }
        if not dropped:
            return components

        # Repeated, because dropping a button can empty the row that held it,
        # and an empty row is a gap on screen that nothing explains.
        kept = [node for node in components if str(node.get("id")) not in dropped]
        for _ in range(5):
            changed = False
            for node in kept:
                children = node.get("children")
                if not isinstance(children, list):
                    continue
                filtered = [
                    child
                    for child in children
                    if not isinstance(child, str) or child not in dropped
                ]
                if len(filtered) != len(children):
                    node["children"] = filtered
                    changed = True
                # A container that only ever held the button, and is not root.
                if (
                    not filtered
                    and node.get("id") != "root"
                    and str(node.get("id")) not in dropped
                ):
                    dropped.add(str(node.get("id")))
                    changed = True
            if not changed:
                break
            kept = [node for node in kept if str(node.get("id")) not in dropped]
        return kept

    for message in messages:
        if "createSurface" in message:
            surface = message["createSurface"]
            if surface.get("components"):
                surface["components"] = prune(surface["surfaceId"], surface["components"])
        elif "updateComponents" in message:
            update = message["updateComponents"]
            update["components"] = prune(update["surfaceId"], update.get("components") or [])

    return messages


def finish(
    messages: list[A2uiMessage], trip: dict[str, Any], standing: Iterable[str] = STANDING_SURFACES
) -> list[A2uiMessage]:
    """All four passes, in the order the Worker runs them.

    The order matters in one place: `bind_commit_context` may *add* a button,
    and `strip_panel_actions` may remove one, so seeding has to happen first
    (it is what a control opens showing) and stripping last (so a button added
    on a panel is still taken back off it).
    """
    return strip_panel_actions(
        bind_derived_labels(bind_commit_context(seed_surface_trip(messages, trip))), standing
    )
