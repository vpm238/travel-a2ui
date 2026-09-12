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
# Stage 2: the server
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Unbuffered, or the logs arrive in chunks and a crash loses the line that
# explains it. No .pyc for a container that runs its source once.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY apps/server/pyproject.toml apps/server/
RUN pip install --no-cache-dir -e ./apps/server

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

# Cloud Run sends traffic to $PORT and does not ask.
ENV PORT=8080
EXPOSE 8080

# One worker, deliberately. Sessions live in memory (see `sessions.py`), so a
# second worker would be a second set of conversations and a traveller whose
# next request landed on the wrong one would find their trip gone. Concurrency
# comes from asyncio, which is what an agent that spends its time waiting on a
# model actually needs.
CMD exec uvicorn travel_a2ui.main:app --host 0.0.0.0 --port ${PORT} --workers 1
