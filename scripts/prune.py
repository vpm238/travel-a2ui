"""Which worked examples the model is shown, once the catalog is pruned.

Pruning itself is the SDK's: `scripts/build_skills.py` narrows the catalog with
`ComponentPruningTransformer` and `FunctionPruningTransformer`. What upstream
does not do is drop the examples that call something pruned, and an example
teaching a call the prompt no longer documents is worse than no example. That
is this file.

Pruning is a *server-side* operation on the catalog the model reads. Every
renderer keeps its full component registry, so nothing about the React or the
Flutter client changes when the agent decides it will never draw a `Video`.
"""

from __future__ import annotations

import dataclasses
import re

#: `Name(` at the head of a call — how a component is spelled in Express.
_CALL = re.compile(r"\b([A-Z][A-Za-z0-9]*)\s*\(")

#: `?required`, `?email("…")` — how a check rule is spelled.
_RULE = re.compile(r"\?([a-z][A-Za-z0-9]*)")

#: `formatCurrency(` — a catalog function called for its value.
_FUNCTION = re.compile(r"\b([a-z][A-Za-z0-9]*)\s*\(")


@dataclasses.dataclass(frozen=True)
class Vocabulary:
    """What the pruned catalog still offers, against what it ever offered.

    Both halves are needed. `allowed` alone cannot tell a pruned component from
    a name that was never in this catalog — `Event(`, `_template(`, a component
    borrowed from another catalog — and rejecting those would throw away every
    example.
    """

    allowed_components: set[str]
    known_components: set[str]
    allowed_functions: set[str]
    known_functions: set[str]


def uses_only(source: str, vocabulary: Vocabulary) -> bool:
    """True when everything the example calls survived pruning.

    Components and functions both: an example teaching `?required` after the
    validators were pruned is an example teaching a call the prompt no longer
    documents, which is the same failure whichever case the name starts with.
    """
    for name in _CALL.findall(source):
        if name in vocabulary.known_components and name not in vocabulary.allowed_components:
            return False
    for name in _RULE.findall(source) + _FUNCTION.findall(source):
        if name in vocabulary.known_functions and name not in vocabulary.allowed_functions:
            return False
    return True
