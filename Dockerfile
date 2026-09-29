FROM python:3.12-slim

ARG SDK_REPO=https://github.com/sachinkaushik/edge-ai-libraries.git
ARG SDK_REF=mcp
ARG HERMES_INSTALL_URL=https://hermes-agent.nousresearch.com/install.sh
ARG HERMES_INSTALL_COMMIT=

ENV HOME=/home/qsr \
    PATH=/home/qsr/.local/bin:/opt/qsr/.venv/mcp/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bash build-essential ca-certificates curl ffmpeg git libffi-dev python3-dev ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /bin/bash qsr

WORKDIR /opt/qsr
COPY --chown=qsr:qsr . .

RUN python3 -m venv /opt/qsr/.venv/mcp \
    && /opt/qsr/.venv/mcp/bin/python -m pip install --upgrade pip \
    && git clone --depth 1 --filter=blob:none --sparse --no-recurse-submodules \
        --branch "$SDK_REF" "$SDK_REPO" /tmp/edge-ai-libraries \
    && git -C /tmp/edge-ai-libraries sparse-checkout set frameworks/mcp-service-sdk \
    && /opt/qsr/.venv/mcp/bin/python -m pip install \
        "/tmp/edge-ai-libraries/frameworks/mcp-service-sdk[mcp]" \
        -r /opt/qsr/autonomy/requirements.txt PyYAML \
    && rm -rf /tmp/edge-ai-libraries \
    && mkdir -p /home/qsr/.hermes /home/qsr/.local/state/qsr-agent \
    && chown -R qsr:qsr /opt/qsr/.venv /home/qsr

USER qsr
RUN curl -fsSL "$HERMES_INSTALL_URL" -o /tmp/install-hermes.sh \
    && if [ -n "$HERMES_INSTALL_COMMIT" ]; then \
        bash /tmp/install-hermes.sh --skip-setup --non-interactive --commit "$HERMES_INSTALL_COMMIT"; \
    else \
        bash /tmp/install-hermes.sh --skip-setup --non-interactive; \
    fi \
    && rm /tmp/install-hermes.sh

EXPOSE 8600
ENTRYPOINT ["/opt/qsr/.venv/mcp/bin/python", "/opt/qsr/entrypoint.py"]