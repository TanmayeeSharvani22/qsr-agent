# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

FROM python:3.12-slim AS builder

ARG HERMES_INSTALL_URL=https://hermes-agent.nousresearch.com/install.sh
ARG HERMES_INSTALL_COMMIT=

ENV HOME=/home/qsr \
    PATH=/home/qsr/.local/bin:/opt/qsr/.venv/mcp/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PIP_NO_CACHE_DIR=1 \
    # Hermes installs a standalone Python that ignores Debian's /etc/ssl/certs;
    # point it at the system CA bundle so its urllib-based downloads verify TLS.
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_DIR=/etc/ssl/certs

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash build-essential ca-certificates curl git libffi-dev python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /bin/bash qsr \
    && mkdir -p /opt/qsr && chown -R qsr:qsr /opt/qsr /home/qsr

WORKDIR /opt/qsr

# Installed before the app source so code edits don't re-run this slow, flaky download.
USER qsr
# Retries cover GitHub rate limits (HTTP 429) and intermittent TLS chain failures.
RUN curl -fsSL "$HERMES_INSTALL_URL" -o /tmp/install-hermes.sh \
    && set -- --skip-setup --non-interactive --skip-browser --skip-computer-use \
    && if [ -n "$HERMES_INSTALL_COMMIT" ]; then set -- "$@" --commit "$HERMES_INSTALL_COMMIT"; fi \
    && for attempt in 1 2 3 4 5; do \
    bash /tmp/install-hermes.sh "$@" && break; \
    if [ "$attempt" = 5 ]; then echo "Hermes install failed after $attempt attempts" >&2; exit 1; fi; \
    wait_seconds=$((attempt * 60)); \
    echo "Hermes install attempt $attempt failed; retrying in ${wait_seconds}s" >&2; \
    sleep "$wait_seconds"; \
    done \
    && rm /tmp/install-hermes.sh

COPY --chown=qsr:qsr autonomy/requirements.txt /opt/qsr/autonomy/requirements.txt
COPY --chown=qsr:qsr tests/mcp-services/requirements.txt /opt/qsr/tests/mcp-services/requirements.txt
RUN python3 -m venv /opt/qsr/.venv/mcp \
    && /opt/qsr/.venv/mcp/bin/python -m pip install --upgrade pip \
    && /opt/qsr/.venv/mcp/bin/python -m pip install \
    -r /opt/qsr/tests/mcp-services/requirements.txt \
    -r /opt/qsr/autonomy/requirements.txt PyYAML \
    && rm -rf /home/qsr/.cache


# Runtime stage: no compilers, git, or install caches — only what the app runs on.
FROM python:3.12-slim

ENV HOME=/home/qsr \
    PATH=/home/qsr/.local/bin:/opt/qsr/.venv/mcp/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_DIR=/etc/ssl/certs

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash ca-certificates ffmpeg ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /bin/bash qsr \
    && mkdir -p /opt/qsr /home/qsr/.hermes /home/qsr/.local/state/qsr-agent \
    && chown -R qsr:qsr /opt/qsr /home/qsr

WORKDIR /opt/qsr
USER qsr

# Hermes CLI + standalone runtime and the MCP venv, built in the builder stage.
# ~/.hermes holds the actual hermes binary and seeds the hermes-home volume on
# first run, so it must be baked in; ~/.local has the launcher on PATH.
COPY --from=builder --chown=qsr:qsr /home/qsr/.local /home/qsr/.local
COPY --from=builder --chown=qsr:qsr /home/qsr/.hermes /home/qsr/.hermes
COPY --from=builder --chown=qsr:qsr /opt/qsr/.venv /opt/qsr/.venv

COPY --chown=qsr:qsr . .

EXPOSE 8600
ENTRYPOINT ["/opt/qsr/.venv/mcp/bin/python", "/opt/qsr/entrypoint.py"]