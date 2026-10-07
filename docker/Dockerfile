# Every Zahlmeister image, one named stage each. The build context is the
# repository root; /.dockerignore decides what any stage can see.
#
#   backend-dev    API, worker and bootstrap in development (compose.yml)
#   backend-test   Ruff and pytest (manage.sh -> 10) Tests, scripts/test.sh)
#   backend        production API, worker and bootstrap (pushed to GHCR)
#   frontend-dev   Next.js dev server (compose.yml)
#   frontend-test  node --test suites and the TypeScript check
#   frontend       production nginx with the static export (pushed to GHCR)
#   mobile         Android build toolchain (compose.yml, profile "tools")
#
# BuildKit builds only the stages the requested target depends on.

# --- Backend -----------------------------------------------------------------

FROM python:3.14.7-slim AS backend-os

# Build-time only: apt runs without a terminal, so debconf must not try to prompt.
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
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

# Development runs as root with backend/ bind-mounted over /app; the editable
# install keeps the mounted sources importable.
FROM backend-os AS backend-dev
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir -e ".[dev]"
COPY backend/ .
# Verify async database dependencies in the actual runtime environment.
RUN python -c "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine; from sqlalchemy.util.concurrency import greenlet_spawn; import asyncio; asyncio.run(greenlet_spawn(lambda: None))"

FROM backend-os AS backend-base
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --prefix=/home/app/.local .

FROM backend-base AS backend-test
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
COPY docker/scripts/test.sh /docker/scripts/test.sh
COPY docker/scripts/deploy-production.sh /docker/scripts/deploy-production.sh
USER app
CMD ["python", "-m", "pytest", "-q"]

FROM backend-base AS backend
COPY --chown=app:app backend/locales ./locales
USER app
# Verify async database dependencies in the actual runtime environment.
RUN python -c "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine; from sqlalchemy.util.concurrency import greenlet_spawn; import asyncio; asyncio.run(greenlet_spawn(lambda: None))"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Frontend ----------------------------------------------------------------

FROM node:24.21.0-alpine AS frontend-deps
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./

# compose.yml mounts frontend/ over /app and reinstalls into a volume on start.
FROM frontend-deps AS frontend-dev
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM frontend-deps AS frontend-test
RUN npm test && npm run typecheck

FROM frontend-test AS frontend-build
ARG NEXT_PUBLIC_API_BASE_URL=
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

FROM nginx:1.30.5-alpine AS frontend
RUN sed -i \
      -e '/^user[[:space:]].*;$/d' \
      -e 's|^pid[[:space:]].*;|pid /tmp/nginx.pid;|' \
      /etc/nginx/nginx.conf \
    && grep -q '^pid /tmp/nginx.pid;$' /etc/nginx/nginx.conf \
    && ! grep -q '^user[[:space:]]' /etc/nginx/nginx.conf
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build --chown=nginx:nginx /app/out /usr/share/nginx/html
USER nginx
EXPOSE 8080

# --- Mobile ------------------------------------------------------------------

# Android build toolchain for the Capacitor app in mobile/.
#
# A tool, not a service: compose.yml keeps it behind the "tools" profile and
# manage.sh -> 11) Android App runs it with `compose run --rm`. Node, JDK 21,
# the Android SDK (adb included), bundletool and the npm dependencies of
# frontend/ and mobile/ (Capacitor CLI included) are baked in, so building,
# installing and debugging the app needs nothing on the host but Docker.
# Sources are mounted read-only at run time and built in a private copy under
# /work by mobile/tool/build_android.sh; mobile/tool/android_device.sh drives a
# USB-connected phone from the same image (compose service mobile-device).
FROM node:24.21.0-trixie-slim AS mobile

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    NEXT_TELEMETRY_DISABLED=1 \
    ANDROID_HOME=/opt/android-sdk \
    GRADLE_USER_HOME=/home/dev/.gradle

