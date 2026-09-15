FROM python:3.12-slim

ARG SDK_GIT_REF=mcp

WORKDIR /opt/qsr

COPY tests/mcp-services/ ./tests/mcp-services/

RUN pip install --no-cache-dir "mcp-service-sdk[mcp] @ git+https://github.com/sachinkaushik/edge-ai-libraries.git@${SDK_GIT_REF}#subdirectory=libraries/mcp-service-sdk"

ENV PYTHONUNBUFFERED=1 \
    QSR_MCP_TRANSPORT=streamable-http \
    QSR_MCP_HOST=0.0.0.0 \
    QSR_MCP_PORT=8000

EXPOSE 8000

USER 65532:65532

ENTRYPOINT ["python", "/opt/qsr/tests/mcp-services/service_launcher.py"]