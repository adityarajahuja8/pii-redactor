FROM node:20-slim

# ── System packages ───────────────────────────────────────────────────────────
# python3, pip, and build tools needed for spaCy's Cython extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Copy everything ───────────────────────────────────────────────────────────
COPY . /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Use requirements.txt with pinned versions (same as local dev)
# NOTE: --break-system-packages is needed on Debian/Ubuntu when no virtualenv
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ── spaCy language model ──────────────────────────────────────────────────────
# Install en_core_web_sm via pip (direct wheel install, no spacy download command)
# Model version 3.8.0 is compatible with spacy 3.8.x
# We use pip directly (NOT `python3 -m spacy download`) to avoid flag confusion
RUN pip3 install --no-cache-dir --break-system-packages \
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

# ── Verify Python + spaCy model is working before building frontend ───────────
RUN python3 -c "import en_core_web_sm; nlp = en_core_web_sm.load(); print('[Docker] spaCy en_core_web_sm loaded OK, pipe:', nlp.pipe_names)"

# ── Install Node server dependencies ─────────────────────────────────────────
RUN cd pii_web/server && npm ci

# ── Build React client for production ────────────────────────────────────────
RUN cd pii_web/client && npm ci && npm run build

# ── Runtime config ────────────────────────────────────────────────────────────
EXPOSE 4000

# PYTHON_BIN tells server/index.js which binary to use (skip the auto-detect loop)
ENV PYTHON_BIN=python3
ENV PORT=4000
ENV NODE_ENV=production

CMD ["node", "pii_web/server/index.js"]
