# ASTRASOC API image
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# No OS packages needed: psycopg2-binary bundles libpq and the healthcheck
# uses the Python standard library.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY astrasoc ./astrasoc

# Run as an unprivileged user. /data holds the SQLite file in the demo profile.
RUN groupadd -g 10001 astrasoc && useradd -u 10001 -g astrasoc -M -s /usr/sbin/nologin astrasoc \
    && mkdir -p /data && chown astrasoc:astrasoc /data
USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"]

# --proxy-headers is safe: uvicorn only trusts X-Forwarded-* from
# FORWARDED_ALLOW_IPS (loopback unless set). Client IPs for audit/rate
# limiting use ASTRASOC_TRUSTED_PROXIES.
CMD ["uvicorn", "astrasoc.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
