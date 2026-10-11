FROM python:3.12-slim

ARG TZ=UTC
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=${TZ}

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends busybox tzdata ca-certificates curl git openssh-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/requirements-automation.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Scripts live outside /app so mounting the repo at /app does not shadow them.
COPY docker/bin /usr/local/scoop-bin
RUN chmod +x /usr/local/scoop-bin/*.sh \
 && mkdir -p /data/logs /data/cache /var/spool/cron/crontabs

VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD /usr/local/scoop-bin/healthcheck.sh

ENTRYPOINT ["/usr/local/scoop-bin/entrypoint.sh"]
