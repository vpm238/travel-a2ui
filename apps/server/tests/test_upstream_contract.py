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
    from travel_a2ui.doors.interactions import _parser

    good = _parser("inline-1").compile(
        'title = Text("Madrid")\nroot = Column([title])', is_final=True
    )
    _VALIDATOR.validate(good)

    # A child that was never defined: compiles, and renders as a box with a
    # hole in it. Catching that is what the validator is for.
    broken = _parser("inline-1").compile(
        'title = Text("Madrid")\nroot = Column([title, missing])', is_final=True
    )
    with pytest.raises(Exception):
        _VALIDATOR.validate(broken)
