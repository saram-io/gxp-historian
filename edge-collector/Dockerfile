FROM telegraf:1.32-alpine

RUN apk add --no-cache python3 py3-pip && \
    pip3 install --no-cache-dir --break-system-packages httpx pydantic && \
    mkdir -p /var/lib/telegraf/buffer /etc/telegraf/scripts && \
    chown -R telegraf:telegraf /var/lib/telegraf /etc/telegraf

COPY telegraf-clickhouse.conf /etc/telegraf/telegraf.conf
COPY telegraf-clickhouse.conf /etc/telegraf/telegraf-clickhouse.conf
COPY scripts/ /etc/telegraf/scripts/

RUN chmod +x /etc/telegraf/scripts/*.py
