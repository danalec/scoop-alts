FROM python:3.12-slim

ARG TZ=UTC
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=${TZ}

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends busybox tzdata ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/requirements-automation.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY docker/bin /app/bin
RUN chmod +x /app/bin/*.sh \
 && mkdir -p /data/logs /data/bucket /data/cache /var/spool/cron/crontabs

VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD /app/bin/healthcheck.sh

ENTRYPOINT ["/app/bin/entrypoint.sh"]
