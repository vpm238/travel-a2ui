"""Turns that say what they are about to do, and then end.

A model told not to answer "Let me find some flights for you" with nothing
drawn still does it, in both doors, often enough that it is not a wording
problem. So both doors hand such a turn back once, with what it actually did.
The check lives in the brain so the two doors share it rather than one
importing the other.
"""

from __future__ import annotations

import re

#: Saying you are about to do the thing, instead of doing it.
#:
#: Deliberately narrow. This only decides whether a turn that produced *nothing*
#: gets handed back once, so a false positive costs one extra round and a false
#: negative costs nothing that is not already broken. What it must not do is
#: fire on an ordinary answer — "there are four nonstops" is a turn that did its
#: job, and re-prodding it would talk over the traveller.
PROMISE = re.compile(
    r"\b("
    # "let me know" is an invitation, not a promise to act — and it is how a
    # perfectly good turn ends. Excluding it is not a nicety: a false positive
    # here fires a retry over a turn that already did its job.
    r"let me\b(?!\s+know)|let'?s\s+(set|get|start|find|look|pick|sort)|"
    r"i'?ll\s+(find|look|check|pull|search|get|see|set|map|record|put)|"
    r"i'?m\s+(going to|about to|looking|finding|checking|searching|pulling)|"
    r"one (moment|second)|just a (moment|second)|hold on|"
    r"give me a (moment|second)|searching now|looking (that )?up"
    r")",
    re.IGNORECASE,
)


def promised(said: str) -> bool:
    """True when the turn announced an intention rather than acting on one."""
    return bool(said.strip()) and bool(PROMISE.search(said))


#: Handed back to a spoken turn that promised and called nothing.
#:
#: Phrased as the traveller, because that is the only role that channel has to
#: speak in — and phrased as a fact about the screen rather than a scolding,
#: since what needs to change is the next action, not the model's feelings about
#: the last one.
SPOKEN_NUDGE = (
    "[system] You said you would look, and then called nothing — the screen in "
    "front of me has not changed. Do it now in this turn: call the lookup, then "
    "the tool that draws the result, then say one short sentence about what is "
    "on screen. Do not say you are about to; there is no turn after this one to "
    "do it in."
)

#: Handed back to a typed turn that promised and drew nothing.
#:
#: Names the controls, because the turn this fires on is almost always the
#: opening one — somebody said where they want to go, and what is missing is the
#: dates and the party.
TYPED_NUDGE = (
    "You said what you were about to do and then did not do it: no tool ran and "
    "nothing was drawn, so the traveler is looking at a sentence and an empty "
    "space.\n\n"
    "Do it now, in this turn. If values are missing, draw the controls for them "
    "in one surface — a DateRangePicker for the dates, one TravelerCounter per "
    "hop labelled by hop, an AirportPicker for any airport you cannot place — with "
    "a single commit button binding every path it edits. If a lookup is what is "
    "needed, call it and draw the result.\n\n"
    "Only the <a2ui> block. Do not repeat the sentence, and do not write another "
    "one saying you are about to."
)
