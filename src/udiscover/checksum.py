"""
Checksum/CRC analysis for U.Discover packets.

[STATUS] Algorithm not yet identified. This module probes multiple
common algorithms against real packets to find a match.

Known examples:
    %Z,00,30D40927C0010000,00E8#
    %Z,01,7A2B20D7A5D60B7A8310A7ADB00A7AE790A7B19D0B7B4C10B,00F6#
    %Z,02,7B8AE087BD640C7C0880B7C3AC0A7C607087C92B1B7CC4F0A,0003#
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .packet import UDiscoverPacket


# ------------------------------------------------------------------
# Candidate algorithms
# ------------------------------------------------------------------

def _sum_bytes(data: bytes) -> int:
    return sum(data) & 0xFFFF


def _xor_bytes(data: bytes) -> int:
    result = 0
    for b in data:
        result ^= b
    return result & 0xFFFF


def _crc16(data: bytes, poly: int, init: int, ref_in: bool, ref_out: bool, xor_out: int) -> int:
    crc = init
    for byte in data:
        if ref_in:
            byte = int(f"{byte:08b}"[::-1], 2)
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    if ref_out:
        crc = int(f"{crc:016b}"[::-1], 2)
    return crc ^ xor_out


def _crc16_ibm(data: bytes) -> int:
    return _crc16(data, 0x8005, 0x0000, True, True, 0x0000)


def _crc16_ccitt_false(data: bytes) -> int:
    return _crc16(data, 0x1021, 0xFFFF, False, False, 0x0000)


def _crc16_xmodem(data: bytes) -> int:
    return _crc16(data, 0x1021, 0x0000, False, False, 0x0000)


def _crc16_modbus(data: bytes) -> int:
    return _crc16(data, 0x8005, 0xFFFF, True, True, 0x0000)


def _crc16_kermit(data: bytes) -> int:
    return _crc16(data, 0x1021, 0x0000, True, True, 0x0000)


# ------------------------------------------------------------------
# Input variants — what bytes to feed to the algorithm
# ------------------------------------------------------------------

def _input_payload(pkt: UDiscoverPacket) -> bytes:
    """Just the payload bytes."""
    return pkt.payload_bytes


def _input_index_payload(pkt: UDiscoverPacket) -> bytes:
    """Block index byte + payload bytes."""
    return bytes([pkt.block_index]) + pkt.payload_bytes


def _input_full_text(pkt: UDiscoverPacket) -> bytes:
    """Full ASCII text up to (not including) the checksum field."""
    # "%Z,NN,PAYLOAD," — strip trailing checksum and '#'
    text = pkt.raw_text
    last_comma = text.rfind(",")
    if last_comma == -1:
        return text.encode("ascii")
    return text[:last_comma].encode("ascii")


@dataclass
class ChecksumCandidate:
    name: str
    algorithm: Callable[[bytes], int]
    input_builder: Callable[[UDiscoverPacket], bytes]
    endian_swap: bool = False  # swap bytes of result before comparing

    def compute(self, pkt: UDiscoverPacket) -> int:
        data = self.input_builder(pkt)
        result = self.algorithm(data)
        if self.endian_swap:
            result = ((result & 0xFF) << 8) | ((result >> 8) & 0xFF)
        return result & 0xFFFF


CANDIDATES: list[ChecksumCandidate] = [
    ChecksumCandidate("sum_payload", _sum_bytes, _input_payload),
    ChecksumCandidate("sum_payload_swap", _sum_bytes, _input_payload, endian_swap=True),
    ChecksumCandidate("sum_index_payload", _sum_bytes, _input_index_payload),
    ChecksumCandidate("sum_full_text", _sum_bytes, _input_full_text),
    ChecksumCandidate("xor_payload", _xor_bytes, _input_payload),
    ChecksumCandidate("xor_index_payload", _xor_bytes, _input_index_payload),
    ChecksumCandidate("xor_full_text", _xor_bytes, _input_full_text),
    ChecksumCandidate("crc16_ibm_payload", _crc16_ibm, _input_payload),
    ChecksumCandidate("crc16_ibm_index_payload", _crc16_ibm, _input_index_payload),
    ChecksumCandidate("crc16_ibm_full_text", _crc16_ibm, _input_full_text),
    ChecksumCandidate("crc16_ccitt_false_payload", _crc16_ccitt_false, _input_payload),
    ChecksumCandidate("crc16_xmodem_payload", _crc16_xmodem, _input_payload),
    ChecksumCandidate("crc16_xmodem_full_text", _crc16_xmodem, _input_full_text),
    ChecksumCandidate("crc16_modbus_payload", _crc16_modbus, _input_payload),
    ChecksumCandidate("crc16_kermit_payload", _crc16_kermit, _input_payload),
    ChecksumCandidate("crc16_ibm_payload_swap", _crc16_ibm, _input_payload, endian_swap=True),
    ChecksumCandidate("crc16_xmodem_payload_swap", _crc16_xmodem, _input_payload, endian_swap=True),
    ChecksumCandidate("crc16_modbus_payload_swap", _crc16_modbus, _input_payload, endian_swap=True),
]


# ------------------------------------------------------------------
# Probe
# ------------------------------------------------------------------

@dataclass
class ProbeResult:
    candidate_name: str
    matches: int
    total: int

    @property
    def match_rate(self) -> float:
        return self.matches / self.total if self.total else 0.0

    def __str__(self) -> str:
        return (
            f"{self.candidate_name:<40s}  "
            f"{self.matches:3d}/{self.total}  "
            f"({self.match_rate * 100:.1f}%)"
        )


def probe_packets(packets: list[UDiscoverPacket]) -> list[ProbeResult]:
    """
    Test all candidate algorithms against a list of packets.

    Returns results sorted by descending match count.
    """
    if not packets:
        return []

    results = []
    for cand in CANDIDATES:
        matches = sum(
            1 for pkt in packets if cand.compute(pkt) == pkt.checksum_value
        )
        results.append(ProbeResult(cand.name, matches, len(packets)))

    return sorted(results, key=lambda r: r.matches, reverse=True)


def verify_packet(pkt: UDiscoverPacket, algorithm_name: str) -> bool:
    """Verify a single packet against a named candidate algorithm."""
    for cand in CANDIDATES:
        if cand.name == algorithm_name:
            return cand.compute(pkt) == pkt.checksum_value
    raise ValueError(f"Unknown algorithm: {algorithm_name!r}")
