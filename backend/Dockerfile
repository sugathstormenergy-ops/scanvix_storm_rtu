# =============================================================================
# Storm Energy RTU Platform — production image
# One image, two services (see compose.yml):
#   storm-api : uvicorn app.main:app          (FastAPI + MQTT consumer)
#   storm-tcp : python -m app.tcp.server      (RTU TCP listener only)
# No secrets, certificates or server addresses are baked into this image —
# all configuration arrives as environment variables at runtime.
# =============================================================================
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Microsoft ODBC Driver 18 for SQL Server (pyodbc backend) + tzdata (Asia/Kolkata).
# curl/gnupg are only needed to add the Microsoft repo and are purged afterwards.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg tzdata unixodbc; \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg; \
    echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list; \
    apt-get update; \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

# Unprivileged runtime user
RUN groupadd --system --gid 10001 storm \
 && useradd --system --uid 10001 --gid storm --home-dir /app --no-create-home --shell /usr/sbin/nologin storm

WORKDIR /app

COPY requirements-prod.txt ./
RUN pip install --no-compile -r requirements-prod.txt

COPY --chown=root:root app ./app
COPY --chown=root:root docker/healthcheck.py /usr/local/bin/storm-healthcheck
RUN chmod 0755 /usr/local/bin/storm-healthcheck

USER storm:storm

EXPOSE 8000 8100

# Default command = API service. storm-tcp overrides it in compose.yml.
# --proxy-headers: requests arrive through the nginx reverse proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
