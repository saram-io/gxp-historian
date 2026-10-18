FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY mock_instruments.py /app/mock_instruments.py
RUN mkdir -p /app/ufl_drop

# 8095: HTTP Control Plane, OPC DA 2.05a Bridge, PI UFL Watch-Folder & Swagger UI
# 4840: OPC UA Binary TCP (HEL/ACK + Node Read)
# 5020: Modbus TCP Server (MBAP + FC03/FC04 IEEE-754 ABCD/CDAB & INT16)
# 47808/udp: BACnet/IP UDP Server (ASHRAE 135 BVLC + ReadProperty-ACK)
# 1102: Siemens S7comm ISO-on-TCP Server (RFC 1006 TPKT/COTP + DB10 Read)
# 4001: Moxa NPort RS-232 Serial-over-TCP Server (Mettler Toledo MT-SICS & Osmometer)
EXPOSE 8095 4840 5020 47808/udp 1102 4001

CMD ["uvicorn", "mock_instruments:app", "--host", "0.0.0.0", "--port", "8095"]
