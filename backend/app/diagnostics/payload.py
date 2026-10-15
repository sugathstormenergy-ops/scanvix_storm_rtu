"""
Storm Energy RTU Platform - safe payload rendering for the Protocol Test Log.

Raw bytes from the network are NEVER interpreted: they are stored either as text
(when the bytes are valid UTF-8 without control characters other than TAB/CR/LF) or
as spaced hexadecimal (binary / probing traffic), and truncated to a fixed maximum.
HTML/JS safety is enforced where the value is displayed (the React UI renders it as
text, never as markup); here we only guarantee bounded, printable storage.
"""
from __future__ import annotations

from dataclasses import dataclass

_ALLOWED_CONTROL = {"\t", "\r", "\n"}


@dataclass(frozen=True)
class RenderedPayload:
    text: str          # stored representation (<= max_chars)
    encoding: str      # "TEXT" | "HEX"
    size: int          # original size in bytes
    truncated: bool


def _is_printable_text(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if (o < 32 and ch not in _ALLOWED_CONTROL) or o == 127 or 0x80 <= o <= 0x9F:
            return False
    return True


def render_payload(raw: bytes | bytearray | str | None, max_chars: int = 4000) -> RenderedPayload:
    if raw is None:
        raw = b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="replace")
    raw = bytes(raw)
    size = len(raw)
    try:
        text = raw.decode("utf-8")
        if _is_printable_text(text):
            truncated = len(text) > max_chars
            return RenderedPayload(text[:max_chars], "TEXT", size, truncated)
    except UnicodeDecodeError:
        pass
    # Binary / non-printable: spaced hex, 3 characters per byte.
    max_bytes = max(1, (max_chars + 1) // 3)
    shown = raw[:max_bytes]
    return RenderedPayload(shown.hex(" ").upper(), "HEX", size, size > len(shown))
