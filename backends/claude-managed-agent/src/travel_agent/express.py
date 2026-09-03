"""Compiling A2UI Express, from Python.

Two implementations, because there are two honest answers today:

**`sdk`** — Google's own `a2ui-agent-sdk`. The canonical compiler, and the
obvious choice. There is a catch, and it is worth stating plainly rather than
discovering at runtime: the published wheel (0.5.0 at time of writing) predates
keyword arguments in Express, so it rejects `Text("Hi", variant="h3")` — which
is what the generated skills teach and what a current model will write. This
module detects that at import and refuses to be selected rather than failing
one turn in three.

**`service`** — `POST /api/compile` on the deployed Worker. That is the same
TypeScript compiler the rest of this project uses, and it is diffed against the
reference implementation by the parity suite, so "not the SDK" does not mean
"not the reference behaviour".

The default picks `sdk` when it is capable and `service` otherwise, so this file
gets shorter and less interesting the moment Google publishes a current wheel.
That is the intended end state.
"""

from __future__ import annotations

import dataclasses
import json
import re
import urllib.error
import urllib.request
from typing import Any, Iterator, Literal, Protocol

A2UI_OPEN = "<a2ui>"
A2UI_CLOSE = "</a2ui>"
VERSION = "v0.9.1"

Backend = Literal["sdk", "service"]


class CompileError(RuntimeError):
    """The Express did not compile. The message names what was wrong."""


class Compiler(Protocol):
    name: Backend

    def compile(self, source: str, surface_id: str, *, is_final: bool = True) -> list[dict[str, Any]]: ...

    def decompile(self, messages: list[dict[str, Any]]) -> str: ...


# --------------------------------------------------------------------------
# The reference SDK
# --------------------------------------------------------------------------


def sdk_capabilities() -> dict[str, Any]:
    """What the installed a2ui SDK can actually do.

    Checked by compiling one representative program rather than by reading a
    version number: a version tells you which release is installed, not whether
    a checkout on `PYTHONPATH` supports the syntax you are about to send it.
    """
    try:
        from a2ui.core.catalog import Catalog  # noqa: F401
        from a2ui.inference_formats.experimental.express.compiler import (  # noqa: F401
            ExpressCompiler,
        )
    except ImportError as error:
        return {"installed": False, "reason": str(error), "keyword_args": False, "versioned": False}

    import inspect

    versioned = "version" in inspect.signature(ExpressCompiler.compile).parameters
    return {"installed": True, "keyword_args": None, "versioned": versioned}


@dataclasses.dataclass
class SdkCompiler:
    """Google's reference compiler, driven directly."""

    catalog_schema: dict[str, Any]
    catalog_id: str
    name: Backend = "sdk"

    def __post_init__(self) -> None:
        from a2ui.core.catalog import Catalog
        from a2ui.inference_formats.experimental.express.compiler import ExpressCompiler
        from a2ui.inference_formats.experimental.express.parser import ExpressParser

        self._catalog = Catalog.from_json(
            catalog_schema=self.catalog_schema,
            spec_version=VERSION,
            catalog_id=self.catalog_id,
        )

        import inspect

        self._versioned = "version" in inspect.signature(ExpressCompiler.compile).parameters
        self._compiler = (
            ExpressCompiler(self._catalog, version=VERSION)
            if "version" in inspect.signature(ExpressCompiler.__init__).parameters
            else ExpressCompiler(self._catalog)
        )
        self._parser_factory = ExpressParser

    def compile(self, source: str, surface_id: str, *, is_final: bool = True) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "surface_id": surface_id,
            "catalog_id": self.catalog_id,
            "is_final": is_final,
        }
        if self._versioned:
            kwargs["version"] = VERSION
        try:
            result = self._compiler.compile(source, **kwargs)
        except Exception as error:  # the SDK raises several unrelated types
            raise CompileError(str(error)) from error
        # Older releases return a single v1.0 envelope; newer ones a list.
        return result if isinstance(result, list) else [result]

    def decompile(self, messages: list[dict[str, Any]]) -> str:
        parser = self._parser_factory(self._catalog)
        return "\n".join(parser.decompile(message) for message in messages if message)


def sdk_supports_current_grammar(catalog_schema: dict[str, Any], catalog_id: str) -> bool:
    """Compiles one keyword-argument program to see whether the SDK is current."""
    try:
        compiler = SdkCompiler(catalog_schema, catalog_id)
        compiler.compile('root = Text("Hi", variant="h3")', "probe")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# The compile service
# --------------------------------------------------------------------------


@dataclasses.dataclass
class ServiceCompiler:
    """`POST /api/compile` on the deployed Worker.

    Uses `urllib` rather than a client library on purpose: this has to work in
    any Python environment, and the request is one JSON POST.
    """

    base_url: str
    catalog_id: str
    timeout: float = 20.0
    name: Backend = "service"

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                raise CompileError(json.loads(detail).get("error", detail))
            except (ValueError, AttributeError):
                raise CompileError(f"{error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise CompileError(
                f"Could not reach the compile service at {self.base_url}: {error.reason}"
            ) from error

    def compile(self, source: str, surface_id: str, *, is_final: bool = True) -> list[dict[str, Any]]:
        body = self._post(
            "/api/compile",
            {
                "source": source,
                "surfaceId": surface_id,
                "catalogId": self.catalog_id,
                "isFinal": is_final,
            },
        )
        return list(body.get("messages", []))

    def decompile(self, messages: list[dict[str, Any]]) -> str:
        return str(self._post("/api/decompile", {"messages": messages}).get("express", ""))