# python3 is only for mobile/tool/bootstrap_mobile.sh, which regenerates the
# native project; ordinary builds do not need it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip openjdk-21-jdk-headless python3 \
    && rm -rf /var/lib/apt/lists/*

# Capacitor 8.5 targets compileSdk 36 with AGP 8.13, whose default build tools
# are 35.0.0. Everything the build needs is installed here and the SDK stays
# root-owned, so a missing component fails the build instead of being
# downloaded into a throwaway container. cmdline-tools 19.0 is the newest
# release whose package metadata AGP 8.13 still reads (20.0+ write SDK XML v4).
# sdkmanager unpacks tools as 0744; a+rX lets the build user run apksigner.
ARG ANDROID_CMDLINE_TOOLS=commandlinetools-linux-13114758_latest.zip
ARG ANDROID_CMDLINE_TOOLS_SHA1=5fdcc763663eefb86a5b8879697aa6088b041e70
ARG ANDROID_BUILD_TOOLS=35.0.0
ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/build-tools/${ANDROID_BUILD_TOOLS}:${ANDROID_HOME}/platform-tools:${PATH}"
RUN curl -fsSL -o /tmp/cmdline-tools.zip "https://dl.google.com/android/repository/${ANDROID_CMDLINE_TOOLS}" \
    && echo "${ANDROID_CMDLINE_TOOLS_SHA1}  /tmp/cmdline-tools.zip" | sha1sum -c - \
    && mkdir -p "${ANDROID_HOME}/cmdline-tools" \
    && unzip -q /tmp/cmdline-tools.zip -d "${ANDROID_HOME}/cmdline-tools" \
    && mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest" \
    && rm /tmp/cmdline-tools.zip \
    && { yes 2>/dev/null || true; } | sdkmanager --licenses >/dev/null \
    && sdkmanager "platforms;android-36" "build-tools;${ANDROID_BUILD_TOOLS}" "platform-tools" >/dev/null \
    && chmod -R a+rX "${ANDROID_HOME}"

# bundletool turns an AAB into the split APKs Google Play would deliver and
# installs them on a connected device (manage.sh -> 11 -> 5) Device).
ARG BUNDLETOOL_VERSION=1.18.3
ARG BUNDLETOOL_SHA256=a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29
RUN curl -fsSL -o /opt/bundletool.jar \
        "https://github.com/google/bundletool/releases/download/${BUNDLETOOL_VERSION}/bundletool-all-${BUNDLETOOL_VERSION}.jar" \
    && echo "${BUNDLETOOL_SHA256}  /opt/bundletool.jar" | sha256sum -c - \
    && chmod 644 /opt/bundletool.jar \
    && printf '#!/bin/sh\nexec java -jar /opt/bundletool.jar "$@"\n' > /usr/local/bin/bundletool \
    && chmod 755 /usr/local/bin/bundletool

# A user whose uid/gid match the host's, so artifacts written to the mounted
# mobile/dist and docker/secrets/android stay host-owned. The node image's own
# uid 1000 user is removed rather than collided with.
ARG UID=1000
ARG GID=1000
RUN if getent passwd "${UID}" >/dev/null; then \
        userdel -r "$(getent passwd "${UID}" | cut -d: -f1)" 2>/dev/null || true; \
    fi \
    && if getent group "${GID}" >/dev/null; then \
        groupmod -n dev "$(getent group "${GID}" | cut -d: -f1)"; \
    else \
        groupadd -g "${GID}" dev; \
    fi \
    && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash dev \
    && install -d -o dev -g dev /work /work/frontend /work/mobile /work/mobile/tool \
        /home/dev/.gradle /home/dev/.android

USER dev

# node_modules for the exact lockfiles. build_android.sh refuses to run when a
# mounted lockfile differs; manage.sh rebuilds this image before every build,
# which is a cache hit unless a lockfile changed.
WORKDIR /work/frontend
COPY --chown=dev:dev frontend/package.json frontend/package-lock.json /work/frontend/
RUN npm ci --no-audit --no-fund && npm cache clean --force

WORKDIR /work/mobile
COPY --chown=dev:dev mobile/package.json mobile/package-lock.json /work/mobile/
COPY --chown=dev:dev mobile/tool/harden_native_purchases.sh /work/mobile/tool/
RUN npm ci --no-audit --no-fund && npm cache clean --force \
    && npx cap telemetry off

WORKDIR /work
CMD ["bash"]
