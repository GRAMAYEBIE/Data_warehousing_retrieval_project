FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY assistant ./assistant
COPY prompts ./prompts
COPY tests ./tests
COPY pyproject.toml ./

RUN useradd --create-home assistant
USER assistant

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
