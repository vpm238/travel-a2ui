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

import json
import pathlib
from typing import Any, Iterable, Optional

STRUCTURAL_PROPERTIES = frozenset({"component", "id"})


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

    Properties that do not are marked ``(static)`` in generated signatures — the
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

    def get_function_description(self, name: str) -> Optional[str]:
        schema = self.functions.get(name)
        if not schema:
            return None
        description = schema.get("description")
        return description if isinstance(description, str) else None
