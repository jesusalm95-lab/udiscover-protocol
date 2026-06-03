"""
Packet parser for U.Discover HID protocol.

[CONFIRMED] Packets arrive as ASCII text with the structure:
    %Z,NN,PAYLOAD_HEX,CHECKSUM#

where:
    %Z          — fixed prefix (purpose unknown but consistent)
    NN          — block index in hexadecimal (00..24)
    PAYLOAD_HEX — hexadecimal payload bytes
    CHECKSUM    — 4-hex-digit checksum (algorithm TBD — see checksum.py)
    #           — end-of-message sentinel
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# [CONFIRMED] pattern observed in real captures
_PACKET_RE = re.compile(
    r"^%Z,([0-9A-Fa-f]{2}),([0-9A-Fa-f]+),([0-9A-Fa-f]{4})#$"
)


class PacketParseError(ValueError):
    """Raised when a raw text string cannot be parsed as a valid packet."""


@dataclass(frozen=True)
class UDiscoverPacket:
    """
    One HID report decoded as a protocol packet.

    Attributes
    ----------
    prefix       : Always "%Z" (confirmed).
    block_index  : Integer index of the block within a frame (0x00..0x24).
    block_label  : Zero-padded hex string of the index, e.g. "01".
    payload_hex  : Raw hex string of the payload (even number of chars).
    checksum_hex : 4-char hex string. Algorithm under investigation.
    raw_text     : The original ASCII text as received from the device.
    """

    prefix: str
    block_index: int
    block_label: str
    payload_hex: str
    checksum_hex: str
    raw_text: str

    @property
    def payload_bytes(self) -> bytes:
        """Payload decoded to bytes."""
        return bytes.fromhex(self.payload_hex)

    @property
    def checksum_value(self) -> int:
        """Checksum field as integer."""
        return int(self.checksum_hex, 16)

    @property
    def payload_length(self) -> int:
        """Number of payload bytes."""
        return len(self.payload_bytes)


def parse_packet(text: str) -> UDiscoverPacket | None:
    """
    Parse a single ASCII line into a UDiscoverPacket.

    Returns None (rather than raising) for lines that look like noise
    (empty strings, partial reads). Raises PacketParseError for strings
    that start with '%Z' but are malformed.
    """
    text = text.strip()
    if not text:
        return None

    if not text.startswith("%Z"):
        return None

    m = _PACKET_RE.match(text)
    if m is None:
        raise PacketParseError(
            f"Malformed packet (starts with %Z but does not match expected "
            f"format): {text!r}"
        )

    block_label, payload_hex, checksum_hex = m.group(1), m.group(2), m.group(3)
    block_index = int(block_label, 16)

    if len(payload_hex) % 2 != 0:
        raise PacketParseError(
            f"Payload hex has odd length ({len(payload_hex)}) — "
            f"cannot decode to bytes: {text!r}"
        )

    return UDiscoverPacket(
        prefix="%Z",
        block_index=block_index,
        block_label=block_label,
        payload_hex=payload_hex.upper(),
        checksum_hex=checksum_hex.upper(),
        raw_text=text,
    )
