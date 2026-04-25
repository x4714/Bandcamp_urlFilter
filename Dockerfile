FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    XDG_CONFIG_HOME=/config

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        flac \
        lame \
        mp3val \
        sox \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app /app/exports /config /downloads

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN chmod +x /app/docker/entrypoint.sh \
    && chown -R appuser:appuser /app /config /downloads

USER appuser

HEALTHCHECK CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "streamlit", "run", "app.py"]
