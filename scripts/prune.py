"""Narrowing the catalog the *model* is shown.

The rest of what `tools/skillgen` used to do — crawling the catalog into
signatures, generating the prompt, packaging a SKILL.md — is the SDK's job now
and is done by `scripts/build_skills.py`. This is what upstream does not have.

`A2uiCatalog.with_pruning` narrows components and messages, and this keeps that
signature so the component half is a rename the day it is enough. The function
half is ours, and it came out of measuring rather than guessing: pruning six
components off this catalog saved 1.3 kB, while the function block — mostly
check-rule validators for a `checks=` argument this agent has never once written
— was three times that.

Pruning is a *server-side* operation on the catalog the model reads. Every
renderer keeps its full component registry, so nothing about a Web, Swift or
Kotlin client changes when the agent decides it will never draw a `Video`.
"""

from __future__ import annotations

import copy
import dataclasses
import re
from typing import Any, Iterable, Optional

#: Definitions a catalog publishes rather than merely uses.
#:
#: `anyComponent` and `anyFunction` are the unions every child slot and every
#: function call validates against, and `theme` is read by the host, not by a
#: schema. Nothing inside the catalog points at them — they are pointed at from
#: outside it — so a reachability sweep that treats "unreferenced" as "unused"
#: deletes exactly the three definitions that make the catalog a catalog.
ENTRY_POINT_DEFS = frozenset({"anyComponent", "anyFunction", "theme"})


def collect_refs(node: Any) -> set[str]:
    """Every ``$ref`` string anywhere under ``node``."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            found |= collect_refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= collect_refs(item)
    return found


def prune_defs_by_reachability(
    defs: dict[str, Any], root_def_names: Iterable[str]
) -> dict[str, Any]:
    """Keeps only the ``$defs`` reachable from the roots.

    A definition survives if something still standing points at it, directly or
    through another surviving definition. Dropping a component whose schema was
    the only thing referencing a shared type should take that type with it —
    otherwise pruning removes the signature the model reads and leaves behind
    the bytes it costs.
    """
    reachable: set[str] = set()
    queue = [name for name in root_def_names if name in defs]

    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for ref in collect_refs(defs[name]):
            target = ref.split("/")[-1] if "#/$defs/" in ref else None
            if target and target in defs and target not in reachable:
                queue.append(target)

    return {name: schema for name, schema in defs.items() if name in reachable}


def with_pruning(
    schema: dict[str, Any],
    allowed_components: Optional[Iterable[str]] = None,
    allowed_messages: Optional[Iterable[str]] = None,
    allowed_functions: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Returns a copy of a catalog holding only the named components.

    A port of ``A2uiCatalog.with_pruning`` from the Python agent SDK, kept to the
    same signature so that adopting the upstream one is a rename. Pruning is a
    *server-side* operation on the catalog the model is shown: the renderers keep
    their full component registries, so nothing about a client changes when the
    agent decides it will never draw a ``Video``.

    ``allowed_functions`` is the one argument upstream does not have. It is here
    because measuring beat guessing: pruning six components off this catalog
    saved 1.3 kB, while the function block — most of it check-rule validators for
    a ``checks=`` argument this agent never writes — was three times that. When
    upstream grows the same axis this becomes a rename too; until then it is the
    documented local extension.

    Unknown names are ignored rather than raising. The catalog is the authority
    on what exists, and an allow-list that outlives a renamed component should
    narrow the prompt, not break the build.
    """
    if allowed_components is None and allowed_messages is None and allowed_functions is None:
        return schema

    pruned = copy.deepcopy(schema)

    if allowed_components is not None:
        allowed = set(allowed_components)
        components = pruned.get("components")
        if isinstance(components, dict):
            pruned["components"] = {
                name: value for name, value in components.items() if name in allowed
            }

        # `anyComponent` is the union every child slot points at. Leaving a
        # dropped component listed there would keep its schema reachable and
        # advertise a component the prompt no longer documents.
        defs = pruned.get("$defs")
        if isinstance(defs, dict):
            any_component = defs.get("anyComponent")
            if isinstance(any_component, dict) and isinstance(any_component.get("oneOf"), list):
                any_component["oneOf"] = [
                    entry
                    for entry in any_component["oneOf"]
                    if not (
                        isinstance(entry, dict)
                        and isinstance(entry.get("$ref"), str)
                        and entry["$ref"].startswith("#/components/")
                        and entry["$ref"].split("/")[-1] not in allowed
                    )
                ]

    if allowed_functions is not None:
        allowed_function_names = set(allowed_functions)
        functions = pruned.get("functions")
        if isinstance(functions, dict):
            pruned["functions"] = {
                name: value
                for name, value in functions.items()
                if name in allowed_function_names
            }
        defs = pruned.get("$defs")
        if isinstance(defs, dict):
            any_function = defs.get("anyFunction")
            if isinstance(any_function, dict) and isinstance(any_function.get("oneOf"), list):
                any_function["oneOf"] = [
                    entry
                    for entry in any_function["oneOf"]
                    if not (
                        isinstance(entry, dict)
                        and isinstance(entry.get("$ref"), str)
                        and entry["$ref"].startswith("#/functions/")
                        and entry["$ref"].split("/")[-1] not in allowed_function_names
                    )
                ]

    if allowed_messages is not None:
        allowed_message_names = set(allowed_messages)
        for key in ("s2cSchema", "s2c_schema"):
            block = pruned.get(key)
            if isinstance(block, dict) and isinstance(block.get("properties"), dict):
                block["properties"] = {
                    name: value
                    for name, value in block["properties"].items()
                    if name in allowed_message_names
                }

    defs = pruned.get("$defs")
    if isinstance(defs, dict):
        # Roots are whatever the surviving catalog still points at, minus the
        # definitions themselves — a def referenced only by a pruned sibling is
        # not a root.
        outside = {key: value for key, value in pruned.items() if key != "$defs"}
        roots = {ref.split("/")[-1] for ref in collect_refs(outside) if "#/$defs/" in ref}
        roots |= ENTRY_POINT_DEFS
        pruned["$defs"] = prune_defs_by_reachability(defs, roots)

    return pruned


def _sub_schemas(schema: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield schema
    for sub in schema.get("allOf", []) or []:
        if isinstance(sub, dict):
            yield sub


def find_enum(schema: Any) -> Optional[list[str]]:
    """Finds an ``enum`` anywhere in a property schema's union branches."""
    if not isinstance(schema, dict):
        return None
    if isinstance(schema.get("enum"), list):
        return schema["enum"]
    for key in ("oneOf", "anyOf", "allOf"):
        branch = schema.get(key)
        if isinstance(branch, list):
            for sub in branch:
                found = find_enum(sub)
                if found:
                    return found
    return None


def allows_databinding(schema: Any) -> bool:
    """True when a property accepts a ``$path`` binding instead of a literal.

    Properties that do not are marked ``(static only)`` in generated signatures — the
    single most common compile failure a model hits, so it is worth the tokens.
    """
    if not isinstance(schema, dict):
        return False
    ref = schema.get("$ref")
    if isinstance(ref, str) and (
        "DataBinding" in ref or "Dynamic" in ref or "ChildList" in ref
    ):
        return True
    for key in ("oneOf", "anyOf", "allOf"):
        branch = schema.get(key)
        if isinstance(branch, list):
            for sub in branch:
                if allows_databinding(sub):
                    return True
    return False


def is_component_id(schema: Any) -> bool:
    """True when a property holds a component id rather than a value."""
    return (
        isinstance(schema, dict)
        and isinstance(schema.get("$ref"), str)
        and "ComponentId" in schema["$ref"]
    )


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
