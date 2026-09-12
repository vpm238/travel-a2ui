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

They agree on every field.
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

#: The field worth naming, because it looked for a while like a difference.
#:
#: The catalog carries two names for itself — `catalogId` and `$id` — and they
#: are the same string. An earlier comparison of the two implementations
#: appeared to show the port emitting a short name where the SDK emitted the
#: URI; that short name came from a hardcoded value in the throwaway harness
#: doing the comparing, not from either implementation. They agree.
#:
#: Kept as a named constant rather than deleted because "do the two compilers
#: agree about the catalog identifier" is a real question with a real answer,
#: and the answer is worth asserting rather than remembering.
CATALOG_ID = "catalogId"


@pytest.fixture(scope="module")
def parser() -> ExpressParser:
    config = CatalogConfig.from_path("travel", str(CATALOG_PATH))
    catalog = A2uiCatalog.from_config(config, version="0.9.1")
    return ExpressParser(catalog=catalog, surface_id="inline-1", version="v0.9.1")


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
    # Compared whole, nothing normalised away: the two compilers agree on every
    # field, and stripping one before comparing is how a test stops noticing.
    assert json.dumps(pending.opening, sort_keys=True) == json.dumps(
        expected["opening"], sort_keys=True
    ), f"{tool}: the two Express compilers disagree"


def test_both_implementations_name_the_catalog_the_same_way(
    parser: ExpressParser,
) -> None:
    """The identifier the wire carries, and the one the prompt is told.

    Asserted because it is the field most likely to drift silently: a renderer
    stores it on the surface and never dispatches on it, so a mismatch changes
    nothing visible until something downstream starts caring.
    """
    pending = pending_surface_for("search_flights", "inline-1", parser)
    assert pending is not None
    created = next(m for m in pending.opening if "createSurface" in m)
    ts_created = next(m for m in GOLDEN["search_flights"]["opening"] if "createSurface" in m)

    catalog = json.loads(CATALOG_PATH.read_text("utf-8"))
    assert created["createSurface"][CATALOG_ID] == ts_created["createSurface"][CATALOG_ID]
    assert created["createSurface"][CATALOG_ID] == catalog["$id"]
    # The catalog's two names for itself are the same string; a change that
    # made them differ would need a decision about which one goes on the wire.
    assert catalog["catalogId"] == catalog["$id"]


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
