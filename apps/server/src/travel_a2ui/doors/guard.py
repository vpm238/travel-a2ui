"""What a request may ask of this server, and how often on the server's key.

A visitor normally brings their own Gemini key, and pays for their own turns.
A deployment can also hold one (`GEMINI_API_KEY`), so a booth or a demo works
with no key typed in. Then every turn is on the deployment's account, and these
rules are what stop the server being an open Gemini proxy:

  - a client may choose only a model this server advertises, and an effort
    level the API knows; anything else falls back to the server's default;
  - a browser may open the voice socket only from this site, or from an
    origin listed in `ALLOWED_ORIGINS`;
  - turns on the server's key are limited per client address, to
    `SHARED_KEY_TURNS_PER_HOUR` (default 60). Turns on a visitor's own key are
    not limited here.

None of this replaces putting the service behind IAP or an API gateway when it
must not be public; see `docs/deploying.md`.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Iterable
from urllib.parse import urlsplit

from ..gemini import THINKING_LEVELS

#: Requests per address per hour on the server's own key.
SHARED_KEY_TURNS_PER_HOUR = int(os.environ.get("SHARED_KEY_TURNS_PER_HOUR", "60"))

_WINDOW_SECONDS = 3600.0
_MAX_ADDRESSES = 10_000


def chosen_model(requested: Any, allowed: Iterable[str], default: str) -> str:
    """The model to run: the one asked for if this server offers it, else the default."""
    asked = str(requested or "").strip()
    return asked if asked and asked in set(allowed) else default


def chosen_effort(requested: Any, default: str) -> str:
    """The thinking level to run at: a known one, else the default."""
    asked = str(requested or "").strip()
    return asked if asked in THINKING_LEVELS else default


def server_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Whether a browser on `origin` may open the voice socket on `host`.

    No Origin header is a non-browser client (a script, the validators), which
    cross-site protection is not about. A browser always sends one.
    """
    if not origin:
        return True
    listed = {entry.strip().rstrip("/") for entry in os.environ.get("ALLOWED_ORIGINS", "").split(",") if entry.strip()}
    if origin.rstrip("/") in listed:
        return True
    return bool(host) and urlsplit(origin).netloc.lower() == str(host).lower()


def client_address(headers: Any, peer: str | None) -> str:
    """The caller's address: the first `X-Forwarded-For` hop behind Cloud Run."""
    forwarded = str(headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (peer or "unknown")


class RateLimit:
    """A sliding hour of requests per address, in this process's memory."""

    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, address: str, now: float | None = None) -> bool:
        if self.per_hour <= 0:
            return False
        moment = time.monotonic() if now is None else now
        with self._lock:
            if len(self._seen) > _MAX_ADDRESSES:
                self._seen.clear()
            stamps = self._seen.setdefault(address, deque())
            while stamps and moment - stamps[0] > _WINDOW_SECONDS:
                stamps.popleft()
            if len(stamps) >= self.per_hour:
                return False
            stamps.append(moment)
            return True


SHARED_KEY_LIMIT = RateLimit(SHARED_KEY_TURNS_PER_HOUR)

#: Said when the server's key has been used up for this address.
LIMITED = (
    "This demo's shared key has reached its limit for now. Add your own Gemini "
    "key (it stays in your browser) to keep going."
)
