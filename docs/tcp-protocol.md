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

## Scanvix production frame (`#SP`) - confirmed from a real captured packet

Scanvix confirmed the captured packet as the production TCP frame; the wire format is authoritative.
Implemented by `ScanvixSpFrameParser` (`backend/app/protocol/tcp_parser.py`):

```
#SP,<device id>,NUL<IMEI>,HH:MM:SS,DD/MM/YYYY,<sensor byte>,<signal>,<firmware>NUL,
<4-byte binary field>, ... ,00000,00000,00000,00000,00000,00000,00000,.
```

- IMEI (15 digits, leading NUL stripped) is the device identity used for the Devices lookup. Unknown IMEIs are
  UNKNOWN_DEVICE; nothing is auto-registered. `STORM-ENER` is the frame's device field and is not persisted.
- Sensor byte `0x01` = RS485 (`rs485`). Signal is stored as received (28). Firmware `V001`.
- 8 or 9 comma-terminated 4-byte binary fields (captured packet: 8 = 146 bytes; the field list: 9 = 151 bytes),
  Instant Flow, Positive Totaliser, AI3, AI4, AI5, Today Total, Previous Day Total, 4-20mA 1, 4-20mA 2.
  Located by position, never split on commas.
- **Open item:** byte order and REAL4/LONG type are not confirmed. Only the all-zero value is decoded;
  any non-zero binary field is rejected as a visible PARSE ERROR (raw bytes in the message) rather than guessed.
  Implement `ScanvixSpFrameParser.decode_binary_field` once Scanvix confirms the encoding.
- Persisted: flow, total_today, total_yesterday, sensor_type, signal, firmware, READ01-READ05 (first five trailing
  fields). Not persisted (no model field): positive totaliser, AI3-5, 4-20mA inputs, trailing fields 6-7.
- No flow unit is sent, so none is stored (analytics reports such meters as excluded rather than guessing).

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
