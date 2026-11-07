"""What a renderer sends the agent, read as A2UI v1.0.

A request from a client carries, beside anything the traveller typed:

    a2ui        renderer-to-agent messages: `{version, action}` for a press and
                `{version, error}` for something the renderer refused
    metadata    `a2uiRendererCapabilities` (which catalogs it renders) and
                `a2uiRendererDataModel` (the data model of every surface that
                asked to send one), on every request
    surfaces    the surface ids the renderer holds, so the agent's mirror of
                them can be reconciled

Each message is validated with the A2UI SDK's own models
(`a2ui.core.schema.v1_0`). Anything that does not validate is reported back
rather than guessed at. The transport around them (SSE for a typed turn, a
WebSocket for a call) is this app's; see `docs/transport.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from a2ui.core.schema.v1_0.renderer_capabilities import A2uiRendererCapabilities
from a2ui.core.schema.v1_0.renderer_to_agent import (
    A2uiRendererActionMessage,
    A2uiRendererDataModel,
    A2uiRendererErrorMessage,
)

#: The metadata keys this agent reads. The first is the v1.0 name; the second
#: carries an `A2uiRendererDataModel` message.
CAPABILITIES_KEY = "a2uiRendererCapabilities"
DATA_MODEL_KEY = "a2uiRendererDataModel"


@dataclass
class SurfaceAction:
    """A press, as the renderer reported it."""

    name: str
    surface_id: str
    source_component_id: str = ""
    timestamp: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    #: The event's `userMessage`, with bindings resolved: the press in words.
    user_message: str | None = None
    #: The pressed surface's data model, when it sends one.
    data_model: dict[str, Any] | None = None


@dataclass
class RendererError:
    code: str
    message: str
    surface_id: str | None = None
    path: str | None = None

    def describe(self) -> str:
        where = f' on surface "{self.surface_id}"' if self.surface_id else ""
        at = f" at {self.path}" if self.path else ""
        return f"{self.code}{where}{at}: {self.message}"


@dataclass
class FromRenderer:
    """Everything one request said on the renderer's behalf."""

    actions: list[SurfaceAction] = field(default_factory=list)
    errors: list[RendererError] = field(default_factory=list)
    #: Data models by surface id, from `a2uiRendererDataModel`.
    data_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    capabilities: dict[str, Any] | None = None
    #: Surface ids the renderer holds, or None when it did not say.
    surfaces: list[str] | None = None
    #: What could not be read, as sentences, for the response.
    refused: list[str] = field(default_factory=list)

    @property
    def action(self) -> SurfaceAction | None:
        """The press this turn answers: the last one sent."""
        return self.actions[-1] if self.actions else None


def read(body: dict[str, Any]) -> FromRenderer:
    """The renderer's part of a request body."""
    out = FromRenderer()
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    capabilities = metadata.get(CAPABILITIES_KEY)
    if capabilities is not None:
        try:
            A2uiRendererCapabilities.model_validate(capabilities)
            out.capabilities = capabilities
        except Exception as error:  # noqa: BLE001 - reported, and the defaults stand
            out.refused.append(f"{CAPABILITIES_KEY}: {_first_line(error)}")

    reported = metadata.get(DATA_MODEL_KEY)
    if reported is not None:
        try:
            out.data_model = dict(A2uiRendererDataModel.model_validate(reported).surfaces)
        except Exception as error:  # noqa: BLE001
            out.refused.append(f"{DATA_MODEL_KEY}: {_first_line(error)}")

    for message in body.get("a2ui") or []:
        if not isinstance(message, dict):
            out.refused.append("a renderer message that is not an object")
        elif "action" in message:
            try:
                action = A2uiRendererActionMessage.model_validate(message).action
            except Exception as error:  # noqa: BLE001
                out.refused.append(f"action: {_first_line(error)}")
                continue
            out.actions.append(
                SurfaceAction(
                    name=action.name,
                    surface_id=action.surface_id,
                    source_component_id=action.source_component_id,
                    timestamp=action.timestamp,
                    context=dict(action.context or {}),
                    user_message=action.user_message,
                    data_model=out.data_model.get(action.surface_id),
                )
            )
        elif "error" in message:
            try:
                error = A2uiRendererErrorMessage.model_validate(message).error
            except Exception as problem:  # noqa: BLE001
                out.refused.append(f"error: {_first_line(problem)}")
                continue
            inner = getattr(error, "root", error)
            out.errors.append(
                RendererError(
                    code=str(inner.code),
                    message=str(inner.message),
                    surface_id=getattr(inner, "surface_id", None),
                    path=getattr(inner, "path", None),
                )
            )
        else:
            out.refused.append(f"a renderer message this agent does not take: {sorted(message)}")

    # The data model may have arrived after the action that needed it.
    for action in out.actions:
        if action.data_model is None:
            action.data_model = out.data_model.get(action.surface_id)

    surfaces = body.get("surfaces")
    if isinstance(surfaces, list):
        out.surfaces = [surface for surface in surfaces if isinstance(surface, str)]
    return out


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0][:300] if str(error).strip() else type(error).__name__
