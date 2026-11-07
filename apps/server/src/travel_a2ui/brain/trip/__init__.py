"""What a trip is, and what the agent should do about it next.

This is the one piece of the project that is neither generated from the catalog
nor provided by the SDK: judgement about which fields block which goals, what
to ask for next, and when to stop asking. `tests/goldens/trip.json` pins it:
nine trips chosen for the decisions they force, run through every function
here.

One module to everybody who uses it (`from ..brain import trip as model`, then
`model.normalize`, `model.journey`). It is six files because it does six jobs:

  `fields`   what a trip is made of, and how a key addresses it
  `values`   reading a value the way the model wrote it
  `route`    the journey as hops: who is on each, and what each still needs
  `problems` what is wrong with it, and what not to let into it
  `asking`   what is still worth asking about, and how to say it
  `edits`    merging, confirming, releasing, and hops of their own

They are layered in that order and import only downwards: `fields` knows
nothing about anybody. The field table itself lives in `data/trip-model.json`.
"""

from __future__ import annotations

from .asking import (  # noqa: F401 — re-exported: this package is one module to its callers
    _short_date,
    ask_for,
    basis_of,
    can_do,
    missing_for,
    summarize,
)
from .edits import (  # noqa: F401 — re-exported: this package is one module to its callers
    DEPENDENTS,
    LEG_OWNED,
    confirm,
    merge,
    normalize,
    onto_leg,
    release,
    released,
    screen_patch,
    unskip,
)
from .fields import (  # noqa: F401 — re-exported: this package is one module to its callers
    _CODE,
    _DATA,
    _DATE_ONLY,
    _LEADING_NUMBER,
    _LEG_KEY,
    _MODEL,
    _MONTHS,
    _ROOT,
    BY_KEY,
    DECISIONS,
    FIELDS,
    LIST_KINDS,
    REQUIREMENTS,
    STAGES,
    TRIP_KEYS,
    Leg,
    Stage,
    Trip,
    _blank,
    binding_for,
    field_for,
    is_hop_key,
    is_trip_key,
)
from .problems import (  # noqa: F401 — re-exported: this package is one module to its callers
    _route_problems,
    days_until,
    nights,
    problems,
)
from .route import (  # noqa: F401 — re-exported: this package is one module to its callers
    _HOP_DECISIONS,
    _legs_of,
    _nights_of,
    _own_leg,
    _planned_days,
    journey,
    party_varies,
    stops,
)
from .values import (  # noqa: F401 — re-exported: this package is one module to its callers
    _days_between,
    _js_round,
    _to_activity,
    _to_date,
    _to_day,
    _to_flag,
    _to_leg,
    _to_number,
    coerce,
)
