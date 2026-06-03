"""
Packet parser for U.Discover HID protocol.

[CONFIRMED] Packets arrive as ASCII text with the structure:
    %Z,NN,PAYLOAD_HEX,CHECKSUM#

where:
    %Z          — fixed prefix (purpose unknown but consistent)
    NN          — block index in hexadecimal (00..24)
    PAYLOAD_HEX — hexadecimal payload (49 nibbles for data blocks, 16 for block 00)
    CHECKSUM    — 4-hex-digit checksum (algorithm TBD — see checksum.py)
    #           — end-of-message sentinel

[CONFIRMED] Payload structure for data blocks (0x01–0x24):
    49 nibbles = 7 samples × 7 nibbles/sample
    Each sample: FFFF XYZ
        FFFF = 4-nibble frequency register (16-bit, monotonically increasing)
        X    = level high nibble
        Y    = middle nibble (usually 0x0, purpose under investigation)
        Z    = level low nibble
        level_byte = (X << 4) | Z  →  0–255  → approx −102 to −62 dBm
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# [CONFIRMED] 49-nibble data blocks and 16-nibble header block both match this regex
_PACKET_RE = re.compile(
    r"^%Z,([0-9A-Fa-f]{2}),([0-9A-Fa-f]+),([0-9A-Fa-f]{4})#$"
)

# [CONFIRMED] samples per data block (7-nibble groups in 49-nibble payload)
SAMPLES_PER_BLOCK = 7
NIBBLES_PER_SAMPLE = 7


class PacketParseError(ValueError):
    """Raised when a raw text string cannot be parsed as a valid packet."""


@dataclass(frozen=True)
class UDiscoverPacket:
    """
    One HID report decoded as a protocol packet.

    Attributes
    ----------
    prefix        : Always "%Z" (confirmed).
    block_index   : Integer index of the block within a frame (0x00..0x24).
    block_label   : Zero-padded hex string of the index, e.g. "01".
    payload_hex   : Raw hex string of the payload, ALL nibbles preserved.
                    Block 0x00 → 16 nibbles (8 bytes).
                    Blocks 0x01–0x24 → 49 nibbles (7 samples × 7 nibbles).
    checksum_hex  : 4-char hex string. Algorithm under investigation.
    raw_text      : The original ASCII text as received from the device.
    """

    prefix: str
    block_index: int
    block_label: str
    payload_hex: str
    checksum_hex: str
    raw_text: str

    @property
    def payload_bytes(self) -> bytes:
        """
        Payload decoded to whole bytes only (truncates any trailing nibble).
        For analysis of individual nibbles use payload_hex directly.
        """
        hex_str = self.payload_hex
        if len(hex_str) % 2 != 0:
            hex_str = hex_str[:-1]
        return bytes.fromhex(hex_str)

    @property
    def payload_nibbles(self) -> str:
        """Full payload as a hex string, preserving all nibbles."""
        return self.payload_hex

    @property
    def checksum_value(self) -> int:
        """Checksum field as integer."""
        return int(self.checksum_hex, 16)

    @property
    def payload_length(self) -> int:
        """Number of whole payload bytes (trailing nibble excluded)."""
        return len(self.payload_hex) // 2

    def samples(self) -> list[tuple[int, int, int]]:
        """
        [CONFIRMED] Decode data blocks (0x01–0x24) into individual samples.

        Returns a list of (freq_reg, level_byte, middle_nibble) tuples:
            freq_reg      : 16-bit frequency register (monotonically increasing)
            level_byte    : 8-bit level = (nibble[4] << 4) | nibble[6]
            middle_nibble : nibble[5], usually 0x0, purpose TBD

        Returns [] for block 0x00 (header block).
        """
        if self.block_index == 0x00:
            return []
        raw = self.payload_hex
        if len(raw) < 49:
            raw = raw.ljust(49, '0')  # pad if truncated
        result = []
        for i in range(0, SAMPLES_PER_BLOCK * NIBBLES_PER_SAMPLE, NIBBLES_PER_SAMPLE):
            group = raw[i:i + NIBBLES_PER_SAMPLE]
            if len(group) < NIBBLES_PER_SAMPLE:
                break
            freq_reg = int(group[0:4], 16)
            mid = int(group[5], 16)
            level_byte = (int(group[4], 16) << 4) | int(group[6], 16)
            result.append((freq_reg, level_byte, mid))
        return result


def parse_packet(text: str) -> UDiscoverPacket | None:
    """
    Parse a single ASCII line into a UDiscoverPacket.

    Returns None for empty/non-matching lines.
    Raises PacketParseError for lines starting with '%Z' that are malformed.
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

    return UDiscoverPacket(
        prefix="%Z",
        block_index=block_index,
        block_label=block_label,
        payload_hex=payload_hex.upper(),
        checksum_hex=checksum_hex.upper(),
        raw_text=text,
    )
