FROM python:3.14.7-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/app/.local/bin:${PATH}"

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://security.debian.org|https://security.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://security.debian.org|https://security.debian.org|g' /etc/apt/sources.list; \
    fi; \
    apt-get -o Acquire::Retries=3 update; \
    apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        poppler-utils \
        qrencode \
        tesseract-ocr \
        tesseract-ocr-bul \
        tesseract-ocr-deu \
        tesseract-ocr-ell \
        tesseract-ocr-eng \
        tesseract-ocr-script-latn; \
    rm -rf /var/lib/apt/lists/*; \
    useradd --create-home --uid 10001 app

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --prefix=/home/app/.local .

FROM base AS test
ENV RUFF_CACHE_DIR=/tmp/ruff-cache \
    PYTEST_ADDOPTS="-p no:cacheprovider"
RUN pip install --no-cache-dir --prefix=/home/app/.local ".[dev]"
COPY backend/tests ./tests
COPY backend/locales ./locales
# Backend contract tests intentionally inspect frontend source files.
# Keep the complete frontend source tree available in the test stage so new
# cross-layer contract tests do not require Dockerfile changes per file.
COPY frontend/src /frontend/src
# Cross-layer contract tests also inspect the production orchestration scripts.
# Copy only the files they assert against; production runtime stages stay unchanged.
COPY docker/predeploy.sh /docker/predeploy.sh
COPY docker/scripts/deploy-production.sh /docker/scripts/deploy-production.sh
USER app
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
COPY --chown=app:app backend/locales ./locales
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]