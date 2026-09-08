"""Schema crawler for A2UI catalogs.

A port of ``CatalogSchemaHelper`` from google/a2ui's Python agent SDK. It is
ported rather than imported for one reason: the reference implementation pulls
in the whole ADK dependency tree, and a skill generator that runs in CI should
not need fifty packages to read a JSON file. ``tests/test_sdk_parity.py``
asserts this produces the same signatures as the reference when the SDK *is*
installed, which is what keeps the shortcut honest.

The load-bearing detail: **declaration order is the API.** A2UI Express is a
positional notation, so the order properties appear in the catalog JSON is the
order the model must pass them in. Nothing is sorted here.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any, Iterable, Optional

STRUCTURAL_PROPERTIES = frozenset({"component", "id"})

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


class CatalogHelper:
    """Reads a catalog JSON schema into the shapes a prompt generator needs."""

    def __init__(self, schema: dict[str, Any]):
        self.schema = schema
        self.components: dict[str, dict[str, Any]] = schema.get("components", {}) or {}
        self.functions: dict[str, dict[str, Any]] = schema.get("functions", {}) or {}

        self.component_properties: dict[str, list[str]] = {}
        self.component_required: dict[str, list[str]] = {}
        self.component_checkable: dict[str, bool] = {}
        self._component_enums: dict[tuple[str, str], list[str]] = {}
        self.function_properties: dict[str, list[str]] = {}
        self.function_required: dict[str, list[str]] = {}

        self._load()

    @classmethod
    def from_path(cls, path: str | pathlib.Path) -> "CatalogHelper":
        return cls(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))

    def with_pruning(
        self,
        allowed_components: Optional[Iterable[str]] = None,
        allowed_messages: Optional[Iterable[str]] = None,
        allowed_functions: Optional[Iterable[str]] = None,
    ) -> "CatalogHelper":
        """A helper over the same catalog with only the named components.

        Mirrors ``A2uiCatalog.with_pruning`` so the call site does not change
        when the upstream SDK replaces this module.
        """
        return CatalogHelper(
            with_pruning(self.schema, allowed_components, allowed_messages, allowed_functions)
        )

    @property
    def catalog_id(self) -> str:
        return str(self.schema.get("catalogId") or self.schema.get("$id") or "")

    @property
    def description(self) -> str:
        return str(self.schema.get("description") or "")

    @property
    def instructions(self) -> str:
        return str(self.schema.get("instructions") or "")

    def _load(self) -> None:
        for name, schema in self.components.items():
            properties: dict[str, Any] = {}
            required: list[str] = []
            checkable = False

            for sub in _sub_schemas(schema):
                ref = sub.get("$ref")
                if isinstance(ref, str) and "Checkable" in ref:
                    checkable = True
                props = sub.get("properties")
                if isinstance(props, dict):
                    properties.update(props)
                    for key, value in props.items():
                        enum_values = find_enum(value)
                        if enum_values:
                            self._component_enums[(name, key)] = enum_values
                req = sub.get("required")
                if isinstance(req, list):
                    required.extend(req)

            ordered = [k for k in properties if k not in STRUCTURAL_PROPERTIES]
            if checkable:
                ordered.append("checks")

            self.component_properties[name] = ordered
            self.component_required[name] = required
            self.component_checkable[name] = checkable

        for name, schema in self.functions.items():
            properties: dict[str, Any] = {}
            required = []
            for sub in _sub_schemas(schema):
                props = sub.get("properties")
                if not isinstance(props, dict):
                    continue
                args = props.get("args")
                if not isinstance(args, dict):
                    continue
                if isinstance(args.get("properties"), dict):
                    properties.update(args["properties"])
                if isinstance(args.get("required"), list):
                    required.extend(args["required"])
            self.function_properties[name] = list(properties)
            self.function_required[name] = required

    def get_component_properties(self, name: str) -> list[str]:
        return self.component_properties.get(name, [])

    def get_component_required(self, name: str) -> list[str]:
        return self.component_required.get(name, [])

    def get_function_properties(self, name: str) -> list[str]:
        return self.function_properties.get(name, [])

    def get_function_required(self, name: str) -> list[str]:
        return self.function_required.get(name, [])

    def get_property_enum(self, component: str, prop: str) -> Optional[list[str]]:
        return self._component_enums.get((component, prop))

    def get_property_schema(self, component: str, prop: str) -> Optional[dict[str, Any]]:
        schema = self.components.get(component)
        if not schema:
            return None
        for sub in _sub_schemas(schema):
            props = sub.get("properties")
            if isinstance(props, dict) and prop in props:
                return props[prop]
        return None

    def get_function_property_schema(self, fn: str, prop: str) -> Optional[dict[str, Any]]:
        schema = self.functions.get(fn)
        if not schema:
            return None
        for sub in _sub_schemas(schema):
            props = sub.get("properties")
            if not isinstance(props, dict):
                continue
            args = props.get("args")
            if isinstance(args, dict) and isinstance(args.get("properties"), dict):
                if prop in args["properties"]:
                    return args["properties"][prop]
        return None

    def get_component_description(self, name: str) -> Optional[str]:
        schema = self.components.get(name)
        if not schema:
            return None
        if isinstance(schema.get("description"), str):
            return schema["description"]
        for sub in schema.get("allOf", []) or []:
            if isinstance(sub, dict) and isinstance(sub.get("description"), str):
                return sub["description"]
        return None

    def check_functions(self) -> list[str]:
        """Functions usable as a `?rule` guard: the ones that return a boolean.

        A catalog can legitimately have none — pruning the validators off a
        travel agent leaves exactly that — and a prompt that still teaches
        `?required` then documents a syntax with nothing to write in it.
        """
        found: list[str] = []
        for name, schema in self.functions.items():
            for sub in _sub_schemas(schema):
                props = sub.get("properties")
                if not isinstance(props, dict):
                    continue
                returns = props.get("returnType")
                if isinstance(returns, dict) and returns.get("const") == "boolean":
                    found.append(name)
                    break
        return found

    def get_function_description(self, name: str) -> Optional[str]:
        schema = self.functions.get(name)
        if not schema:
            return None
        description = schema.get("description")
        return description if isinstance(description, str) else None
