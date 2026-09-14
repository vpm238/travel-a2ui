"""The MCP endpoint, driven as a protocol rather than as functions.

Calling `call_tool` directly would test the parts that already have tests and
miss everything that actually goes wrong with an MCP server: a notification
answered when it should be silent, a batch returned as a single object, an
`initialize` that agrees to a version nobody asked for, an error returned as a
protocol fault when it was an outcome. So every test here sends a JSON-RPC
document and reads a JSON-RPC document back.

The one that matters most is the shape of a tool result. A host does not look
for HTML inside a result — it reads a `ui://` resource once as a *template* and
forwards results to it — and getting that wrong is what made an earlier version
of this plugin render nothing at all, silently, in a host that was behaving
correctly.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from travel_a2ui.doors.plugin import (
    A2UI_MIME,
    APP_MIME,
    APP_URI,
    PROTOCOL_VERSION,
    PROTOCOL_VERSIONS,
    TOOLS,
    UI_EXTENSION,
    RenderContext,
    handle,
    tool_examples,
)
from travel_a2ui.brain.providers.fixture import FixtureProvider

TODAY = "2027-03-01"


def context(view: str = "app") -> RenderContext:
    return RenderContext(
        view=view,
        origin="https://travel.example",
        provider=FixtureProvider(),
        today=TODAY,
    )


def rpc(body: Any, view: str = "app") -> tuple[Any, int]:
    return asyncio.run(handle(body, context(view)))


def call(method: str, params: dict | None = None, request_id: Any = 1, view: str = "app"):
    body, _ = rpc(
        {"jsonrpc": "2.0", "id": request_id, "method": method, **({"params": params} if params else {})},
        view,
    )
    return body


class TestTheHandshake:
    def test_it_speaks_the_version_the_client_asked_for(self) -> None:
        """A stateless server that announces its own favourite ends up on an
        older contract than either side wanted."""
        for asked in PROTOCOL_VERSIONS:
            result = call("initialize", {"protocolVersion": asked})["result"]
            assert result["protocolVersion"] == asked

    def test_an_unknown_version_falls_back_to_ours(self) -> None:
        result = call("initialize", {"protocolVersion": "1999-01-01"})["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION

    def test_it_advertises_the_ui_extension(self) -> None:
        """Which is how a host knows it can render these results at all."""
        capabilities = call("initialize", {})["result"]["capabilities"]
        assert capabilities["extensions"][UI_EXTENSION]["mimeTypes"] == [APP_MIME]

    def test_the_instructions_tell_the_host_to_compose_rather_than_describe(self) -> None:
        instructions = call("initialize", {})["result"]["instructions"]
        assert "not text" in instructions
        assert "render_a2ui_express" in instructions
        assert "Prefer that over describing an interface in prose" in instructions


class TestNotifications:
    @pytest.mark.parametrize(
        "method", ["notifications/initialized", "notifications/cancelled"]
    )
    def test_a_notification_gets_no_reply_and_a_202(self, method: str) -> None:
        body, status = rpc({"jsonrpc": "2.0", "method": method})
        assert body is None
        assert status == 202

    def test_an_unknown_notification_is_still_silent(self) -> None:
        """No id means no reply, whatever the method was.

        Answering a notification with an error is a protocol violation, and the
        host's next move is usually to close the connection.
        """
        body, status = rpc({"jsonrpc": "2.0", "method": "notifications/something-new"})
        assert body is None
        assert status == 202

    def test_an_unknown_request_does_get_an_error(self) -> None:
        body = call("no/such/method")
        assert body["error"]["code"] == -32601


class TestBatches:
    def test_a_batch_comes_back_as_an_array(self) -> None:
        body, status = rpc(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
        )
        assert status == 200
        assert isinstance(body, list) and len(body) == 2
        assert [entry["id"] for entry in body] == [1, 2]

    def test_one_request_comes_back_as_an_object(self) -> None:
        body, _ = rpc({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert isinstance(body, dict)

    def test_a_batch_of_only_notifications_returns_nothing(self) -> None:
        body, status = rpc(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "method": "notifications/cancelled"},
            ]
        )
        assert body is None
        assert status == 202

    def test_a_mixed_batch_returns_only_the_answers(self) -> None:
        body, _ = rpc(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 7, "method": "ping"},
            ]
        )
        assert isinstance(body, list) and len(body) == 1
        assert body[0]["id"] == 7


class TestTools:
    def test_the_plugin_offers_no_prebuilt_layouts(self) -> None:
        """A capable host gets data and a vocabulary, not a menu.

        The six `show_*` tools each return a finished surface, and offering them
        alongside the generative path was self-defeating in a way that only
        shows up in behaviour: given both, a host takes the one-call path every
        time, because it is one call. The compose path then never runs, and a
        demo whose entire thesis is that a model composes interfaces spends its
        life picking from six.

        The builders are not gone — the voice relay calls `build_surface`
        directly, where composing Express mid-sentence would cost latency a call
        does not have. They are simply not offered here.
        """
        listed = [tool["name"] for tool in call("tools/list")["result"]["tools"]]
        assert not [name for name in listed if name.startswith("show_")], listed
        assert "render_a2ui_express" in listed
        assert "get_a2ui_component_reference" in listed
        assert "search_flights" in listed

    def test_the_compiler_is_listed_with_a_view(self) -> None:
        """`render_a2ui_express` draws, so it carries the app resource."""
        listed = {tool["name"]: tool for tool in call("tools/list")["result"]["tools"]}
        entry = listed["render_a2ui_express"]
        assert entry["_meta"]["ui"]["resourceUri"] == APP_URI

    def test_the_data_tools_are_listed_and_draw_nothing(self) -> None:
        from travel_a2ui.brain.tools import mcp_data_tools

        listed = {tool["name"]: tool for tool in call("tools/list")["result"]["tools"]}
        for tool in mcp_data_tools():
            entry = listed[tool["name"]]
            assert "ui" not in (entry.get("_meta") or {}), (
                f"{tool['name']} returns data, not a surface"
            )

    @pytest.mark.parametrize("name", [tool["name"] for tool in TOOLS])
    def test_every_shipped_example_actually_works(self, name: str) -> None:
        """The bug this exists for: the headline example omitted the date
        `show_flight_options` requires, so the first button anyone pressed in
        the MCP console answered with a refusal, on the deployed site, for as
        long as that console had existed.
        """
        import datetime as _dt

        example = tool_examples(_dt.date.fromisoformat(TODAY))[name]
        result = call("tools/call", {"name": name, "arguments": example})["result"]
        assert result.get("isError") is not True, f"{name}: {result['content'][0]['text']}"

    def test_an_unknown_tool_is_a_protocol_error(self) -> None:
        """Unlike a refusal: the host asked for something that does not exist."""
        body = call("tools/call", {"name": "show_nothing", "arguments": {}})
        assert body["error"]["code"] == -32602

    def test_a_refusal_is_a_result_and_not_a_protocol_error(self) -> None:
        """The call worked. What came back is something the model must act on.

        A JSON-RPC error would tell the host this server is broken, which it is
        not, and the model would never see the sentence explaining what to ask.
        """
        body = call("tools/call", {"name": "show_flight_options", "arguments": {"destination": "Madrid"}})
        assert "error" not in body
        result = body["result"]
        assert result["isError"] is True
        assert "$/trip/startDate" in result["content"][0]["text"]

    def test_the_reference_tool_hands_back_the_vocabulary(self) -> None:
        """What makes the layouts generative rather than a menu of six."""
        result = call("tools/call", {"name": "get_a2ui_component_reference", "arguments": {}})["result"]
        assert result["isError"] is False
        assert len(result["structuredContent"]["components"]) > 20
        assert "Express" in result["content"][0]["text"]

    def test_express_the_host_wrote_is_compiled_and_errors_are_explained(self) -> None:
        body = call(
            "tools/call",
            {
                "name": "render_a2ui_express",
                "arguments": {"source": "root = NoSuchComponent(", "surfaceId": "mcp"},
            },
        )
        result = body["result"]
        assert result["isError"] is True
        # The host model wrote it, so it is the host model's to fix — and the
        # error has to name what is wrong, not merely that something is. This
        # asserted the generic "did not compile"; an invented component now
        # comes back named, which is the difference between a message the model
        # can act on and one it can only apologise for.
        said = result["content"][0]["text"]
        assert "NoSuchComponent" in said, said


class TestWhatAToolResultCarries:
    """The shape that made an earlier version render nothing."""

    @staticmethod
    def _flights(view: str = "app") -> dict[str, Any]:
        return call(
            "tools/call",
            {
                "name": "show_flight_options",
                "arguments": {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12"},
            },
            view=view,
        )["result"]

    def test_a_plain_host_still_gets_something_useful(self) -> None:
        """An MCP tool that is useless in a host with no renderer is a bad tool."""
        result = self._flights()
        assert result["content"][0]["type"] == "text"
        assert "flight option" in result["content"][0]["text"]

    def test_a_host_with_its_own_renderer_gets_the_payload(self) -> None:
        result = self._flights()
        resource = result["content"][1]["resource"]
        assert resource["mimeType"] == A2UI_MIME
        messages = json.loads(resource["text"])
        assert any("createSurface" in message for message in messages)

    def test_an_mcp_apps_host_reads_it_from_structured_content(self) -> None:
        """Not decoration: the host forwards this to the template, and without
        it the view has nothing to draw."""
        result = self._flights()
        structured = result["structuredContent"]
        assert structured["surfaceId"] == "mcp-flights"
        assert any("createSurface" in message for message in structured["messages"])
        assert result["_meta"]["ui"]["resourceUri"] == APP_URI

    def test_the_legacy_view_inlines_html_instead(self) -> None:
        result = self._flights(view="legacy")
        resource = result["content"][1]["resource"]
        assert resource["mimeType"] == "text/html"
        assert "<!doctype html" in resource["text"].lower()

    def test_the_two_views_are_never_offered_at_once(self) -> None:
        """A host that speaks MCP Apps has already read the template, and would
        then have two candidate views for one result — which it picks is not
        ours to guess."""
        for view, unwanted in (("app", "text/html"), ("legacy", A2UI_MIME)):
            result = self._flights(view=view)
            types = [
                part.get("resource", {}).get("mimeType")
                for part in result["content"]
                if part["type"] == "resource"
            ]
            assert unwanted not in types


class TestResources:
    def test_the_template_is_declared_first(self) -> None:
        resources = call("resources/list")["result"]["resources"]
        assert resources[0]["uri"] == APP_URI
        assert resources[0]["mimeType"] == APP_MIME

    def test_the_template_fetches_nothing(self) -> None:
        """Everything is inlined, so no content policy can break the view."""
        resources = call("resources/list")["result"]["resources"]
        csp = resources[0]["_meta"]["ui"]["csp"]
        assert csp["resourceDomains"] == []
        assert csp["frameDomains"] == []

    def test_the_template_is_html_a_host_can_read(self) -> None:
        body = call("resources/read", {"uri": APP_URI})
        content = body["result"]["contents"][0]
        assert content["mimeType"] == APP_MIME
        text = content["text"]
        assert "<!doctype html" in text.lower()
        assert '<div id="root">' in text

    def test_the_template_actually_contains_the_renderer(self) -> None:
        """The scaffolding is hardcoded, so a check for `<html>` proves nothing.

        If the build output is missing, `app_template` composes a perfectly
        well-formed page with an empty `<script>` — which renders a blank frame
        inside the host and reports no error anywhere. This is the assertion
        that notices.
        """
        text = call("resources/read", {"uri": APP_URI})["result"]["contents"][0]["text"]
        script = text.split("<script>", 1)[1].split("</script>", 1)[0]
        style = text.split("<style>", 1)[1].split("</style>", 1)[0]
        assert len(script) > 10_000, "the renderer bundle is not in the template"
        assert len(style) > 1_000, "the stylesheet is not in the template"

    def test_the_bundle_cannot_close_the_script_block_early(self) -> None:
        """A bundle containing the literal `</script` would end the page there.

        Minifiers produce that inside string literals more often than anyone
        expects, and the result is a half-parsed page rather than an error.
        """
        text = call("resources/read", {"uri": APP_URI})["result"]["contents"][0]["text"]
        body = text.split("<script>", 1)[1]
        assert body.count("</script>") == 1, "exactly one, and it is the closing tag"

    def test_the_catalog_is_readable(self) -> None:
        body = call("resources/read", {"uri": "a2ui://catalog/travel"})
        catalog = json.loads(body["result"]["contents"][0]["text"])
        assert len(catalog["components"]) > 20

    def test_the_skill_is_readable(self) -> None:
        body = call("resources/read", {"uri": "a2ui://skill/express"})
        text = body["result"]["contents"][0]["text"]
        assert "Express" in text
        # The body, not the frontmatter: a host reading this wants the
        # instructions, not the metadata.
        assert not text.startswith("---")

    def test_an_unknown_resource_is_an_error(self) -> None:
        body = call("resources/read", {"uri": "a2ui://nope"})
        assert body["error"]["code"] == -32602


class TestPrompts:
    def test_the_express_prompt_is_offered_and_readable(self) -> None:
        assert call("prompts/list")["result"]["prompts"][0]["name"] == "a2ui-express"
        body = call("prompts/get", {"name": "a2ui-express"})
        assert "Express" in body["result"]["messages"][0]["content"]["text"]

    def test_an_unknown_prompt_is_an_error(self) -> None:
        assert call("prompts/get", {"name": "nope"})["error"]["code"] == -32602


def test_a_body_that_is_not_an_object_is_an_invalid_request() -> None:
    body, _ = rpc(["not an object"])
    assert body[0]["error"]["code"] == -32600


def test_the_script_escaping_is_the_whole_safety_story() -> None:
    """The one sequence that can end a `<script>` block early.

    It is why the payload goes into a JSON script block rather than a JS string
    literal: inside `<script type="application/json">` there is exactly one
    thing to escape.
    """
    from travel_a2ui.doors.plugin import _escape_script

    assert _escape_script('</script><img onerror=alert(1)>') == (
        "<\\/script><img onerror=alert(1)>"
    )
    assert "</script" not in _escape_script("a </script> b")


class TestTheFourThingsDrivingItForRealFound:
    """What a real Claude conversation turned up that no unit test had.

    The plugin was installed, asked to plan SFO to New York, and driven through
    the whole path. Every one of these looked fine from inside the repository
    and was obviously wrong the moment somebody used it.
    """

    def test_save_trip_can_record_where_you_are_leaving_from(self) -> None:
        """`origin` was not in the schema at all.

        A trip field the route, the panel and `search_flights` all depend
        on — and the one tool whose job is recording decisions could not accept
        it. "Flying from SFO" was unrecordable; the only way `origin` ever
        reached a trip was a traveller typing it into a control.
        """
        from travel_a2ui.brain.tools import TOOLS

        save = next(tool for tool in TOOLS if tool["name"] == "save_trip")
        assert "origin" in save["input_schema"]["properties"]

    def test_every_trip_field_a_decision_uses_can_be_saved(self) -> None:
        """The general version, so the next omission fails here instead.

        Not every field belongs on the tool — `assumed` and `days` are the
        host's bookkeeping — but a decision the panel offers a Change button for
        is a decision the agent has to be able to write.
        """
        from travel_a2ui.brain import trip as model
        from travel_a2ui.brain.tools import TOOLS

        save = next(tool for tool in TOOLS if tool["name"] == "save_trip")
        offered = set(save["input_schema"]["properties"])
        missing = [key for key in model.DECISIONS if key not in offered]
        assert not missing, f"save_trip cannot record: {missing}"

    def test_the_trip_travels_in_the_arguments(self) -> None:
        """MCP is stateless, so the host carries the trip or nothing does."""
        from travel_a2ui.brain.tools import mcp_data_tools

        for tool in mcp_data_tools():
            assert "trip" in tool["inputSchema"]["properties"], tool["name"]

    def test_saving_over_mcp_actually_saves(self) -> None:
        """It used to answer `{"saved": true}` over an empty trip.

        `ToolContext.save` defaults to a no-op — right for a tool that only
        reads, wrong for the one whose entire job is recording what somebody
        decided. The MCP door never passed one, so `save_trip` reported success,
        returned an empty trip, and listed everything it had just been told as
        still needed.
        """
        body = call(
            "tools/call",
            {
                "name": "save_trip",
                "arguments": {"origin": "SFO", "destination": "New York", "travelers": 2},
            },
        )
        saved = json.loads(body["result"]["content"][0]["text"])
        assert saved["saved"] is True
        assert saved["trip"]["origin"] == "SFO"
        assert saved["trip"]["destination"] == "New York"
        assert "destination" not in saved["stillNeeded"]

    def test_a_carried_trip_comes_back_with_the_new_decision_on_it(self) -> None:
        """Two calls, and the second remembers the first — via the host."""
        def save(arguments: dict) -> dict:
            body = call("tools/call", {"name": "save_trip", "arguments": arguments})
            return json.loads(body["result"]["content"][0]["text"])

        first = save({"origin": "SFO", "destination": "New York"})
        second = save({"trip": first["trip"], "travelers": 3})
        assert second["trip"]["origin"] == "SFO"
        assert second["trip"]["travelers"] == 3

    def test_the_component_reference_carries_the_signatures(self) -> None:
        """Not just the names.

        A host may render `structuredContent` and drop the text — the one this
        was tested against does — so the model asked for the grammar and the
        positional signatures and got a list of thirty component names. Enough
        to know `FlightOption` exists, nothing about what it takes.
        """
        result = call("tools/call", {"name": "get_a2ui_component_reference", "arguments": {}})["result"]
        structured = result["structuredContent"]

        for half in (result["content"][0]["text"], structured["contract"]):
            assert "FlightOption(" in half
            assert "<a2ui>" in half
        assert len(structured["contract"]) > 5000

    def test_the_instructions_do_not_advertise_withdrawn_tools(self) -> None:
        """They opened with "the `show_*` tools are shortcuts for the six…".

        Those were withdrawn from the listing deliberately; the sentence
        describing them was not, so the first thing a host read about this
        server was a menu it could not order from.
        """
        from travel_a2ui.doors.plugin import INSTRUCTIONS

        assert "show_*" not in INSTRUCTIONS
        assert "trip" in INSTRUCTIONS


class TestTheViewsRenderWithoutTheirSourceTree:
    """Both HTML views, exercised — because one of them shipped broken.

    `render_view` reads `apps/mcp-view/shell.html` at runtime, and the image
    copied `catalogs/`, `skills/`, `prompts/`, `data/` and the server source.
    Not that file. Nothing caught it: the build passed, the import check passed,
    and every request passed — until a host asked for `?view=legacy`, which is
    the shape an older MCP-UI host asks for, and got a bare 500.

    The Dockerfile now renders both at build time for the same reason it imports
    the app at build time: a file opened lazily inside a function is invisible
    to an import.
    """

    def test_the_legacy_view_renders(self) -> None:
        from travel_a2ui.doors.plugin import render_view

        html = render_view("s", [], "a summary", "https://example.test")
        assert "a2ui-payload" in html
        assert "https://example.test/mcp-view/app.js" in html

    def test_the_mcp_app_template_renders(self) -> None:
        from travel_a2ui.doors.plugin import app_template

        assert "<!doctype html>" in app_template("https://example.test")

    def test_a_legacy_call_comes_back_with_html(self) -> None:
        body = call(
            "tools/call",
            {
                "name": "show_flight_options",
                "arguments": {"destination": "Madrid", "origin": "LHR", "date": "2027-04-12"},
            },
            view="legacy",
        )
        kinds = [
            part.get("resource", {}).get("mimeType")
            for part in body["result"]["content"]
            if part["type"] == "resource"
        ]
        assert "text/html" in kinds
