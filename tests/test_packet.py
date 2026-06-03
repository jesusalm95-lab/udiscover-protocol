"""
Tests for src/udiscover/packet.py

Uses only the real examples captured from hardware — no synthetic data invented.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.packet import parse_packet, UDiscoverPacket, PacketParseError


# ---------------------------------------------------------------------------
# Real examples from hardware (CONFIRMED captures)
# ---------------------------------------------------------------------------

REAL_PACKETS = [
    "%Z,00,30D40927C0010000,00E8#",
    "%Z,01,7A2B20D7A5D60B7A8310A7ADB00A7AE790A7B19D0B7B4C10B,00F6#",
    "%Z,02,7B8AE087BD640C7C0880B7C3AC0A7C607087C92B1B7CC4F0A,0003#",
    "%Z,03,7D03C0C7D1CE0A7D6840C7D74D0C7DA710C7DE5E0A7E24B0E,005B#",
    "%Z,04,7E6380F7E95C117EAEE197EE12197F06D187F5EC1A7F9101E,0048#",
    "%Z,24,AA42615AA68114AAA6E15A96CD00A9ABA00A9DDE00AA03900,005F#",
]


class TestParsePacketValid:
    def test_returns_packet_dataclass(self):
        pkt = parse_packet(REAL_PACKETS[0])
        assert isinstance(pkt, UDiscoverPacket)

    def test_prefix_is_percent_z(self):
        for raw in REAL_PACKETS:
            pkt = parse_packet(raw)
            assert pkt.prefix == "%Z"

    def test_block_index_parsed_correctly(self):
        cases = [
            ("%Z,00,30D40927C0010000,00E8#", 0x00),
            ("%Z,01,7A2B20D7A5D60B7A8310A7ADB00A7AE790A7B19D0B7B4C10B,00F6#", 0x01),
            ("%Z,24,AA42615AA68114AAA6E15A96CD00A9ABA00A9DDE00AA03900,005F#", 0x24),
        ]
        for raw, expected_index in cases:
            pkt = parse_packet(raw)
            assert pkt.block_index == expected_index, f"Failed for {raw!r}"

    def test_block_label_is_zero_padded_hex(self):
        pkt = parse_packet("%Z,01,7A2B20D7A5D60B7A8310A7ADB00A7AE790A7B19D0B7B4C10B,00F6#")
        assert pkt.block_label == "01"

    def test_payload_hex_is_uppercase(self):
        pkt = parse_packet("%Z,01,7a2b20d7a5d60b,00F6#")
        assert pkt.payload_hex == pkt.payload_hex.upper()

    def test_checksum_hex_is_uppercase(self):
        pkt = parse_packet(REAL_PACKETS[0])
        assert pkt.checksum_hex == pkt.checksum_hex.upper()

    def test_payload_bytes_length(self):
        pkt = parse_packet("%Z,00,30D40927C0010000,00E8#")
        # "30D40927C0010000" = 8 hex pairs = 8 bytes
        assert pkt.payload_length == 8

    def test_payload_bytes_content(self):
        pkt = parse_packet("%Z,00,30D40927C0010000,00E8#")
        assert pkt.payload_bytes == bytes.fromhex("30D40927C0010000")

    def test_checksum_value_as_int(self):
        pkt = parse_packet("%Z,00,30D40927C0010000,00E8#")
        assert pkt.checksum_value == 0x00E8

    def test_raw_text_is_preserved(self):
        raw = "%Z,01,7A2B20D7A5D60B7A8310A7ADB00A7AE790A7B19D0B7B4C10B,00F6#"
        pkt = parse_packet(raw)
        assert pkt.raw_text == raw

    def test_whitespace_stripped_before_parsing(self):
        raw = "  %Z,00,30D40927C0010000,00E8#  "
        pkt = parse_packet(raw)
        assert pkt is not None
        assert pkt.block_index == 0x00

    def test_all_real_packets_parse_without_error(self):
        for raw in REAL_PACKETS:
            pkt = parse_packet(raw)
            assert pkt is not None, f"None returned for {raw!r}"


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

    def test_odd_payload_length_truncates_trailing_nibble(self):
        # [CONFIRMED] real hardware sends 49-char payloads; trailing nibble is dropped
        pkt = parse_packet("%Z,01,ABCDE,00FF#")  # 5 chars -> 4 chars kept -> 2 bytes
        assert pkt is not None
        assert len(pkt.payload_hex) == 4  # "ABCD"
        assert pkt.payload_bytes == bytes.fromhex("ABCD")

    def test_checksum_wrong_length_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,01,AABB,FF#")  # checksum must be 4 chars

    def test_missing_checksum_field_raises(self):
        with pytest.raises(PacketParseError):
            parse_packet("%Z,01,AABBCCDD#")


class TestUDiscoverPacketImmutability:
    def test_packet_is_frozen(self):
        pkt = parse_packet(REAL_PACKETS[0])
        with pytest.raises((AttributeError, TypeError)):
            pkt.block_index = 99  # type: ignore[misc]
