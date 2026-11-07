"""The catalog and the recorded sample conform to the published A2UI v1.0 schemas.

Validated with JSON Schema against the spec's own schema files, the ones
`@a2ui/web_core` ships, rather than against anything this app wrote: a catalog
or a message the spec rejects is one some renderer will reject, whatever the
SDK in this repository happens to tolerate.

The schemas come from `node_modules`, which CI installs before the Python
tests. Without them (a checkout that never ran `npm install`) these are skipped
and say why.
"""

from __future__ import annotations

import json
import warnings

import pytest

warnings.filterwarnings("ignore")

from a2ui.utils import RendererState  # noqa: E402

from travel_a2ui import ROOT  # noqa: E402
from travel_a2ui.brain.catalog import CATALOG  # noqa: E402

SCHEMAS = ROOT / "node_modules" / "@a2ui" / "web_core" / "src" / "v1_0" / "schemas"
CATALOG_FILE = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
SAMPLE = ROOT / "apps" / "web" / "public" / "sample-trip.json"

pytestmark = pytest.mark.skipif(
    not SCHEMAS.is_dir(), reason="the v1.0 schemas come from node_modules: run npm install"
)


def _validator(schema_file: str):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for path in SCHEMAS.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            document.get("$id", path.name), Resource.from_contents(document, default_specification=DRAFT202012)
        )
    # A message names its components through `catalog.json#/$defs/anyComponent`,
    # relative to the spec's own address, so the catalog in use is registered
    # there.
    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    registry = registry.with_resource(
        "https://a2ui.org/specification/v1_0/catalog.json",
        Resource.from_contents(catalog, default_specification=DRAFT202012),
    )
    schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


def _recorded_messages() -> list[tuple[int, dict]]:
    recording = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return [
        (number, message)
        for number, turn in enumerate(recording["turns"], 1)
        for event in turn["events"]
        if event["type"] == "ui"
        for message in event["messages"]
    ]


def test_the_catalog_is_a_valid_v1_catalog() -> None:
    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    errors = [
        f"{'/'.join(map(str, error.absolute_path))}: {error.message[:200]}"
        for error in _validator("catalog_definition.json").iter_errors(catalog)
    ]
    assert not errors, "\n".join(errors)


def test_every_recorded_message_is_valid_v1_for_this_catalog() -> None:
    validator = _validator("agent_to_renderer.json")
    failures = [
        f"turn {number}: {next(iter(k for k in message if k != 'version'))}"
        for number, message in _recorded_messages()
        if not validator.is_valid(message)
    ]
    assert not failures, "Re-record with tools/sample/record.py:\n" + "\n".join(failures)


def test_the_recording_replays_into_one_renderer() -> None:
    """In order, into one renderer state, as a browser receives it.

    Stricter than validating each message alone: a surface created twice, an
    update to a surface that does not exist, or a reference to a component no
    earlier message sent all fail here.
    """
    state = RendererState([CATALOG])
    for number, message in _recorded_messages():
        try:
            state.apply([message])
        except Exception as error:  # noqa: BLE001 - the message is the report
            pytest.fail(f"turn {number}: {type(error).__name__}: {str(error)[:300]}")
