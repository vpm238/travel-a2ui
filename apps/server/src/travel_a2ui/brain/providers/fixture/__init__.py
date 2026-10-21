"""The deterministic fixture provider.

Reads `data/` directly — the CSV and JSON a person edits. There is no build step
here and there does not need to be: `scripts/build_fixtures.py` exists only
because a Cloudflare Worker has no filesystem, and this server does.

Determinism is the point. The same query returns the same flights on every run,
so a screenshot stays true and a test can assert on a price. Which means this
port has a harder job than looking right: it has to reproduce the TypeScript's
arithmetic exactly, down to the last dollar, and
`apps/worker/test/__golden__/travel.json` is what says whether it does.

Five files, innermost first:

  `tables`    the data, read straight from `data/`
  `numbers`   the arithmetic, which has to match JavaScript's rather than Python's
  `routes`    which airline flies this, and where it stops on the way
  `places`    finding the place asked for, and inventing one when it is not here
  `provider`  the eight lookups, answered from all of the above

Everything that was importable from `fixture` still is — the tests reach for
`_rng`, `_seed` and `_to_fixed` by name to prove the JavaScript arithmetic, and
the tools reach for `_money`.
"""

from __future__ import annotations

from .tables import (  # noqa: F401 — re-exported: this package is one module to its callers
    FIXTURE_PROVENANCE,
    _AIRLINES,
    _AMENITIES,
    _BY_ALIAS,
    _BY_CODE,
    _CONNECTIONS,
    _CURRENCY_SYMBOL,
    _DATA,
    _DESTINATIONS,
    _DESTINATION_LIST,
    _HOTELS,
    _HOTEL_NAMES,
    _HOTEL_WORDS,
    _HUBS,
    _LODGING,
    _ORIGINS,
    _ORIGIN_CODES,
    _PLACE,
    _ROOT,
    _fold,
    _rows,
)
from .numbers import (  # noqa: F401 — re-exported: this package is one module to its callers
    code_for_seed,
    _MASK,
    _clock,
    _duration_minutes,
    _js_round,
    _money,
    _pick,
    _rng,
    _seed,
    _to_fixed,
)
from .routes import (  # noqa: F401 — re-exported: this package is one module to its callers
    _carriers_for,
    _connection,
    _distance_km,
    _hubs_on_the_way,
)
from .places import (  # noqa: F401 — re-exported: this package is one module to its callers
    _INVENTED_AREAS,
    _INVENTED_HIGHLIGHTS,
    _INVENTED_MONTHS,
    _INVENTED_SUMMARY,
    _elsewhere,
    _invent_destination,
    _resolve,
    _unknown_destination,
)
from .provider import (  # noqa: F401 — re-exported: this package is one module to its callers
    FixtureProvider,
    _relax_until_non_empty,
)
