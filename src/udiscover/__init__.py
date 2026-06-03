"""
Relacart U.Discover Python SDK — Protocol Research Library

Status: RESEARCH / REVERSE ENGINEERING IN PROGRESS
Everything in this package reflects current understanding of the HID protocol.
Sections marked [CONFIRMED] have been verified with real hardware.
Sections marked [HYPOTHESIS] are educated guesses pending validation.
"""

from .device import UDiscoverDevice
from .packet import UDiscoverPacket, parse_packet
from .frame import UDiscoverFrame, UDiscoverFrameCollector

__all__ = [
    "UDiscoverDevice",
    "UDiscoverPacket",
    "parse_packet",
    "UDiscoverFrame",
    "UDiscoverFrameCollector",
]

# [CONFIRMED] Device identifiers
VENDOR_ID = 0x0F8B
PRODUCT_ID = 0x0051
PRODUCT_NAME = "U.Discover"
MANUFACTURER = "GigaDevice"

# [HYPOTHESIS] Frame structure — 25 blocks per frame (00..24)
FRAME_BLOCK_COUNT = 25
FRAME_FIRST_BLOCK = 0x00
FRAME_LAST_BLOCK = 0x24
