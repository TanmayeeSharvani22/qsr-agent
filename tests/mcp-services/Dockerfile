FROM python:3.12-slim

WORKDIR /opt/qsr

COPY tests/mcp-services/ ./tests/mcp-services/

RUN pip install --no-cache-dir -r tests/mcp-services/requirements.txt

ENV PYTHONUNBUFFERED=1 \
    QSR_MCP_TRANSPORT=streamable-http \
    QSR_MCP_HOST=0.0.0.0 \
    QSR_MCP_PORT=8000

EXPOSE 8000

USER 65532:65532

ENTRYPOINT ["python", "/opt/qsr/tests/mcp-services/service_launcher.py"]