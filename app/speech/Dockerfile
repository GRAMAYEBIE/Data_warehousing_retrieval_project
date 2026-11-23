FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    HF_HOME=/models

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./
RUN useradd --create-home speech && mkdir -p /models && chown speech /models
USER speech

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=10 --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
