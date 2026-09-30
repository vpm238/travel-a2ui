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

from travel_a2ui.doors.interactions import _CATALOG


def test_the_catalog_exposes_a_validator() -> None:
    assert _CATALOG.validator is not None


def test_the_validator_still_takes_a_whole_payload() -> None:
    """`express.py` and `surfaces.py` both call `.validate(messages)`.

    Core 0.2.0 split this into `validate_component` and `validate_function`.
    Moving to those is real work; until it is done, this is the contract.
    """
    validate = getattr(_CATALOG.validator, "validate", None)
    assert callable(validate), (
        "a2ui-core dropped PayloadValidator.validate — every surface this "
        "server draws goes through it. Either pin core back, or move "
        "express.py and surfaces.py onto validate_component/validate_function."
    )


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
    _CATALOG.validator.validate(good)

    # A child that was never defined: compiles, and renders as a box with a
    # hole in it. Catching that is what the validator is for.
    broken = _parser("inline-1").compile(
        'title = Text("Madrid")\nroot = Column([title, missing])', is_final=True
    )
    with pytest.raises(Exception):
        _CATALOG.validator.validate(broken)
