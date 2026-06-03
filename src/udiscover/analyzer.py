"""
Payload analysis for U.Discover frames.

[STATUS] Exploratory — no interpretation is assumed correct.
All decodings are generated as hypotheses to be compared against
ground-truth data (e.g. CSV exports from the official software).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from .frame import UDiscoverFrame


# ------------------------------------------------------------------
# Interpretation registry
# ------------------------------------------------------------------

@dataclass
class Interpretation:
    name: str
    fmt: str        # struct format char
    size: int       # bytes per value
    signed: bool
    float_type: bool = False


INTERPRETATIONS: list[Interpretation] = [
    Interpretation("uint8",       "B", 1, False),
    Interpretation("int8",        "b", 1, True),
    Interpretation("uint16_le",   "<H", 2, False),
    Interpretation("uint16_be",   ">H", 2, False),
    Interpretation("int16_le",    "<h", 2, True),
    Interpretation("int16_be",    ">h", 2, True),
    Interpretation("uint24_le",   "",  3, False),   # handled specially
    Interpretation("uint24_be",   "",  3, False),
    Interpretation("uint32_le",   "<I", 4, False),
    Interpretation("uint32_be",   ">I", 4, False),
    Interpretation("float32_le",  "<f", 4, False, float_type=True),
    Interpretation("float32_be",  ">f", 4, False, float_type=True),
]


def _decode_values(data: bytes, interp: Interpretation) -> list[float]:
    values: list[float] = []
    n = len(data)

    if interp.name == "uint24_le":
        for i in range(0, n - 2, 3):
            v = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
            values.append(float(v))
    elif interp.name == "uint24_be":
        for i in range(0, n - 2, 3):
            v = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            values.append(float(v))
    elif interp.fmt:
        size = interp.size
        for i in range(0, n - size + 1, size):
            try:
                (v,) = struct.unpack_from(interp.fmt, data, i)
                values.append(float(v))
            except struct.error:
                pass
    return values


# ------------------------------------------------------------------
# Per-frame stats
# ------------------------------------------------------------------

@dataclass
class FrameStats:
    frame_number: int
    block_count: int
    total_payload_bytes: int
    payload_per_block: dict[str, int]  # block_label -> byte count


@dataclass
class FrameDiff:
    frame_a: int
    frame_b: int
    total_bytes: int
    changed_bytes: int

    @property
    def change_pct(self) -> float:
        return 100.0 * self.changed_bytes / self.total_bytes if self.total_bytes else 0.0


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def frame_stats(frame: UDiscoverFrame) -> FrameStats:
    payload_per_block = {}
    total = 0
    for idx in sorted(frame.packets):
        pkt = frame.packets[idx]
        n = pkt.payload_length
        payload_per_block[pkt.block_label] = n
        total += n
    return FrameStats(
        frame_number=frame.frame_number,
        block_count=len(frame.packets),
        total_payload_bytes=total,
        payload_per_block=payload_per_block,
    )


def frame_diff(frame_a: UDiscoverFrame, frame_b: UDiscoverFrame) -> FrameDiff:
    """Byte-level diff between the data payloads of two frames."""
    a = bytes.fromhex(frame_a.data_payload())
    b = bytes.fromhex(frame_b.data_payload())
    min_len = min(len(a), len(b))
    max_len = max(len(a), len(b))
    changed = sum(1 for i in range(min_len) if a[i] != b[i])
    changed += max_len - min_len  # extra bytes always count as changed
    return FrameDiff(
        frame_a=frame_a.frame_number,
        frame_b=frame_b.frame_number,
        total_bytes=max_len,
        changed_bytes=changed,
    )


def interpret_payload(data: bytes) -> dict[str, list[float]]:
    """
    Decode a bytes object under all registered interpretations.
    Returns a dict mapping interpretation name -> list of decoded values.
    """
    return {interp.name: _decode_values(data, interp) for interp in INTERPRETATIONS}


@dataclass
class InterpSummary:
    name: str
    count: int
    min_val: float
    max_val: float
    mean: float
    std: float
    notes: list[str] = field(default_factory=list)


def summarize_interpretation(name: str, values: list[float]) -> InterpSummary | None:
    if not values:
        return None

    import math

    min_v = min(values)
    max_v = max(values)
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)

    notes: list[str] = []

    # [HYPOTHESIS] plausibility heuristics — do NOT treat as ground truth
    if name.startswith("int") or name.startswith("float"):
        if -120 <= min_v and max_v <= 10:
            notes.append("HINT: range consistent with RF levels (dBm) — unconfirmed")
    if name in ("uint16_le", "uint16_be", "uint32_le", "uint32_be"):
        if 240_000 <= min_v <= 960_000 or 240 <= min_v <= 960:
            notes.append("HINT: range consistent with frequency axis (MHz) — unconfirmed")
    if std < 1.0:
        notes.append("Low variance — possibly constant / metadata field")

    return InterpSummary(
        name=name,
        count=len(values),
        min_val=min_v,
        max_val=max_v,
        mean=mean,
        std=std,
        notes=notes,
    )


def frames_to_csv_rows(
    frames: list[UDiscoverFrame],
) -> list[dict[str, Any]]:
    """
    Convert frames to a flat list of dicts suitable for CSV export.
    Each row = one byte in one block of one frame, under all interpretations.
    """
    rows = []
    for frame in frames:
        for block_idx in sorted(frame.packets):
            pkt = frame.packets[block_idx]
            data = pkt.payload_bytes
            interps = interpret_payload(data)

            for byte_offset, byte_val in enumerate(data):
                row: dict[str, Any] = {
                    "frame_number": frame.frame_number,
                    "block_index": block_idx,
                    "block_label": pkt.block_label,
                    "byte_offset": byte_offset,
                    "value_uint8": byte_val,
                }
                # Add aligned multi-byte interpretations at their start offsets
                for interp in INTERPRETATIONS:
                    if interp.size == 1:
                        continue
                    if byte_offset % interp.size == 0:
                        vals = interps.get(interp.name, [])
                        idx_in_vals = byte_offset // interp.size
                        row[f"value_{interp.name}"] = (
                            vals[idx_in_vals] if idx_in_vals < len(vals) else None
                        )
                rows.append(row)
    return rows
