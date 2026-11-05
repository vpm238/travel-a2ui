"""What every server test runs inside.

## No real Gemini key, whatever the shell has exported

The doors fall back to `GEMINI_API_KEY` from the environment when a request
carries none — which is right for a deployment and wrong for a test. With a key
exported, which is the normal state of a shell somebody develops this app in:

  - the tests that assert "a turn without a key says so" got a key, and failed;
  - and anything that reached a door without a scripted client made a real,
    paid call to Gemini, so the suite's result depended on the network, the
    model being up, and the account having credit.

Two failures in `test_http.py` was the visible half. The invisible half was
the suite quietly spending money and being only as reliable as the API.

So both names the SDK reads are cleared for every test. `GOOGLE_API_KEY` too,
because `google.genai.Client` falls back to it when `GEMINI_API_KEY` is unset —
clearing one and leaving the other just moves the leak. A test that wants a key
sets one itself, explicitly, which is the only kind of key a test should have.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
