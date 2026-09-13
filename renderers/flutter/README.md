# The Flutter client

**The same agent, drawn by a different toolkit.**

This client exists to test one claim, and it is the claim the whole repository
is built around:

> If a generative interface is really a *protocol* rather than a feature of one
> app, then a second client should be a **renderer and nothing else** — no travel
> logic, no idea what a trip is, no private agreement with the server about what
> a button means.

So this is not a port of the React client. It is a second implementation of the
same protocol, written against the official
[`a2ui_core`](https://pub.dev/packages/a2ui_core) and
[`a2ui_flutter`](https://pub.dev/packages/a2ui_flutter) packages rather than
against our renderer's internals. It talks to the same server, over the same
endpoint, and receives the same bytes.

It is served at **`/flutter`** on the same deployment as everything else —
[travel-a2ui-vy7stnte2a-uc.a.run.app/flutter](https://travel-a2ui-vy7stnte2a-uc.a.run.app/flutter).

## What is *not* in here is the point

Roughly 2,800 lines, and none of them are about travel:

| File | What it is |
| --- | --- |
| `main.dart` | the app shell and the theme |
| `api.dart` | the turn: post a message, read the A2UI messages back |
| `surface.dart` | surfaces by id, and the data model behind them |
| `components.dart` | the widgets — the one file that knows a flight card has a price on it, and even here it only knows how to *draw* one |
| `functions.dart` | the catalog's functions, implemented against the schema |
| `catalog.dart` | loading the catalog the server names |
| `chat.dart` | the conversation, and where each surface is placed |

There is no list of trip fields. No code deciding when the panel needs
redrawing. No sentence composed here to describe what somebody pressed. All of
that lives on the server, where it is shared with the React client and with
Claude — which is exactly why this client could be written at all.

The one idea worth carrying across from the React renderer is the **pending**
state: a binding whose path does not resolve is *pending*, and a path resolving
to an empty string is *empty*. That distinction is not a convention invented
here — it falls out of the data model — and it is what lets a surface paint its
layout the moment a search starts and fill in when the rows land.

## Running it

```bash
flutter run -d chrome                       # against a server on :8080
flutter build web --release --base-href=/flutter/
flutter test                                # render_test.dart
```

The `--base-href` is not optional for a release build: the client is served
under `/flutter/`, and without it the bundle asks for `/main.dart.js`, gets the
React app's HTML, and fails as a syntax error rather than as a missing file.

The SDK version is pinned in the root `Dockerfile` (`FLUTTER_VERSION`) and should
match the one the tests are run with — `flutter build web` can otherwise succeed
on code that was never analysed at that version, and the first sign of it is a
rendering difference in production.

## Known gap

**There is no voice path here.** Choosing Gemini Live in the React client puts a
microphone in the composer; this client has no equivalent, so it is typed-only.
Nothing about the architecture prevents it — the relay carries microphone bytes
up and audio plus A2UI down, which is transport this client could speak — it
simply has not been written. See the root [README](../../README.md#talking-to-it)
for what that path does.
