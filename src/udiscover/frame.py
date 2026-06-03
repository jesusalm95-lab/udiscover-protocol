"""
Frame reconstruction for U.Discover HID protocol.

[HYPOTHESIS] A complete frame consists of 25 consecutive blocks
indexed 0x00..0x24. Block 0x00 is treated as the frame header.
Blocks 0x01..0x24 carry the spectrum payload.

This is not yet confirmed. The collector is written to be tolerant
of unexpected block counts so that we can observe the real structure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .packet import UDiscoverPacket

log = logging.getLogger(__name__)

# [HYPOTHESIS] expected block indices in one complete frame
EXPECTED_BLOCKS = set(range(0x00, 0x25))  # 00..24 inclusive
FRAME_SIZE = len(EXPECTED_BLOCKS)  # 25


@dataclass
class UDiscoverFrame:
    """
    One complete (or partial) scan frame assembled from individual packets.

    Attributes
    ----------
    frame_number : Sequential counter assigned by the collector.
    packets      : Dict mapping block_index -> UDiscoverPacket.
    created_at   : Unix timestamp of the first packet added to this frame.
    complete     : True only when all expected blocks are present.
    """

    frame_number: int
    packets: dict[int, UDiscoverPacket] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    complete: bool = False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_complete(self) -> bool:
        return EXPECTED_BLOCKS.issubset(self.packets.keys())

    def missing_blocks(self) -> list[int]:
        return sorted(EXPECTED_BLOCKS - self.packets.keys())

    def extra_blocks(self) -> list[int]:
        """Block indices present but not in the expected range."""
        return sorted(self.packets.keys() - EXPECTED_BLOCKS)

    def concatenated_payload(self, include_header: bool = True) -> str:
        """
        Hex string of all payload bytes concatenated in block order.

        Parameters
        ----------
        include_header : If False, block 0x00 is excluded.
                         [HYPOTHESIS] block 0x00 may be metadata, not spectrum data.
        """
        indices = sorted(self.packets.keys())
        if not include_header:
            indices = [i for i in indices if i != 0x00]
        return "".join(self.packets[i].payload_hex for i in indices)

    def data_payload(self) -> str:
        """
        [HYPOTHESIS] Spectrum data = blocks 0x01..0x24 only.
        Block 0x00 payload is short (8 bytes vs ~24 for others) and
        may carry frame metadata or device state.
        """
        return self.concatenated_payload(include_header=False)

    def to_dict(self) -> dict:
        blocks = {}
        for idx, pkt in sorted(self.packets.items()):
            blocks[pkt.block_label] = {
                "payload_hex": pkt.payload_hex,
                "checksum_hex": pkt.checksum_hex,
                "raw_text": pkt.raw_text,
            }
        return {
            "frame_number": self.frame_number,
            "created_at": self.created_at,
            "complete": self.complete,
            "block_count": len(self.packets),
            "missing_blocks": [f"{b:02X}" for b in self.missing_blocks()],
            "blocks": blocks,
            "concatenated_payload": self.concatenated_payload(),
            "data_payload": self.data_payload(),
        }


class UDiscoverFrameCollector:
    """
    Stateful collector that assembles packets into frames.

    A new frame begins every time block 0x00 arrives. When block 0x00
    arrives again the previous frame is sealed and returned (complete
    or not). Call flush() at the end of a session to retrieve the
    last in-progress frame.
    """

    def __init__(self) -> None:
        self._current: UDiscoverFrame | None = None
        self._frame_counter: int = 0
        self._incomplete_count: int = 0

    @property
    def frames_captured(self) -> int:
        return self._frame_counter

    @property
    def frames_incomplete(self) -> int:
        return self._incomplete_count

    def add_packet(self, packet: UDiscoverPacket) -> UDiscoverFrame | None:
        """
        Feed one packet to the collector.

        Returns a sealed UDiscoverFrame when the previous frame is
        closed by the arrival of a new block 0x00, otherwise None.
        """
        sealed: UDiscoverFrame | None = None

        if packet.block_index == 0x00:
            # Seal whatever was in progress
            if self._current is not None:
                sealed = self._seal(self._current)
            # Start new frame
            self._current = UDiscoverFrame(frame_number=self._frame_counter + 1)
            self._current.packets[packet.block_index] = packet
        else:
            if self._current is None:
                log.warning(
                    "Received block %s before any block 00 — discarding",
                    packet.block_label,
                )
                return None

            if packet.block_index in self._current.packets:
                log.warning(
                    "Duplicate block %s in frame %d — overwriting",
                    packet.block_label,
                    self._current.frame_number,
                )

            prev = max(self._current.packets.keys())
            if packet.block_index != prev + 1:
                log.warning(
                    "Non-consecutive block: expected %02X, got %s (frame %d)",
                    prev + 1,
                    packet.block_label,
                    self._current.frame_number,
                )

            self._current.packets[packet.block_index] = packet

        return sealed

    def flush(self) -> UDiscoverFrame | None:
        """Seal and return the last in-progress frame, if any."""
        if self._current is None:
            return None
        sealed = self._seal(self._current)
        self._current = None
        return sealed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _seal(self, frame: UDiscoverFrame) -> UDiscoverFrame:
        frame.complete = frame.is_complete()
        self._frame_counter += 1

        if not frame.complete:
            self._incomplete_count += 1
            log.warning(
                "Frame %d is INCOMPLETE — missing blocks: %s",
                frame.frame_number,
                [f"{b:02X}" for b in frame.missing_blocks()],
            )
        else:
            log.debug("Frame %d complete (%d blocks)", frame.frame_number, len(frame.packets))

        return frame
