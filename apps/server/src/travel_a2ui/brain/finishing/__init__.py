"""Putting the trip into surfaces, and closing the gaps the model leaves.

Four passes run over every surface before it goes out, and all four exist
because something that was *asked* of the model was sometimes not done:

  `seeding`   fills `/trip` and `/plan` so controls open pre-filled
  `commit`    makes sure a button carries every value on its surface
  `labels`    replaces a night count the model wrote as literal text
  `panels`    removes a `change` button from anywhere but the panel

Doing them here rather than in the browser is the point. The old versions of
the first and third lived in the React app, which meant the web client knew
what a trip was and the Flutter client would have had to be taught the same
things to behave the same way — and taught again every time the trip grew a
field. The server already holds the trip and can say all of this in the
protocol's own words, so a thin client gets a surface that is already right.

Two more files that are not passes: `shared`, which is how all of them read an
A2UI message, and `blocks`, which decides what a turn's blocks land on — one
surface per turn, composed rather than overwritten.
"""

from __future__ import annotations

from typing import Any, Iterable

from .shared import (  # noqa: F401 — re-exported: this package is one module to its callers
    REBUILT_IN_A_TURN,
    STANDING_SURFACES,
    VALUE_EDITORS,
    VERSION,
    _bound_paths,
    _components_in,
    _event_of,
    _root_of,
)
from .seeding import (  # noqa: F401 — re-exported: this package is one module to its callers
    plan_rows,
    seed_surface_trip,
    trip_updates,
    _STAGE_LABELS,
    _kind_of,
    _stated_facts,
    _value_text,
)
from .blocks import (  # noqa: F401 — re-exported: this package is one module to its callers
    on_its_own_surface,
    stack_blocks,
    _addressed_to,
    _rename_components,
)
from .commit import (  # noqa: F401 — re-exported: this package is one module to its callers
    bind_commit_context,
    _key_for,
)
from .labels import (  # noqa: F401 — re-exported: this package is one module to its callers
    bind_derived_labels,
    name_pressable_cards,
    _COUNT_OF_NIGHTS,
    _is_count_of_nights,
    _is_path_binding,
)
from .panels import (  # noqa: F401 — re-exported: this package is one module to its callers
    panel_events,
    strip_panel_actions,
)
from .shared import A2uiMessage  # noqa: F401


def finish(
    messages: list[A2uiMessage],
    trip: dict[str, Any],
    standing: Iterable[str] = STANDING_SURFACES,
    carried: dict[str, dict[str, None]] | None = None,
) -> list[A2uiMessage]:
    """All five passes, in the order the Worker runs them.

    The order matters in one place: `bind_commit_context` may *add* a button,
    and `strip_panel_actions` may remove one, so seeding has to happen first
    (it is what a control opens showing) and stripping last (so a button added
    on a panel is still taken back off it).

    `name_pressable_cards` reads properties and writes one of its own, so it
    does not care where it sits; it runs beside the other pass that rewrites a
    label the model wrote.
    """
    return strip_panel_actions(
        name_pressable_cards(
            bind_derived_labels(bind_commit_context(seed_surface_trip(messages, trip), carried))
        ),
        standing,
    )
