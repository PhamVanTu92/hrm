# syntax=docker/dockerfile:1.7
# ----------------------------------------------------------------------------
# Multi-stage build for the HRM backend.
#   stage 1 (builder): install Python deps into a venv
#   stage 2 (runtime): copy the venv + app, run as a non-root user
# The same image runs the API, Celery workers and Celery beat — only the
# container command differs (see docker-compose.yml).
# ----------------------------------------------------------------------------

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build-time system deps. gcc/headers are needed to compile argon2-cffi /
# asyncpg wheels when a prebuilt wheel is unavailable.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated venv we can copy wholesale into the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# The hatchling backend builds the `app` package wheel, so the source must be
# present at install time. Copy metadata + source, then install with the [pdf]
# extra (WeasyPrint + pikepdf) for payslip rendering.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[pdf,observability]"

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production

# Runtime system deps:
#   libpq5            -> asyncpg/psycopg at runtime
#   WeasyPrint stack  -> payslip PDF rendering (pango/cairo/gdk-pixbuf + fonts)
#   libqpdf*          -> pikepdf (AES-256 password-protect the payslip PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        qpdf \
        fonts-dejavu-core \
        fonts-liberation \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the prebuilt virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Non-root user — never run the app as root.
RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app

# App source (ownership set so the non-root user can read it).
COPY --chown=app:app . /app

USER app

EXPOSE 8000

# Container-level healthcheck hits the app's /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default command runs the API under gunicorn with uvicorn workers.
# Workers/beat override this in docker-compose.yml.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
