# Storm Energy RTU Platform — TCP Protocol

## Status: PARTIALLY TBD

The TCP transport is confirmed (Scanvix RTU V1.3 spec: "Device support TCP protocol").  
The exact packet framing has **NOT** yet been finalised with Scanvix.

## Connection

- Host: configured via `TCP_HOST` (default `0.0.0.0`)
- Port: `TCP_PORT` (default `8100`)
- Protocol: raw TCP, ASCII encoding
- One persistent connection per RTU

## Parser Strategy

The server uses a pluggable parser chain:

1. **JsonOverTcpParser** — if the packet is `{...}` JSON, parse it as MQTT JSON. Handles RTU firmware that sends JSON over TCP.
2. **PlaceholderAsciiParser** — pipe-delimited ASCII (internal testing placeholder only). **NOT confirmed with Scanvix.**

When the final Scanvix frame specification is received, add a concrete parser class in `backend/app/protocol/tcp_parser.py` implementing `TcpParser`. No other files need to change.

## ACK Mechanism — TBD

**The server-to-RTU acknowledgement byte sequence has not been agreed with Scanvix.**

Current implementation: `NullAckStrategy` — no ACK bytes sent.  
A `SimpleOkAckStrategy` placeholder (`OK\r\n` / `ERR\r\n`) is included but **must not be deployed to production** without Scanvix confirmation.

To change the ACK strategy, modify `get_ack_strategy()` in `tcp_parser.py`.

## Raw Message Storage

Every TCP packet — valid or invalid — is stored in `RawMessages` before any parsing attempt.

## Items Requiring Scanvix Confirmation

- [ ] Final ASCII frame format and field order
- [ ] Frame delimiter (CRLF? fixed-length? length-prefix?)
- [ ] ACK byte sequence
- [ ] Reconnect behaviour after network outage
- [ ] Store-and-forward packet format over TCP
