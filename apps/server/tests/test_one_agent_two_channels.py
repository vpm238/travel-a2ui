"""One agent, two channels, and the seam between them.

The architecture this guards: everything about *travel* — who the agent is, how
a journey is shaped, what this deployment can answer about, which control a
decision is asked for in — is written once and handed to both the Interactions
API and the Live API. What differs between them is how an answer leaves: the
text channels are taught a notation and parse `<a2ui>` blocks out of the
stream, the spoken one is taught that a function call is the only way to reach
a screen.

That was true and nothing held it in place, so it was quietly drifting. The
spoken door had grown its own copy of "take the rows out of the result" —
`_without_the_list`, which read a key no tool has ever returned and so did
nothing at all for as long as it existed, while the typed door did not strip
them either. Two channels, one rule, zero working implementations.

These are the tests that would have caught that: the domain layer is
byte-identical across the channels, and the things both doors do to a result
are done by one function.
"""

from __future__ import annotations

from travel_a2ui.brain import skills


DOMAIN = ("role", "flow", "journey", "inventory", "controls")


def _stable(draws: str) -> str:
    stable, _ = skills.build_prompt_parts(
        variant="express-modular",
        surface="inline",
        surface_id="inline-1",
        catalog_id="a2ui-travel",
        trip={"destination": "Madrid", "origin": "JFK"},
        today="2026-04-01",
        draws=draws,
    )
    return stable


def _domain(draws: str) -> str:
    """The travel half of a channel's prompt — everything before the drawing layer."""
    from travel_a2ui.brain.skills import _for_channel

    return "\n\n---\n\n".join(
        [
            _for_channel(skills.ROLE, draws),
            _for_channel(skills.FLOW, draws),
            _for_channel(skills.JOURNEY, draws),
            skills._inventory(),
            skills._controls(),
        ]
    )


class TestBothChannelsGetTheSameAgent:
    def test_neither_channel_has_a_rule_the_other_does_not(self) -> None:
        """Change how a trip works and both channels change, or neither does.

        Line by line, because the whole point is that no rule exists on one
        channel only. What the typed channel has and the spoken one does not
        must be inside a fence — and nothing may be the other way round, since
        a fence can only ever remove.
        """
        typed = [line for line in _domain("express").splitlines() if line.strip()]
        spoken = [line for line in _domain("tools").splitlines() if line.strip()]

        invented = set(spoken) - set(typed)
        assert not invented, f"the spoken channel has rules of its own: {sorted(invented)[:5]}"

        fenced = {
            line.strip()
            for text in (skills.ROLE, skills.FLOW, skills.JOURNEY)
            for passage in skills._EXPRESS_ONLY.findall(text)
            for line in passage.splitlines()
            if line.strip()
        }
        only_typed = {line.strip() for line in set(typed) - set(spoken)}
        assert only_typed <= fenced, (
            "the channels differ outside a fence, so a rule about travel now "
            f"applies on one and not the other: {sorted(only_typed - fenced)[:5]}"
        )

    def test_and_a_fenced_passage_only_ever_holds_notation(self) -> None:
        """The fence is for *how* to draw. A fact about travel inside one is a fact lost.

        Checked by what a fenced passage may mention: a component, a macro, a
        block, a binding. Not a date rule, a party rule, a hop or a lookup.
        """
        import re

        for name, text in (("role", skills.ROLE), ("flow", skills.FLOW), ("journey", skills.JOURNEY)):
            for passage in skills._EXPRESS_ONLY.findall(text):
                assert re.search(
                    r"<a2ui>|surface\(|root = |[A-Z][A-Za-z]+\(|\$/|Express", passage
                ), f"{name}: a fenced passage with no notation in it:\n{passage}"

    def test_the_fences_are_balanced(self) -> None:
        """An unclosed fence silently swallows the rest of a brief."""
        for name, text in (("role", skills.ROLE), ("flow", skills.FLOW), ("journey", skills.JOURNEY)):
            assert text.count("<!-- draws:express -->") == text.count("<!-- /draws -->"), (
                f"{name}.md has an unbalanced draws fence"
            )
            # And the typed channel keeps every byte that is not a marker.
            assert skills._for_channel(text, "express") == text.replace(
                "<!-- draws:express -->\n", ""
            ).replace("<!-- /draws -->\n", ""), f"{name}.md: the typed channel lost content"

    def test_the_spoken_channel_is_never_taught_express(self) -> None:
        """Its replies are audio. A notation in one is read aloud, one token at a time."""
        spoken = _domain("tools")
        for tell in ("<a2ui>", 'surface("', "root = Column", "@path", "Itinerary()"):
            assert tell not in spoken, (
                f"{tell!r} reached a channel that has no compiler to send it to"
            )
        assert "show_" in _stable("tools"), "and it was not told what to call instead"


def _EXPRESS_ONLY_OUT(text: str) -> str:
    """Whatever survives on the narrowest channel — the rules, with no notation."""
    return skills._EXPRESS_ONLY.sub("", text).replace("\n\n\n", "\n\n")


class TestWhatBothDoorsDoToAResultIsDoneOnce:
    """The rule that had two homes and no working implementation."""

    def test_withholding_rows_lives_in_the_brain_not_in_a_door(self) -> None:
        from travel_a2ui.brain import macros

        assert callable(macros.without_the_rows)

    def test_and_neither_door_keeps_its_own_copy(self) -> None:
        import inspect

        from travel_a2ui.doors import live
        from travel_a2ui.doors.interactions import turn

        for door in (live, turn):
            source = inspect.getsource(door)
            assert "without_the_rows" in source, f"{door.__name__} stopped withholding rows"
            # The tell of a second implementation: a door deciding for itself
            # which key holds the rows.
            assert 'result.get("items")' not in source, (
                f"{door.__name__} has grown its own row-stripping again"
            )

    def test_and_it_is_keyed_off_the_table_that_files_them(self) -> None:
        """The bug was a door naming a key the filing side never used."""
        from travel_a2ui.brain.macros import LANDINGS, WITHHELD

        assert WITHHELD, "nothing is withheld, so the rows are all going to the model"
        for tool, key in WITHHELD.items():
            assert LANDINGS.get(tool, (None, None))[1] == key, (
                f"{tool}: withheld from {key!r}, filed from "
                f"{LANDINGS.get(tool, (None, None))[1]!r}"
            )
