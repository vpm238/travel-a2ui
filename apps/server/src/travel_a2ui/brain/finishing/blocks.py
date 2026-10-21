"""Which surface a turn's blocks land on, and how two of them compose.

The renderer has two rules that everything here is downstream of: it merges
components by id, and it draws whichever component is called `root`. So a turn
that writes two blocks has two components called `root` and the second silently
replaces the first; and a block that names a surface the traveller already
answered replaces *that*, which is how a hotel list vanished the moment one was
picked from it.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from .shared import VERSION, A2uiMessage, _components_in, _root_of

def _addressed_to(value: Any, surface_id: str) -> Any:
    """The same message, with every `surfaceId` in it set to this turn's."""
    if isinstance(value, dict):
        return {
            key: surface_id
            if key == "surfaceId" and isinstance(item, str)
            else _addressed_to(item, surface_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_addressed_to(item, surface_id) for item in value]
    return value


def on_its_own_surface(
    messages: Iterable[A2uiMessage], surface_id: str
) -> list[A2uiMessage]:
    """A turn's messages, readdressed to the card the turn was given.

    Express lets a block name the surface it draws into — `surface("sidebar")`
    — because a surface id is how you say "the persistent panel, not a new
    card". Nothing stopped a block naming a *spent* one, and the renderer's two
    rules then did the rest: it merges components by id, and it draws whichever
    component is called `root`. So a block that says `surface("inline-2")` and
    defines a `root` does not add to that card, it **replaces** it.

    Which is what was happening to the hotel. The brief's worked example opens
    `surface("inline-flights")` — a literal id, the same one every time — so a
    turn that copied the example rather than the line in "This turn" drew onto
    a surface it shared with every other turn that copied it. Pick a stay, and
    the turn that answers the press lands on the same id and its `root` takes
    the place of the list the traveller just pressed: the hotels vanish. Only
    sometimes, because it depends on the model copying the example.

    Rewritten rather than refused. The block is a finished interface and the
    traveller is owed it; the only thing wrong with it is the envelope, and the
    turn already knows the right address. Dropping it would trade a card that
    lands in the wrong place for no card at all.

    This is the renderer's contract, not the flow's — the same line `wrong_controls`
    and `half_asked` sit on. It says nothing about what the turn may draw or when;
    it says a turn may not draw over the answer to a question already asked, which
    is the one thing a spent card is for. Everything a turn wants to revisit it can
    say again on its own card, which is where the traveller is looking.
    """
    out: list[A2uiMessage] = []
    for message in messages:
        found = _components_in(message)
        elsewhere = message.get("updateDataModel")
        target = (
            found[0]
            if found
            else elsewhere.get("surfaceId")
            if isinstance(elsewhere, dict)
            else None
        )
        out.append(
            message if target in (None, surface_id) else _addressed_to(message, surface_id)
        )
    return out


#: Ids that structurally point at another component, rather than holding a value.
_ID_REFERENCES = ("children", "child", "componentId")


def _rename_components(components: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Every id in a block, prefixed, with the references that point at them."""
    known = {node["id"] for node in components if isinstance(node.get("id"), str)}

    def renamed(value: Any) -> Any:
        if isinstance(value, str):
            return f"{prefix}{value}" if value in known else value
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return value

    out: list[dict[str, Any]] = []
    for node in components:
        copy = dict(node)
        if isinstance(copy.get("id"), str) and copy["id"] in known:
            copy["id"] = f"{prefix}{copy['id']}"
        for key in _ID_REFERENCES:
            if key in copy:
                copy[key] = renamed(copy[key])
        out.append(copy)
    return out


def stack_blocks(
    messages: list[A2uiMessage], surface_id: str, block_index: int, state: dict[str, Any]
) -> list[A2uiMessage]:
    """Keeps a second block in a turn from replacing the first.

    A renderer replaces components by id, which is what lets a block re-send
    itself as it streams, and it renders whichever component is called `root`.
    So a turn that writes two blocks has two components called `root`, and the
    second silently takes the first one's place: the traveller is shown dates
    and party for three hops, then that vanishes and only the airports remain.

    Two blocks in one turn is a reasonable thing to write — one card for the
    route, one for who is on it — so this composes them rather than forbidding
    them. When a second block starts, the first block's root is re-sent under
    `b0-root`, the second block's ids are prefixed so nothing collides, and
    `root` becomes a Column of every block's root in the order written.

    Both halves therefore live on **one surface**, which is what makes the rest
    fall out rather than needing machinery of its own: `bind_commit_context`
    gathers every editable path *per surface* onto that surface's buttons, so
    one press sends both blocks' answers back together; and the client greys a
    spent surface by id, so when the next turn starts both halves go inert at
    once.

    `state` carries the turn's blocks between calls — the roots in order, and
    the first block's root node in case it has to be re-homed.
    """
    roots: list[str] = state.setdefault("roots", [])
    prefix = f"b{block_index}-" if block_index > 0 else ""
    out: list[A2uiMessage] = []
    rehomed = False

    for message in messages:
        found = _components_in(message)
        if not found or found[0] != surface_id:
            out.append(message)
            continue

        _, components = found
        # Found before renaming, while the block still calls it `root`.
        root = _root_of(components)
        root_id = root.get("id") if isinstance(root, dict) else None

        if prefix:
            # The first block's root has already gone out as `root`, and `root`
            # is about to become the column over both. Re-home it first, or the
            # column replaces the very thing it is meant to contain.
            if not rehomed and roots and roots[0] == "root":
                first = state.get("first_root")
                if isinstance(first, dict):
                    out.append(
                        {
                            "version": VERSION,
                            "updateComponents": {
                                "surfaceId": surface_id,
                                "components": [{**first, "id": "b0-root"}],
                            },
                        }
                    )
                    roots[0] = "b0-root"
                rehomed = True

            message = copy.deepcopy(message)
            target = message.get("createSurface") or message.get("updateComponents")
            target["components"] = _rename_components(components, prefix)
            if isinstance(root_id, str):
                root_id = f"{prefix}{root_id}"
        elif isinstance(root, dict):
            # Kept whole: a block re-sends itself as it streams, so the last
            # one seen is the finished one.
            state["first_root"] = copy.deepcopy(root)

        out.append(message)
        if isinstance(root_id, str) and root_id not in roots:
            roots.append(root_id)

    if len(roots) > 1:
        out.append(
            {
                "version": VERSION,
                "updateComponents": {
                    "surfaceId": surface_id,
                    "components": [
                        {"id": "root", "component": "Column", "children": list(roots)}
                    ],
                },
            }
        )
    return out
