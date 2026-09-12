"""What a conversation has to survive, and what it must not.

The store is a dict with a lock, so most of it is not worth testing. Three
things are:

  - the three-way meaning of `interaction_id`, because collapsing two of them
    loses a conversation's history and does it silently;
  - expiry, because without it a long-running process grows forever on
    abandoned sessions, and every page reload makes one;
  - that a reset actually forgets, because "a hard refresh starts over" is a
    promise made to the user in the docs.
"""

from __future__ import annotations

import threading

from travel_a2ui.sessions import SessionStore


def test_a_first_turn_creates_the_conversation() -> None:
    store = SessionStore()
    session = store.get("abc")
    assert session.interaction_id is None
    assert session.trip == {}
    assert session.turns == 0


def test_the_chain_continues_when_an_id_is_given() -> None:
    store = SessionStore()
    store.save("abc", interaction_id="int_1", trip={"destination": "Madrid"})
    assert store.get("abc").interaction_id == "int_1"


def test_leaving_the_id_out_leaves_the_chain_alone() -> None:
    """The commonest save: the trip moved, the conversation did not."""
    store = SessionStore()
    store.save("abc", interaction_id="int_1")
    store.save("abc", trip={"destination": "Madrid"})
    assert store.get("abc").interaction_id == "int_1"


def test_an_explicit_none_breaks_the_chain() -> None:
    """The whole reason the default is a sentinel rather than None.

    A failed request has to be able to say "that interaction id is no good, do
    not chain to it". If `None` meant "unchanged" there would be no way to say
    it, and the next turn would chain to an interaction the API has no record
    of — which fails again, forever, with the conversation stuck.
    """
    store = SessionStore()
    store.save("abc", interaction_id="int_1")
    store.save("abc", interaction_id=None)
    assert store.get("abc").interaction_id is None


def test_the_trip_survives_a_broken_chain() -> None:
    """The point of keeping the trip ourselves.

    The model forgetting is recoverable; the traveller's decisions being
    forgotten is not.
    """
    store = SessionStore()
    store.save("abc", interaction_id="int_1", trip={"destination": "Madrid", "travelers": 2})
    store.save("abc", interaction_id=None)
    assert store.get("abc").trip == {"destination": "Madrid", "travelers": 2}


def test_patching_the_trip_does_not_count_a_turn() -> None:
    # A button press that saves a value is not a turn of conversation, and
    # counting it as one would make the turn count useless for anything.
    store = SessionStore()
    store.save("abc", trip={"destination": "Madrid"})
    store.patch_trip("abc", {"travelers": 2})
    session = store.get("abc")
    assert session.trip == {"destination": "Madrid", "travelers": 2}
    assert session.turns == 1


def test_an_untouched_conversation_expires() -> None:
    store = SessionStore(ttl_seconds=0)
    store.save("abc", trip={"destination": "Madrid"})
    assert store.get("abc").trip == {}, "an expired session comes back empty, not stale"


def test_activity_keeps_a_conversation_alive() -> None:
    store = SessionStore(ttl_seconds=60)
    store.save("abc", trip={"destination": "Madrid"})
    assert store.get("abc").trip == {"destination": "Madrid"}


def test_too_many_conversations_drops_the_oldest() -> None:
    """The backstop the TTL is not.

    A day is a long time to hold everything something automated opened in a
    minute.
    """
    store = SessionStore(max_sessions=3)
    for index in range(10):
        store.save(f"session-{index}", trip={"n": index})
    assert len(store) == 3
    assert store.get("session-9").trip == {"n": 9}


def test_reset_forgets() -> None:
    store = SessionStore()
    store.save("abc", interaction_id="int_1", trip={"destination": "Madrid"})
    store.reset("abc")
    session = store.get("abc")
    assert session.interaction_id is None
    assert session.trip == {}


def test_ids_are_not_guessable() -> None:
    """Session ids are bearer tokens for someone's trip.

    Nothing else identifies a conversation, so a sequential or short id would
    let anyone read the trip next door by counting.
    """
    store = SessionStore()
    ids = {store.new_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(value) >= 16 for value in ids)


def test_concurrent_turns_do_not_lose_a_trip() -> None:
    """Two turns of the same conversation overlapping is the ordinary case.

    A traveller pressing a button while the previous turn is still streaming
    hits exactly this, and an unlocked dict loses one of the two writes in a
    way that looks like the model forgot.
    """
    store = SessionStore()
    store.save("abc", trip={})

    def add(index: int) -> None:
        for _ in range(50):
            store.patch_trip("abc", {f"key{index}": index})

    threads = [threading.Thread(target=add, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    trip = store.get("abc").trip
    assert {f"key{index}" for index in range(8)} <= set(trip)
