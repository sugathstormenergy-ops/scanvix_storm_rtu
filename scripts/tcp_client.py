#!/usr/bin/env python3
"""
Storm Energy RTU Platform — TCP RTU Simulator.
Connects to the Storm TCP listener and sends packets.
Development tool — uses the same protocol as actual Scanvix hardware.

NOTE: TCP packet format is TBD with Scanvix.
This simulator uses JSON-over-TCP (the JsonOverTcpParser fallback)
until the final ASCII frame format is agreed.

Usage:
  python scripts/tcp_client.py --device 864012049873321 --site BENCH
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time

sys.path.insert(0, "backend")
from scripts.telemetry_generator import make_historical_batch, make_telemetry

DEFAULT_HOST   = "localhost"
DEFAULT_PORT   = 8100
DEFAULT_DEVICE = "864012049873321"
DEFAULT_SITE   = "BENCH"


def send_packet(sock: socket.socket, payload: dict | str) -> str:
    raw = (json.dumps(payload) if isinstance(payload, dict) else payload) + "\r\n"
    sock.sendall(raw.encode("utf-8"))
    print(f"[TCP] → {raw[:120].strip()}")
    try:
        ack = sock.recv(256)
        print(f"[TCP] ← ACK: {ack!r}")
        return ack.decode("utf-8", errors="replace")
    except socket.timeout:
        print("[TCP] ← (no ACK within timeout — TBD with Scanvix)")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Storm RTU TCP Simulator")
    parser.add_argument("--host",       default=DEFAULT_HOST)
    parser.add_argument("--port",       type=int, default=DEFAULT_PORT)
    parser.add_argument("--device",     default=DEFAULT_DEVICE)
    parser.add_argument("--site",       default=DEFAULT_SITE)
    parser.add_argument("--count",      type=int, default=1)
    parser.add_argument("--interval",   type=float, default=2.0)
    parser.add_argument("--historical", action="store_true")
    args = parser.parse_args()

    print(f"[SIM] Connecting to {args.host}:{args.port} …")
    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.settimeout(5)
        print("[SIM] TCP connected")

        if args.historical:
            records = make_historical_batch(args.device, args.site, count=args.count)
            for record in records:
                send_packet(sock, record)
                time.sleep(args.interval)
        else:
            for i in range(args.count):
                payload = make_telemetry(args.device, args.site)
                send_packet(sock, payload)
                if i < args.count - 1:
                    time.sleep(args.interval)

    print("[SIM] Done.")


if __name__ == "__main__":
    main()