def make_compiler(
    catalog_schema: dict[str, Any],
    catalog_id: str,
    *,
    prefer: Backend | None = None,
    service_url: str | None = None,
) -> Compiler:
    """Picks a compiler: the SDK when it is current, otherwise the service."""
    if prefer == "sdk":
        return SdkCompiler(catalog_schema, catalog_id)
    if prefer == "service":
        if not service_url:
            raise ValueError("The 'service' compiler needs a base URL.")
        return ServiceCompiler(service_url, catalog_id)

    if sdk_supports_current_grammar(catalog_schema, catalog_id):
        return SdkCompiler(catalog_schema, catalog_id)
    if service_url:
        return ServiceCompiler(service_url, catalog_id)

    raise RuntimeError(
        "No usable A2UI Express compiler.\n"
        "The installed a2ui-agent-sdk cannot compile the current grammar "
        "(keyword arguments are rejected), and no compile service URL was given.\n"
        "Either install a current SDK, or pass --compile-service "
        "https://<your-worker>.workers.dev"
    )


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


def _dangling_prefix(text: str, token: str) -> int:
    """Longest tail of `text` that is also a proper prefix of `token`."""
    for length in range(min(len(text), len(token) - 1), 0, -1):
        if text.endswith(token[:length]):
            return length
    return 0


@dataclasses.dataclass
class StreamEvent:
    kind: Literal["text", "ui", "error"]
    delta: str = ""
    messages: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    done: bool = False
    message: str = ""


class ExpressStream:
    """Splits a model's output into prose and compiled surfaces, as it arrives.

    A mirror of the TypeScript `ExpressStreamParser`, and for the same reason:
    the surface should paint while the model is still typing, and Express is the
    format that allows it because a partial program is still a program.

    The `service` compiler makes a network call per recompile, so it recompiles
    on block boundaries only; the in-process `sdk` compiler recompiles on every
    chunk.
    """

    def __init__(self, compiler: Compiler, surface_id: str) -> None:
        self._compiler = compiler
        self._surface_id = surface_id
        self._buffer = ""
        self._inside = False
        self._block = ""
        self._last_emitted = ""
        self._incremental = compiler.name != "service"

    def push(self, chunk: str) -> Iterator[StreamEvent]:
        self._buffer += chunk

        while True:
            if not self._inside:
                index = self._buffer.find(A2UI_OPEN)
                if index == -1:
                    hold = _dangling_prefix(self._buffer, A2UI_OPEN)
                    emit = self._buffer[: len(self._buffer) - hold]
                    self._buffer = self._buffer[len(self._buffer) - hold :]
                    if emit:
                        yield StreamEvent("text", delta=emit)
                    return
                prose = self._buffer[:index]
                if prose:
                    yield StreamEvent("text", delta=prose)
                self._buffer = self._buffer[index + len(A2UI_OPEN) :]
                self._inside = True
                self._block = ""
                self._last_emitted = ""
                continue

            index = self._buffer.find(A2UI_CLOSE)
            if index == -1:
                hold = _dangling_prefix(self._buffer, A2UI_CLOSE)
                self._block += self._buffer[: len(self._buffer) - hold]
                self._buffer = self._buffer[len(self._buffer) - hold :]
                if self._incremental:
                    event = self._compile(done=False)
                    if event:
                        yield event
                return

            self._block += self._buffer[:index]
            self._buffer = self._buffer[index + len(A2UI_CLOSE) :]
            self._inside = False
            event = self._compile(done=True)
            if event:
                yield event

    def end(self) -> Iterator[StreamEvent]:
        if self._inside:
            # The model stopped mid-block. An unterminated block usually still
            # describes a complete tree, so compile it rather than discard it.
            self._block += self._buffer
            self._buffer = ""
            self._inside = False
            event = self._compile(done=True)
            if event:
                yield event
        elif self._buffer:
            yield StreamEvent("text", delta=self._buffer)
            self._buffer = ""

    def _compile(self, *, done: bool) -> StreamEvent | None:
        source = self._block
        if not source.strip():
            return None
        if not done and source == self._last_emitted:
            return None
        self._last_emitted = source

        try:
            messages = self._compiler.compile(source, self._surface_id, is_final=done)
            return StreamEvent("ui", messages=messages, done=done)
        except CompileError as error:
            # Mid-stream failures are expected: half a constructor is not valid
            # Express. Only a failure on the finished block is worth reporting.
            if not done:
                return None
            return StreamEvent("error", message=str(error))


SENTINEL_RE = re.compile(rf"{re.escape(A2UI_OPEN)}(.*?){re.escape(A2UI_CLOSE)}", re.DOTALL)


def extract_blocks(text: str) -> list[str]:
    """Every complete `<a2ui>` block in a finished message."""
    return [match.group(1) for match in SENTINEL_RE.finditer(text)]
