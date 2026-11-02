"""The bits of the A2UI SDK this server actually calls.

Not a test of our code — a test of the assumption underneath it. Every check
here failed in production while the whole suite was green, and the reason is
worth keeping next to the assertions: a developer machine and a CI runner both
reuse the environment they already have, so neither of them ever resolves
`a2ui-agent-sdk` afresh. Only a clean image build does. On 2026-09-28 core
0.2.0 removed `PayloadValidator.validate`, the deployed service started
answering every turn with "'PayloadValidator' object has no attribute
'validate'", and nothing anywhere went red.

So these assert the *shape* rather than the version. A pin that is bumped on
purpose, to a release that still offers what we call, should keep these
passing; an upgrade that quietly takes a method away should not.
"""

from __future__ import annotations

import pytest

from travel_a2ui.doors.interactions import _CATALOG, _VALIDATOR


def test_something_still_validates_a_whole_payload() -> None:
    """Asserted by the call, not by where the call currently lives.

    It sat on `catalog.validator` through agent-sdk 0.6 and moved onto the
    catalog in 0.7. `_VALIDATOR` resolves whichever is present; what must never
    happen again is *neither*, which is what a 0.x upgrade did silently.
    """
    assert callable(getattr(_VALIDATOR, "validate", None)), (
        "no whole-payload validate() anywhere — every surface this server "
        "draws goes through it, and without it malformed ones reach the "
        "traveller. Find where it moved and teach _VALIDATOR about it."
    )


def test_the_catalog_is_still_the_thing_the_compiler_is_given() -> None:
    assert _CATALOG is not None


def test_a_real_compiled_surface_passes_and_a_broken_one_raises() -> None:
    """The entry point is exercised, not merely present.

    Compiled through the same parser production uses, so the payload shape is
    whatever the app really hands the validator rather than a shape invented
    here — which is the only version of this test that could have caught the
    outage.
    """
    from travel_a2ui.brain.express import as_wire
    from travel_a2ui.doors.interactions import _parser

    # Through `as_wire`, because that is what production hands the validator:
    # agent-sdk 0.9 returns typed models from `compile`, and the whole point of
    # this test is that the payload shape is the real one.
    good = as_wire(_parser("inline-1").compile(
        'title = Text("Madrid")\nroot = Column([title])', is_final=True
    ))
    _VALIDATOR.validate(good)

    # A child that was never defined: compiles, and renders as a box with a
    # hole in it. Catching that is what the validator is for.
    broken = as_wire(_parser("inline-1").compile(
        'title = Text("Madrid")\nroot = Column([title, missing])', is_final=True
    ))
    with pytest.raises(Exception):
        _VALIDATOR.validate(broken)


def test_the_wire_version_is_the_sdks_own_answer() -> None:
    """Not a literal here, and not a second copy anywhere else.

    `brain/catalog.py` carried `"v1.0"` under a comment claiming it was
    "derived by asking the compiler what it emits rather than hard-coded, which
    is what makes the upgrade a one-line pin bump instead of a hunt". It was
    hard-coded, 0.10.0 renamed the wire spelling (a2ui#3726), and the hunt
    happened: 83 tests red, all of them the same rejected envelope.

    Two more copies of the same decision turned up behind it —
    `scripts/build_skills.py` stamping the skill a model reads, and
    `apps/gallery/scripts/surfaces.mjs` building `v` + the catalog's version —
    so three places disagreed with the SDK the morning it shipped.
    """
    from a2ui.core.schema.v1_0.constants import PROTOCOL_VERSION as SDK_SAYS

    from travel_a2ui.brain.catalog import PROTOCOL_VERSION

    assert PROTOCOL_VERSION == SDK_SAYS


def test_and_it_is_what_a_compiled_surface_actually_carries() -> None:
    """The end the renderer sees, so the constant cannot be right alone."""
    from travel_a2ui.brain.catalog import PROTOCOL_VERSION, parser_for
    from travel_a2ui.brain.express import as_wire

    wire = as_wire(
        parser_for("inline-1").compile('head = Text("Hi")\nroot = Column([head])')
    )
    assert wire, "nothing compiled"
    for message in wire:
        assert message["version"] == PROTOCOL_VERSION, message


def test_the_skill_a_model_reads_agrees_with_the_envelope() -> None:
    """The second copy, asserted rather than trusted.

    `build_skills.py` defers to the server's constant now. If somebody gives it
    its own again, this is where that shows up — before a model is handed a
    brief describing one protocol while the server speaks another.
    """
    import importlib.util
    import pathlib
    import sys

    root = pathlib.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "_build_skills", root / "scripts" / "build_skills.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(root / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(root / "scripts"))

    from travel_a2ui.brain.catalog import PROTOCOL_VERSION

    assert module.PROTOCOL_VERSION == PROTOCOL_VERSION
