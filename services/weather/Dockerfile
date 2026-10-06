FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_NO_INPUT=1 \
    WEATHER_SIM_STATE=/home/weather/.local/state/weather-simulator/state.json

RUN useradd --create-home --uid 10002 --shell /usr/sbin/nologin weather \
    && mkdir -p /home/weather/.local/state/weather-simulator \
    && chown -R weather:weather /home/weather

WORKDIR /opt/weather-simulator
COPY pyproject.toml README.md ./
COPY weather_simulator ./weather_simulator
RUN pip install .

USER weather
EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)"]
ENTRYPOINT ["weather-simulator"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8090"]
