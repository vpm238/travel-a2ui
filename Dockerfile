# One image: the Python server, with both front ends and the quickstart built
# into it. The build stages need Node and Flutter; the runtime needs neither.
#
# Base images are pinned by digest, and the Flutter archive by checksum, so a
# rebuild of the same commit is the same image. Bump them deliberately.

# ---------------------------------------------------------------------------
# Stage 1: build the React client
# ---------------------------------------------------------------------------
FROM node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS web

WORKDIR /build

# Manifests first, so a source change does not re-resolve the dependency tree.
# This is the layer that takes a minute; the source layer takes a second.
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY renderers/react/package.json renderers/react/
RUN npm ci

COPY . .
RUN npm run build -w @travel-a2ui/renderer \
 && npm run build -w @travel-a2ui/web

# ---------------------------------------------------------------------------
# Stage 1a: build the quickstart
# ---------------------------------------------------------------------------
#
# `docs/site`, the A2UI quickstart, is a Starlight site with its own lockfile:
# it is written to move into the A2UI documentation, so it is not a workspace
# of this app. Built for `/docs`, where the server mounts it.
FROM node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS docs

WORKDIR /build

COPY docs/site/package.json docs/site/package-lock.json ./
RUN npm ci

COPY docs/site/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 1b: build the Flutter client
# ---------------------------------------------------------------------------
#
# The SDK from Flutter's release archive, at the version CI tests with
# (`.github/workflows/ci.yml`), verified against its published SHA-256
# (releases_linux.json). Bump both together.
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS flutter

ARG FLUTTER_VERSION=3.47.9
ARG FLUTTER_SHA256=25ed8c3c29d51a7353f2a944310b478af8214920639524b19c50a19e6c044c5a

# `git` because the SDK is a git checkout and its tooling reads its own
# revision; `xz-utils` to unpack the archive; `curl`/`ca-certificates` to fetch
# it. `unzip` is used by `flutter precache` for its own artifacts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git unzip xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/flutter.tar.xz \
      "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
 && echo "${FLUTTER_SHA256}  /tmp/flutter.tar.xz" | sha256sum -c - \
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
COPY renderers/flutter/pubspec.yaml renderers/flutter/pubspec.lock ./
RUN flutter pub get

COPY renderers/flutter/ ./
# `--base-href` because the client is served under `/flutter/`, not at the root:
# without it the bundle asks for `/main.dart.js` and gets the React app's HTML,
# which fails as a syntax error rather than as a missing file.
RUN flutter build web --release --base-href=/flutter/

# ---------------------------------------------------------------------------
# Stage 2: the server
# ---------------------------------------------------------------------------
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS runtime

# Unbuffered, or the logs arrive in chunks and a crash loses the line that
# explains it. No .pyc for a container that runs its source once.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The manifest first: this layer is the dependency resolution, and it should not
# re-run because somebody edited a module.
COPY apps/server/pyproject.toml apps/server/requirements.lock apps/server/

# An editable install needs the package directory to exist (hatchling builds
# an empty wheel otherwise), so a stub stands in for the source copied below.
# Editable because the server reads `catalogs/`, `skills/` and `prompts/` from
# the repository layout.
RUN mkdir -p apps/server/src/travel_a2ui \
 && touch apps/server/src/travel_a2ui/__init__.py \
 && pip install --no-cache-dir -r apps/server/requirements.lock \
 && pip install --no-cache-dir --no-deps -e ./apps/server

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
COPY --from=flutter /build/build/web/ renderers/flutter/build/web/
COPY --from=docs /build/dist/ docs/site/dist/

# The import uvicorn does at startup, at build time: a missing file or package
# fails the build with its name, not the deploy with "failed to listen".
RUN python -c "import travel_a2ui.doors.http"

# Not root. Nothing at runtime writes to /app.
RUN useradd --system --uid 10001 --no-create-home app
USER app

# Cloud Run sends traffic to $PORT and does not ask.
ENV PORT=8080
EXPOSE 8080

# One worker, deliberately. Sessions live in memory (see `sessions.py`), so a
# second worker would be a second set of conversations and a traveller whose
# next request landed on the wrong one would find their trip gone. Concurrency
# comes from asyncio, which is what an agent that spends its time waiting on a
# model actually needs.
CMD exec uvicorn travel_a2ui.doors.http:app --host 0.0.0.0 --port ${PORT} --workers 1
