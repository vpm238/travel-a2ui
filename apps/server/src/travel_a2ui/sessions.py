"""One traveller's conversation, for as long as it lasts.

What lives here is deliberately small:

  - the id of the last interaction, which is how the conversation continues,
  - the trip, which is the part worth keeping: what the traveller decided, and
  - the decision shape when the standing surfaces were last drawn, so the server
    knows when the panel is owed a redraw.

The transcript is **not** here. The Interactions API keeps it server-side and
`previous_interaction_id` chains to it, so a tenth turn sends one message rather
than re-uploading nine turns of prose and tool results to ask one more question.
That removed the trimming problem along with the storage: there is no history to
trim, and so no way to trim it into a tool call with no matching result.

The trip stays ours regardless. It is what the traveller decided, and it has to
survive a model that forgets, a chain that breaks, and a change of runtime.

What deliberately does not live here: the API key. It arrives with each request
and leaves with it.

**In memory, and that is a decision with a consequence.** Nothing is written to
disk and nothing outlives the process, which is what "we are not storing
interactions beyond the session" has to mean if it means anything. The
consequence is that this server does not scale horizontally: a second instance
would not know the first instance's conversations, and a traveller whose next
request landed on it would find their trip gone. So the deployment pins one
instance. That is a real limit, written down here rather than discovered when
two people use the demo at once — and the fix, when it is wanted, is a shared
store behind this class, not a change to anything that calls it.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: How long an untouched conversation is kept.
#:
#: Reloading the page starts a new conversation, which is what a person means by
#: reloading — and it means every reload leaves a session behind that nothing
#: will ever ask for again. Each one holds a trip. So they expire.
SESSION_TTL_SECONDS = 24 * 60 * 60

#: Above this many live sessions, the oldest are dropped regardless of age.
#:
#: A TTL alone bounds nothing over a day: a crawler, a load test or a loop in
#: someone's client can open thousands of sessions in a minute and every one of
#: them is live for 24 hours. This is the backstop that keeps an unbounded dict
#: out of a long-running process.
MAX_SESSIONS = 500


class _Unchanged:
    """"Leave this as it was", which `None` cannot mean here — see `save`."""


UNCHANGED = _Unchanged()


@dataclass
class Session:
    """One conversation."""

    id: str
    #: The last interaction in this conversation, or None before the first turn.
    interaction_id: str | None = None
    #: What the traveller has decided.
    trip: dict[str, Any] = field(default_factory=dict)
    #: The trip's decision shape when the standing surfaces were last drawn.
    #:
    #: Kept here rather than in the browser because the *server* decides when a
    #: panel is owed a redraw: a client that does not know what a trip is cannot
    #: be the thing watching for one to change.
    shape: str | None = None
    #: The setup — the stable half of the prompt — this conversation is bound to.
    #:
    #: Sent once, when the conversation starts. Held so that a later turn can
    #: tell whether it is still the same setup: change the skill variant and the
    #: rules the model is working from are different, so the chain is dropped
    #: and a new conversation starts rather than continuing against a contract
    #: nobody is reading any more.
    setup: str | None = None
    #: The handle that lets a Live conversation be picked up where it stopped.
    #:
    #: A Live session belongs to Google and has a lifetime of its own. When it
    #: reaches the end of it the API sends `go_away`, the relay ends, and the
    #: browser's socket closes with it — without anybody pressing anything. The
    #: conversation lives inside that session and nowhere else, so reconnecting
    #: without this starts a stranger who has never heard of the trip.
    #:
    #: That is what made stopping and restarting the microphone feel like a
    #: reset. It is not a reset anyone asked for: the traveller stopped talking
    #: for a moment, which is the most ordinary thing that can happen in a
    #: conversation. The trip survived — it is kept here — but the conversation
    #: did not, and an agent that still has the facts and has forgotten the
    #: discussion is worse company than one that has forgotten both.
    #:
    #: `session_resumption_update` carries a fresh handle as the session runs;
    #: the newest one is kept, and the next connection opens with it.
    live_handle: str | None = None
    turns: int = 0
    #: How many inline surfaces this conversation has handed out.
    #:
    #: Separate from `turns`, which counts turns that *finished*. A turn that
    #: fails still drew a card, and reusing its id would mean the next question
    #: replaces the one that went wrong — leaving the traveller looking at a
    #: card whose error message was overwritten by an unrelated question.
    inline_surfaces: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def next_inline_surface_id(self) -> str:
        """A surface id no card in this conversation is already using."""
        self.inline_surfaces += 1
        return f"inline-{self.inline_surfaces}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "interactionId": self.interaction_id,
            "trip": self.trip,
            "shape": self.shape,
            "setup": self.setup,
            "turns": self.turns,
            "createdAt": int(self.created_at * 1000),
            "updatedAt": int(self.updated_at * 1000),
        }


class SessionStore:
    """Every live conversation, and nothing that is not live.

    Locked, because a single Uvicorn worker still runs request handlers
    concurrently and two turns of the *same* conversation can overlap — a
    traveller pressing a button while the previous turn is still streaming is
    the ordinary case, not a race nobody hits.
    """

    def __init__(
        self,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_sessions

    def _expire(self, now: float) -> None:
        """Drops what has aged out, then what does not fit. Caller holds the lock."""
        for key in [
            key
            for key, session in self._sessions.items()
            if now - session.updated_at > self._ttl
        ]:
            del self._sessions[key]

        if len(self._sessions) > self._max:
            oldest = sorted(self._sessions.values(), key=lambda s: s.updated_at)
            for session in oldest[: len(self._sessions) - self._max]:
                self._sessions.pop(session.id, None)

    def get(self, session_id: str) -> Session:
        """The conversation with this id, creating it if this is the first turn."""
        now = time.time()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(id=session_id)
                self._sessions[session_id] = session
            return session

    def save(
        self,
        session_id: str,
        *,
        interaction_id: str | None | _Unchanged = UNCHANGED,
        trip: dict[str, Any] | None = None,
        shape: str | None = None,
        setup: str | None = None,
    ) -> Session:
        """Records a turn.

        `interaction_id` distinguishes three things, which is why its default is
        a sentinel rather than `None`: absent means unchanged, a string means the
        chain continues, and `None` means the chain broke and the next turn
        starts a fresh one. Collapsing the last two would silently lose a
        conversation's history the first time a request failed.
        """
        now = time.time()
        with self._lock:
            session = self._sessions.get(session_id) or Session(id=session_id)
            if not isinstance(interaction_id, _Unchanged):
                session.interaction_id = interaction_id
            if trip is not None:
                session.trip = trip
            if shape is not None:
                session.shape = shape
            if setup is not None:
                session.setup = setup
            session.turns += 1
            session.updated_at = now
            self._sessions[session_id] = session
            self._expire(now)
            return session

    def patch_trip(self, session_id: str, patch: dict[str, Any]) -> Session:
        """Merges into the trip without counting a turn."""
        with self._lock:
            session = self._sessions.get(session_id) or Session(id=session_id)
            session.trip = {**session.trip, **patch}
            session.updated_at = time.time()
            self._sessions[session_id] = session
            return session

    def set_live_handle(self, session_id: str, handle: str | None) -> Session:
        """Remembers where a Live conversation can be picked up from.

        Not a turn: the handle is refreshed by the API as the session runs, and
        counting each refresh would age a conversation out for talking.
        """
        with self._lock:
            session = self._sessions.get(session_id) or Session(id=session_id)
            session.live_handle = handle
            session.updated_at = time.time()
            self._sessions[session_id] = session
            return session

    def reset(self, session_id: str) -> None:
        """Forgets a conversation entirely. A hard refresh means this."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def new_id(self) -> str:
        return secrets.token_urlsafe(12)

    def __len__(self) -> int:
        with self._lock:
            self._expire(time.time())
            return len(self._sessions)
