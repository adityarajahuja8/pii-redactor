FROM node:20-slim

# Install Python 3, pip, and required system build packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy root files and Python package
COPY . /app

# Install Python dependencies globally inside container
RUN pip3 install --no-cache-dir python-docx spacy faker tqdm --break-system-packages
RUN python3 -m spacy download en_core_web_sm --break-system-packages || \
    pip3 install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl --break-system-packages

# Install Node server dependencies
RUN cd pii_web/server && npm install

# Build React client for production
RUN cd pii_web/client && npm install && npm run build

# Expose backend port
EXPOSE 4000

ENV PORT=4000
CMD ["node", "pii_web/server/index.js"]
