"""What a data binding looks like on the wire, in one place.

A component property is one of four things, and the one that matters here is
the binding: a pointer into the surface's data model, which is how a control
opens pre-filled and how a press sends back what somebody typed.

    v0.9    {"path": "/trip/origin"}
    v1.0    {"@path": "/trip/origin"}

That `@` is the whole of 1.0's reserved-prefix rule: `@path` for a binding,
`@call` for a function call, `@index` for the position in a list template. The
point of the rule is that a plain object with a `path` key is now ordinary
data, so a renderer can tell a binding from a dictionary that happens to have
the word in it — which, before, it could not.

Four passes read bindings (the control check, the commit binder, the derived
labels, the surface skeleton) and each had its own `value.get("path")`. At
0.9 that was duplication; at 1.0 it is four independent chances to keep
speaking the old protocol while claiming the new one — and a binding the
renderer does not recognise is not an error, it is a control that silently
opens empty. So they all ask here instead.

The spelling follows the catalog: `brain/catalog.py` reads `protocolVersion`
off the generated catalog, and this reads it off that. There is no third copy
of the version in the server.
"""

from __future__ import annotations

from typing import Any

from .catalog import CATALOG_VERSION

#: The key a binding is written under, at the version this catalog declares.
PATH_KEY = "@path" if CATALOG_VERSION >= "1.0" else "path"

#: And the one a function call is written under. Same rule, same reason.
CALL_KEY = "@call" if CATALOG_VERSION >= "1.0" else "call"

#: Both spellings, for reading. A pass reads whatever arrives — the model's
#: block, a skeleton the host built, a golden recorded before the upgrade —
#: and only ever *writes* the current one.
_READ_PATH = ("@path", "path")


def is_binding(value: Any) -> bool:
    """True when this property is a pointer into the data model.

    `componentId` excludes a list template, which carries a path too and means
    something else entirely: "repeat this component for each item at that
    path", not "read the value there".
    """
    return (
        isinstance(value, dict)
        and any(isinstance(value.get(key), str) for key in _READ_PATH)
        and "componentId" not in value
    )


def path_of(value: Any) -> str | None:
    """The pointer this binding names, whichever spelling it arrived in."""
    if not isinstance(value, dict):
        return None
    for key in _READ_PATH:
        found = value.get(key)
        if isinstance(found, str):
            return found
    return None


def bind(path: str) -> dict[str, str]:
    """A binding to that pointer, written the way this protocol spells it."""
    return {PATH_KEY: path}
