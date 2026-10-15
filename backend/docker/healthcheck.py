#!/usr/bin/env python3
"""
Storm Energy RTU — container healthcheck helper (stdlib only).

  storm-healthcheck http <url>        exit 0 if the URL answers HTTP 2xx
  storm-healthcheck tcp-listen <port> exit 0 if a socket is LISTENING on <port>

tcp-listen reads /proc/net/tcp{,6} instead of connecting, so healthchecks do not
open RTU sessions against the TCP listener or spam its logs.
"""
import sys
import urllib.request


def check_http(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return 0 if 200 <= resp.status < 300 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"healthcheck http failed: {exc}", file=sys.stderr)
        return 1


def check_tcp_listen(port: int) -> int:
    want = f"{port:04X}"
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    # parts[1] = local_address "HEXIP:HEXPORT", parts[3] = state (0A = LISTEN)
                    if len(parts) > 3 and parts[1].rsplit(":", 1)[-1] == want and parts[3] == "0A":
                        return 0
        except FileNotFoundError:
            continue
    print(f"healthcheck: nothing listening on port {port}", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("http", "tcp-listen"):
        print(__doc__, file=sys.stderr)
        return 2
    if sys.argv[1] == "http":
        return check_http(sys.argv[2])
    return check_tcp_listen(int(sys.argv[2]))


if __name__ == "__main__":
    sys.exit(main())
