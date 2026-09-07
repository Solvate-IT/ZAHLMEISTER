FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/app/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        poppler-utils \
        qrencode \
        tesseract-ocr \
        tesseract-ocr-bul \
        tesseract-ocr-deu \
        tesseract-ocr-ell \
        tesseract-ocr-eng \
        tesseract-ocr-script-latn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --prefix=/home/app/.local .

FROM base AS test
RUN pip install --no-cache-dir --prefix=/home/app/.local ".[dev]"
COPY backend/tests ./tests
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/locales ./locales
USER app
CMD ["pytest", "-q"]

FROM base AS runtime
COPY --chown=app:app backend/alembic.ini ./
COPY --chown=app:app backend/alembic ./alembic
COPY --chown=app:app backend/locales ./locales
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
