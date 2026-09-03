"""Paths, skills and the provisioned agent's identity.

An agent is a persisted, versioned object on Anthropic's side, so its
configuration lives here and in `setup_agent.py`, and the request path holds
nothing but a session id.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
"""`backends/claude-managed-agent`."""

ROOT = BACKEND_DIR.parents[1]
"""The repository root, two levels above this backend."""

STATE_FILE = BACKEND_DIR / ".agent.json"

CATALOG_PATH = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

AGENT_NAME = "travel-a2ui"
ENVIRONMENT_NAME = "travel-a2ui-env"

SKILL_FILES: dict[str, list[str]] = {
    "express-monolithic": ["skills/express-monolithic/a2ui/SKILL.md"],
    "express-modular": [
        "skills/express-modular/a2ui-core/SKILL.md",
        "skills/express-modular/a2ui-travel/SKILL.md",
    ],
    "direct-json-monolithic": ["skills/direct-json-monolithic/a2ui/SKILL.md"],
}


@dataclasses.dataclass
class AgentState:
    agent_id: str
    agent_version: int
    environment_id: str
    mcp_url: str
    skill_variant: str
    compile_service: str | None = None
    created_at: str = ""
    #: Where the Worker deployment is, so the front end's runtime picker can
    #: offer a way back after switching to this backend. Derived from the MCP
    #: URL when not set explicitly, since that is the same deployment.
    worker_origin: str = ""

    @classmethod
    def load(cls) -> "AgentState | None":
        try:
            return cls(**json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    @property
    def worker(self) -> str:
        if self.worker_origin:
            return self.worker_origin.rstrip("/")
        if self.mcp_url:
            from urllib.parse import urlsplit

            parts = urlsplit(self.mcp_url)
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
        return ""

    def save(self) -> None:
        STATE_FILE.write_text(
            json.dumps(dataclasses.asdict(self), indent=2) + "\n", encoding="utf-8"
        )


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def skill_body(markdown: str) -> str:
    """Strips YAML frontmatter — the model wants the instructions, not the metadata."""
    if not markdown.startswith("---"):
        return markdown.strip()
    end = markdown.find("\n---", 3)
    return markdown.strip() if end == -1 else markdown[end + 4 :].strip()


def load_skill(variant: str = "express-monolithic") -> str:
    files = SKILL_FILES.get(variant, SKILL_FILES["express-monolithic"])
    return "\n\n---\n\n".join(
        skill_body((ROOT / name).read_text(encoding="utf-8")) for name in files
    )


ROLE = """\
You are a travel agent that plans trips as **interfaces**, not as paragraphs.

When a reply contains options, a comparison, dates, a form, a cost, or an
itinerary, draw it rather than describing it.

Your travel tools come from the `travel-a2ui` MCP server:

- `show_flight_options`, `show_hotel_options`, `show_trip_controls`,
  `show_itinerary`, `show_trip_dashboard` and `show_price_summary` return
  finished surfaces. Prefer them — they are backed by real data and cheaper than
  composing the same thing yourself. Each takes a `surface` argument
  (`inline`, `sidebar`, `home`); pass the one that matches where the answer goes.
- `render_a2ui_express` compiles A2UI Express you write. Use it when none of the
  above fits and you want your own layout.

Say one useful sentence, then draw. Do not narrate what the interface shows."""
