"""The skeleton, and what it proves about the two Express compilers.

The blueprint is a fixed Express program with everything that makes Express
worth having in it — bindings, a `_template` row, an `Event` carrying bound
context. Both servers compile it: the TypeScript through this repo's Express
port, the Python through the SDK's `ExpressParser`, which is the reference
implementation.

So this file is two tests wearing one coat. The obvious one is that the
skeleton is built correctly. The one that matters is that the reference
implementation and the port agree about what this program *means* — because if
they did not, the surface would still render, just differently, and nothing
would report it.

They agree on every field but one, and the exception is recorded below rather
than smoothed over.
"""

from __future__ import annotations

import json
import pathlib
import warnings

import pytest

warnings.filterwarnings("ignore")

from a2ui.inference_formats.experimental.express.parser import ExpressParser  # noqa: E402
from a2ui.schema.catalog import A2uiCatalog, CatalogConfig  # noqa: E402

from travel_a2ui.skeleton import PENDING_ROWS, pending_surface_for  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (ROOT / "tools" / "parity" / "__golden__" / "skeleton.json").read_text("utf-8")
)
CATALOG_PATH = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

#: The one field the two implementations disagree about.
#:
#: The catalog carries two names for itself: a short `catalogId` ("travel") and
#: a canonical `$id` (a URI). The TypeScript port emits the short one; the SDK
#: emits `$id`. Both round-trip, because the renderer stores the value on the
#: surface and never dispatches on it — so this is a difference in what the wire
#: says, not in what anyone draws.
#:
#: It is not normalised away here. The Python server is the one that ships, so
#: it emits what the reference implementation emits, and the turn's prompt is
#: told the same value — the model and the wire agreeing matters more than the
#: two servers agreeing, given one of them is being retired.
CATALOG_ID_DIFFERS = "catalogId"


@pytest.fixture(scope="module")
def parser() -> ExpressParser:
    config = CatalogConfig.from_path("travel", str(CATALOG_PATH))
    catalog = A2uiCatalog.from_config(config, version="0.9.1")
    return ExpressParser(catalog=catalog, surface_id="inline-1", version="v0.9.1")


def without_catalog_id(messages: list[dict]) -> list[dict]:
    out = json.loads(json.dumps(messages))
    for message in out:
        if "createSurface" in message:
            message["createSurface"].pop(CATALOG_ID_DIFFERS, None)
    return out


@pytest.mark.parametrize("tool", list(GOLDEN))
def test_compiles_to_what_the_typescript_compiles(tool: str, parser: ExpressParser) -> None:
    expected = GOLDEN[tool]
    pending = pending_surface_for(tool, "inline-1", parser)

    if expected is None:
        # `estimate_cost` has no predictable shape — asking what a trip costs
        # does not tell you what the model will draw — and a skeleton for a
        # shape nobody fills is worse than no skeleton.
        assert pending is None
        return

    assert pending is not None
    assert json.dumps(without_catalog_id(pending.opening), sort_keys=True) == json.dumps(
        without_catalog_id(expected["opening"]), sort_keys=True
    ), f"{tool}: the two Express compilers disagree"


def test_the_catalog_id_is_the_one_difference(parser: ExpressParser) -> None:
    """Asserted, so it stays a known difference rather than becoming folklore."""
    pending = pending_surface_for("search_flights", "inline-1", parser)
    assert pending is not None
    created = next(m for m in pending.opening if "createSurface" in m)
    ts_created = next(m for m in GOLDEN["search_flights"]["opening"] if "createSurface" in m)

    catalog = json.loads(CATALOG_PATH.read_text("utf-8"))
    assert created["createSurface"][CATALOG_ID_DIFFERS] == catalog["$id"]
    assert ts_created["createSurface"][CATALOG_ID_DIFFERS] == catalog["catalogId"]


class TestTheOpening:
    """What has to be true for the surface to paint empty rather than wrong."""

    def test_the_data_model_is_seeded_before_the_layout_paints(
        self, parser: ExpressParser
    ) -> None:
        # The ordering is the whole thing. Components referencing `/flights`
        # sent before `/flights` exists is a template with nothing to repeat
        # over, which renders as an empty list — the exact appearance of a
        # search that found nothing.
        pending = pending_surface_for("search_flights", "inline-1", parser)
        assert pending is not None
        kinds = [next(k for k in message if k != "version") for message in pending.opening]
        assert kinds == ["createSurface", "updateDataModel", "updateComponents"]

    def test_it_lays_out_as_many_rows_as_are_coming(self, parser: ExpressParser) -> None:
        pending = pending_surface_for("search_flights", "inline-1", parser)
        assert pending is not None
        seed = pending.opening[1]["updateDataModel"]
        assert seed["path"] == "/flights"
        assert seed["value"] == [{}] * PENDING_ROWS

    def test_the_blank_rows_hold_nothing_at_all(self, parser: ExpressParser) -> None:
        """Empty objects, not rows of empty strings.

        The distinction is what the shimmer is built on: a binding whose path
        does not resolve is *pending*, and one resolving to `""` is *empty*. Seed
        the rows with blank strings instead and every card paints as a flight
        with no airline and no price — which is worse than a spinner, because it
        looks like an answer.
        """
        pending = pending_surface_for("search_flights", "inline-1", parser)
        assert pending is not None
        assert all(row == {} for row in pending.opening[1]["updateDataModel"]["value"])


class TestFilling:
    def test_rows_replace_the_whole_array(self, parser: ExpressParser) -> None:
        # Replaced, not patched: a provider returning three results against four
        # blank rows would otherwise leave the fourth on screen forever.
        pending = pending_surface_for("search_flights", "inline-1", parser)
        assert pending is not None
        rows = [{"id": "a"}, {"id": "b"}]
        messages = pending.fill({"flights": rows})
        assert messages is not None
        assert messages[0]["updateDataModel"] == {
            "surfaceId": "inline-1",
            "path": "/flights",
            "value": rows,
        }

    @pytest.mark.parametrize(
        "result", [None, {}, {"flights": []}, {"flights": "nope"}, "not a dict"]
    )
    def test_nothing_to_show_fills_nothing(self, result, parser: ExpressParser) -> None:
        """A refusal reaches here as a result with no rows in it.

        Filling the skeleton with an empty array would leave a heading that says
        "Finding flights" above nothing at all — which is precisely the empty
        surface the provider contract exists to prevent. Returning `None` leaves
        the pending state up until the model's own surface replaces it.
        """
        pending = pending_surface_for("search_flights", "inline-1", parser)
        assert pending is not None
        assert pending.fill(result) is None

    def test_a_tool_that_draws_nothing_predictable_gets_no_skeleton(
        self, parser: ExpressParser
    ) -> None:
        for tool in ("estimate_cost", "save_trip", "get_trip", "no_such_tool"):
            assert pending_surface_for(tool, "inline-1", parser) is None
