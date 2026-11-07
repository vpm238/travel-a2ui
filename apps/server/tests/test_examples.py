"""The worked examples are the source, and they hold up on the wire.

`catalogs/a2ui-travel/examples/*.json` are hand-written A2UI messages. The SDK
processor validates them against the model's catalogs when it is built, and
decompiles them into the prompt. This checks the other half: expanded by the
macros, every one is a payload a renderer of the whole catalog accepts.
"""

from __future__ import annotations

import pytest
from a2ui.inference_formats import to_message_models  # noqa: E402
from a2ui.parser import to_message_dicts  # noqa: E402
from a2ui.utils import validate_payload  # noqa: E402

from travel_a2ui.brain.catalog import CATALOG, CATALOG_DIR, EXAMPLES, PROCESSOR  # noqa: E402
from travel_a2ui.brain.macros import EXPANDER, MACRO_NAMES  # noqa: E402

FILES = sorted((CATALOG_DIR / "examples").glob("*.json"))


def test_every_file_is_an_example() -> None:
    assert len(EXAMPLES) == len(FILES) >= 5


@pytest.mark.parametrize("turn", EXAMPLES, ids=[path.stem for path in FILES])
def test_it_expands_to_a_valid_payload(turn: list[dict]) -> None:
    expanded = to_message_dicts(EXPANDER.transform_to_transport(to_message_models(turn)))
    left = [
        component["component"]
        for message in expanded
        for body in message.values()
        if isinstance(body, dict)
        for component in body.get("components") or []
        if component.get("component") in MACRO_NAMES
    ]
    assert not left, f"macros left unexpanded: {left}"
    validate_payload([CATALOG], expanded)


def test_the_prompt_shows_them() -> None:
    snippet = PROCESSOR.prompt_snippet
    assert snippet.count("<a2ui>") >= len(EXAMPLES)
    assert 'Trip("Your trip to Madrid"' in snippet or "Trip(" in snippet
