# One image: the Python server, with both front ends built into it.
#
# Two stages, because the build needs Node and the runtime does not. Shipping
# the toolchain would roughly triple the image for nothing — Cloud Run pays for
# the pull on every cold start, so the difference is startup latency, not just
# registry space.
#
# The front ends are built here rather than committed. A `dist/` in git is a
# second copy of the app that is right until someone forgets, and the way you
# find out is a deploy serving last week's UI against this week's API.

# ---------------------------------------------------------------------------
# Stage 1: build the React client
# ---------------------------------------------------------------------------
FROM node:22-slim AS web

WORKDIR /build

# Manifests first, so a source change does not re-resolve the dependency tree.
# This is the layer that takes a minute; the source layer takes a second.
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY apps/gallery/package.json apps/gallery/
COPY apps/mcp-view/package.json apps/mcp-view/
COPY apps/worker/package.json apps/worker/
COPY packages/express/package.json packages/express/
COPY packages/renderer/package.json packages/renderer/
COPY packages/trip/package.json packages/trip/
RUN npm ci

COPY . .
RUN npm run build -w @travel-a2ui/trip \
 && npm run build -w @travel-a2ui/express \
 && npm run build -w @travel-a2ui/renderer \
 && npm run build -w @travel-a2ui/web

# ---------------------------------------------------------------------------
# Stage 1b: build the Flutter client
# ---------------------------------------------------------------------------
#
# The SDK from Google's own release archive, pinned to an exact version.
#
# Not a prebuilt community image, which would be the obvious choice: the ones
# that exist lag stable by several releases, so pinning one means building the
# client with an SDK nobody developed or tested it against. The download is the
# price of building with the same toolchain the tests ran on.
#
# Bumping FLUTTER_VERSION is a deliberate act. It should match the SDK the
# Flutter tests are run with, or `flutter build web` here can succeed on code
# that was never analysed at that version — and the first sign of it is a
# rendering difference in production.
FROM debian:bookworm-slim AS flutter

ARG FLUTTER_VERSION=3.47.4

# `git` because the SDK is a git checkout and its tooling reads its own
# revision; `xz-utils` to unpack the archive; `curl`/`ca-certificates` to fetch
# it. `unzip` is used by `flutter precache` for its own artifacts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git unzip xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/flutter.tar.xz \
      "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
 && tar -xJf /tmp/flutter.tar.xz -C /opt \
 && rm /tmp/flutter.tar.xz

ENV PATH="/opt/flutter/bin:${PATH}"

# The SDK is unpacked as a git checkout owned by a different uid than the one
# building; without this every `flutter` call fails on git's ownership check
# rather than on anything to do with the app.
RUN git config --global --add safe.directory /opt/flutter \
 && flutter --version \
 && flutter precache --web

WORKDIR /build

# Manifests first, so editing a widget does not re-resolve the package graph.
COPY apps/flutter_client/pubspec.yaml apps/flutter_client/pubspec.lock ./
RUN flutter pub get

COPY apps/flutter_client/ ./
# `--base-href` because the client is served under `/flutter/`, not at the root:
# without it the bundle asks for `/main.dart.js` and gets the React app's HTML,
# which fails as a syntax error rather than as a missing file.
RUN flutter build web --release --base-href=/flutter/

# ---------------------------------------------------------------------------
# Stage 2: the server
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Unbuffered, or the logs arrive in chunks and a crash loses the line that
# explains it. No .pyc for a container that runs its source once.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The manifest first: this layer is the dependency resolution, and it should not
# re-run because somebody edited a module.
COPY apps/server/pyproject.toml apps/server/

# The stub is not a trick, it is the fix for a silent failure.
#
# Installing with no source present is the obvious way to write this and it
# does not work: hatchling finds no package under `src/`, builds a wheel that
# is metadata and nothing else, and pip reports success. Copying the real
# source afterwards changes nothing, because the install already decided there
# was no import path to record. The build stays green, the image builds, the
# push succeeds — and the container dies at startup on `ModuleNotFoundError`
# with nothing anywhere in the build log to explain it.
#
# So there is something for the editable install to point at. The path it
# records is the directory, so the real modules copied over this stub below are
# what actually gets imported.
RUN mkdir -p apps/server/src/travel_a2ui \
 && touch apps/server/src/travel_a2ui/__init__.py \
 && pip install --no-cache-dir -e ./apps/server

# The data the server reads at runtime rather than at build time: the catalog
# it compiles against, the generated skills the model is given, the prompt
# text, and the fixtures. All of it is read from disk on startup, which is what
# makes a change to a prompt a change to a file rather than a code change.
COPY catalogs/ catalogs/
COPY skills/ skills/
COPY prompts/ prompts/
COPY data/ data/
COPY apps/server/src/ apps/server/src/

COPY --from=web /build/apps/web/dist/ apps/web/dist/
COPY --from=flutter /build/build/web/ apps/flutter_client/build/web/

# Import the app at build time, so a broken image fails here rather than in
# production.
#
# Everything above can succeed and still produce a container that cannot start:
# a package that did not install, a module that reads a data file that was
# never copied, a static mount pointing at a directory that is not there. Cloud
# Run reports all of it the same way — "failed to start and listen on the port"
# — several minutes after the build went green, and the reason is in a log the
# deploy does not show you.
#
# This is the same import uvicorn does, so if it passes here the process will
# start there. It costs a second and it is the difference between a build
# failure that names the problem and a deploy failure that does not.
RUN python -c "import travel_a2ui.main"

# Cloud Run sends traffic to $PORT and does not ask.
ENV PORT=8080
EXPOSE 8080

# One worker, deliberately. Sessions live in memory (see `sessions.py`), so a
# second worker would be a second set of conversations and a traveller whose
# next request landed on the wrong one would find their trip gone. Concurrency
# comes from asyncio, which is what an agent that spends its time waiting on a
# model actually needs.
CMD exec uvicorn travel_a2ui.main:app --host 0.0.0.0 --port ${PORT} --workers 1
