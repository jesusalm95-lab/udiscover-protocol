"""
Tests for src/udiscover/packet.py

Uses real hardware captures as fixtures. No synthetic data invented.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.packet import parse_packet, UDiscoverPacket, PacketParseError


# ---------------------------------------------------------------------------
# Real examples from hardware (CONFIRMED captures)
# ---------------------------------------------------------------------------

# Block 00 (header block) — always 16 hex chars (8 bytes)
HEADER_PACKET = "%Z,00,30D40927C0010000,00E8#"

# Data blocks (01–24h) — 49 hex chars (7 samples × 7 nibbles)
DATA_PACKETS = [
    "%Z,01,7A2B20A7A69F0A7A831097AB550C7AF420A7B19D0C7B71C0A,0077#",
    "%Z,02,7B8AE097BD640B7BE2D097C1510A7C6070B7C92B1B7CB8609,0042#",
    "%Z,03,7CDE10C7D2970A7D4F2097D8160C7DCCC0C7DE5E0C7E24B0E,00A2#",
    "%Z,24,AA42615AA68114AAA6E15A96CD00A9ABA00A9DDE00AA03900,005F#",
]

ALL_REAL_PACKETS = [HEADER_PACKET] + DATA_PACKETS


class TestParsePacketValid:
    def test_returns_packet_dataclass(self):
        pkt = parse_packet(HEADER_PACKET)
        assert isinstance(pkt, UDiscoverPacket)

    def test_prefix_is_percent_z(self):
        for raw in ALL_REAL_PACKETS:
            pkt = parse_packet(raw)
            assert pkt.prefix == "%Z"

    def test_block_index_header(self):
        pkt = parse_packet(HEADER_PACKET)
        assert pkt.block_index == 0x00

    def test_block_index_data_blocks(self):
        cases = [
            (DATA_PACKETS[0], 0x01),
            (DATA_PACKETS[1], 0x02),
            (DATA_PACKETS[3], 0x24),
        ]
        for raw, expected in cases:
            assert parse_packet(raw).block_index == expected

    def test_block_label_is_zero_padded_hex(self):
        pkt = parse_packet(DATA_PACKETS[0])
        assert pkt.block_label == "01"

    def test_payload_hex_preserved_uppercase(self):
        pkt = parse_packet(DATA_PACKETS[0])
        assert pkt.payload_hex == pkt.payload_hex.upper()

    def test_header_payload_length(self):
        pkt = parse_packet(HEADER_PACKET)
        assert len(pkt.payload_hex) == 16   # 8 bytes = 16 nibbles

    def test_data_payload_nibble_count(self):
        # [CONFIRMED] data blocks have 49 nibbles (7 samples × 7 nibbles)
        pkt = parse_packet(DATA_PACKETS[0])
        assert len(pkt.payload_hex) == 49

    def test_payload_bytes_header(self):
        pkt = parse_packet(HEADER_PACKET)
        assert pkt.payload_bytes == bytes.fromhex("30D40927C0010000")

    def test_payload_bytes_truncates_trailing_nibble(self):
        # data blocks have 49 nibbles; payload_bytes returns 24 whole bytes
        pkt = parse_packet(DATA_PACKETS[0])
        assert pkt.payload_length == 24
        assert len(pkt.payload_bytes) == 24

    def test_checksum_hex_is_uppercase(self):
        pkt = parse_packet(HEADER_PACKET)
        assert pkt.checksum_hex == pkt.checksum_hex.upper()

    def test_checksum_value_as_int(self):
        pkt = parse_packet(HEADER_PACKET)
        assert pkt.checksum_value == 0x00E8

    def test_raw_text_is_preserved(self):
        raw = DATA_PACKETS[0]
        pkt = parse_packet(raw)
        assert pkt.raw_text == raw

    def test_whitespace_stripped_before_parsing(self):
        raw = f"  {HEADER_PACKET}  "
        pkt = parse_packet(raw)
        assert pkt is not None
        assert pkt.block_index == 0x00

    def test_all_real_packets_parse_without_error(self):
        for raw in ALL_REAL_PACKETS:
            pkt = parse_packet(raw)
            assert pkt is not None, f"None returned for {raw!r}"


class TestSamplesMethod:
    """Tests for UDiscoverPacket.samples() — 7-nibble decode."""

    def test_header_block_returns_empty(self):
        pkt = parse_packet(HEADER_PACKET)
        assert pkt.samples() == []

    def test_data_block_returns_seven_samples(self):
        pkt = parse_packet(DATA_PACKETS[0])
        samples = pkt.samples()
        assert len(samples) == 7

    def test_sample_is_three_tuple(self):
        pkt = parse_packet(DATA_PACKETS[0])
        for sample in pkt.samples():
            assert len(sample) == 3  # (freq_reg, level_byte, middle_nibble)

    def test_freq_reg_first_sample_block01(self):
        # [CONFIRMED] first sample of block 01 = freq register 0x7A2B = 31275
        pkt = parse_packet(DATA_PACKETS[0])
        freq_reg, _, _ = pkt.samples()[0]
        assert freq_reg == 0x7A2B

    def test_freq_registers_monotonically_increasing_within_block(self):
        pkt = parse_packet(DATA_PACKETS[0])
        freqs = [s[0] for s in pkt.samples()]
        assert all(freqs[i] < freqs[i + 1] for i in range(len(freqs) - 1))

    def test_level_byte_in_range(self):
        for raw in DATA_PACKETS:
            pkt = parse_packet(raw)
            for _, level_byte, _ in pkt.samples():
                assert 0 <= level_byte <= 255

    def test_level_byte_encoding_first_sample(self):
        # Block 01, group 1: level nibbles = "20A" → byte = (2<<4)|A = 0x2A = 42
        pkt = parse_packet(DATA_PACKETS[0])
        _, level_byte, _ = pkt.samples()[0]
        assert level_byte == 0x2A  # (0x2 << 4) | 0xA

    def test_middle_nibble_is_typically_zero(self):
        # [CONFIRMED] middle nibble of level field is usually 0x0
        total, zeros = 0, 0
        for raw in DATA_PACKETS:
            pkt = parse_packet(raw)
            for _, _, mid in pkt.samples():
                total += 1
                if mid == 0:
                    zeros += 1
        assert zeros / total > 0.8  # at least 80% are zero


class TestParsePacketEdgeCases:
    def test_empty_string_returns_none(self):
        assert parse_packet("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_packet("   \n\t") is None

    def test_unrelated_text_returns_none(self):
        assert parse_packet("hello world") is None

    def test_partial_prefix_returns_none(self):
        assert parse_packet("%") is None

    def test_malformed_percent_z_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,not-hex,AABBCC,00FF#")

    def test_missing_hash_sentinel_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,01,AABBCCDD,00FF")

    def test_checksum_wrong_length_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,01,AABB,FF#")

    def test_missing_checksum_field_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,01,AABBCCDD#")


class TestUDiscoverPacketImmutability:
    def test_packet_is_frozen(self):
        pkt = parse_packet(HEADER_PACKET)
        with pytest.raises((AttributeError, TypeError)):
            pkt.block_index = 99  # type: ignore[misc]
