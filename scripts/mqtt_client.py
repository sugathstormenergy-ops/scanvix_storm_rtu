#!/usr/bin/env python3
"""
Storm Energy RTU Platform — MQTT RTU Simulator.
Connects to the real Storm MQTT broker and publishes Scanvix telemetry.
Development tool — uses the same protocol as actual Scanvix hardware.

Usage:
  python scripts/mqtt_client.py --device 864012049873321 --site BENCH
  python scripts/mqtt_client.py --device 864012049873321 --historical
  python scripts/mqtt_client.py --device 864012049873321 --invalid
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import paho.mqtt.client as paho

sys.path.insert(0, "backend")
from scripts.telemetry_generator import (
    make_duplicate, make_historical_batch,
    make_invalid_payload, make_telemetry,
)

DEFAULT_HOST   = "localhost"
DEFAULT_PORT   = 1883
DEFAULT_DEVICE = "864012049873321"
DEFAULT_SITE   = "BENCH"
TOPIC_TEMPLATE = "storm/meters/{device_id}/telemetry"


def build_client(host: str, port: int, username: str = "", password: str = "") -> paho.Client:
    client = paho.Client(client_id=f"sim-{DEFAULT_DEVICE}", clean_session=True)
    if username:
        client.username_pw_set(username, password)
    client.on_connect    = lambda c, u, f, rc: print(f"[MQTT] Connected rc={rc}")
    client.on_disconnect = lambda c, u, rc:    print(f"[MQTT] Disconnected rc={rc}")
    client.on_publish    = lambda c, u, mid:   print(f"[MQTT] Published mid={mid}")
    client.connect(host, port, keepalive=60)
    client.loop_start()
    time.sleep(1)
    return client


def publish(client: paho.Client, device_id: str, payload: dict | str, qos: int = 1) -> None:
    topic = TOPIC_TEMPLATE.format(device_id=device_id)
    raw   = json.dumps(payload) if isinstance(payload, dict) else payload
    info  = client.publish(topic, raw, qos=qos)
    info.wait_for_publish(timeout=5)
    print(f"[MQTT] → {topic}\n       {raw[:120]}")


def main():
    parser = argparse.ArgumentParser(description="Storm RTU MQTT Simulator")
    parser.add_argument("--host",       default=DEFAULT_HOST)
    parser.add_argument("--port",       type=int, default=DEFAULT_PORT)
    parser.add_argument("--device",     default=DEFAULT_DEVICE)
    parser.add_argument("--site",       default=DEFAULT_SITE)
    parser.add_argument("--count",      type=int, default=1, help="Messages to send")
    parser.add_argument("--interval",   type=float, default=1.0, help="Seconds between messages")
    parser.add_argument("--historical", action="store_true", help="Send historical batch")
    parser.add_argument("--invalid",    action="store_true", help="Send invalid payload")
    parser.add_argument("--duplicate",  action="store_true", help="Send duplicate payload")
    parser.add_argument("--username",   default="")
    parser.add_argument("--password",   default="")
    args = parser.parse_args()

    client = build_client(args.host, args.port, args.username, args.password)

    try:
        if args.invalid:
            publish(client, args.device, make_invalid_payload())

        elif args.historical:
            batch = make_historical_batch(args.device, args.site, count=args.count)
            for record in batch:
                publish(client, args.device, record)
                time.sleep(args.interval)

        elif args.duplicate:
            payload = make_telemetry(args.device, args.site)
            print("[SIM] Sending original…")
            publish(client, args.device, payload)
            time.sleep(args.interval)
            print("[SIM] Sending duplicate…")
            publish(client, args.device, make_duplicate(payload))

        else:
            for i in range(args.count):
                payload = make_telemetry(args.device, args.site)
                publish(client, args.device, payload)
                if i < args.count - 1:
                    time.sleep(args.interval)

    finally:
        client.loop_stop()
        client.disconnect()
        print("[SIM] Done.")


if __name__ == "__main__":
    main()
