"""
Probe for the HID initialization command that makes U.Discover start streaming
WITHOUT the official software running.

Steps:
1. Close U.Discover software completely.
2. Run this script.
3. It tries various write sequences and reports which one produces data.

Usage:
    python tools/init_probe.py
    python tools/init_probe.py --raw     # dump raw HID bytes received
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import hid

VID = 0x0F8B
PID = 0x0051

# Candidate init sequences to try (each is one HID output report)
CANDIDATES = [
    # common "start" bytes for spectrum analyzers
    [0x00, 0x01],
    [0x00, 0x02],
    [0x00, 0x03],
    [0x00, 0x0A],
    [0x00, 0x0B],
    [0x00, 0xA5],
    [0x00, 0xAA],
    [0x00, 0xFF],
    # single-byte
    [0x01],
    [0x02],
    [0x0A],
    # longer patterns
    [0x00, 0x01, 0x00, 0x00],
    [0x00, 0x02, 0x00, 0x00],
    [0x00, 0x01, 0x01, 0xF4, 0x02, 0xBC],  # start=500 MHz, end=700 MHz in some encodings
    # try the header bytes seen in block 00
    [0x00, 0x30, 0xD4, 0x09, 0x27, 0xC0, 0x01, 0x00, 0x00],
]


def _has_data(dev, timeout_ms: int = 300) -> bool:
    """Return True if the device sends any data within timeout_ms."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < timeout_ms:
        data = dev.read(64, timeout_ms=100)
        if data:
            text = bytes(data).decode("ascii", errors="ignore").replace("\x00", "").strip()
            if text.startswith("%Z"):
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe U.Discover HID init sequence")
    parser.add_argument("--raw", action="store_true", help="Dump raw HID bytes")
    args = parser.parse_args()

    print("Opening U.Discover HID device…")
    dev = hid.device()
    try:
        dev.open(VID, PID)
    except OSError as e:
        print(f"ERROR: {e}")
        print("Make sure U.Discover software is CLOSED and the device is connected.")
        sys.exit(1)

    dev.set_nonblocking(0)
    print("Device opened.\n")

    # First: check if device streams WITHOUT any write
    print("Test 0: checking if device streams without any command…")
    if _has_data(dev, timeout_ms=800):
        print("  ✓ Device streams WITHOUT initialization! No command needed.\n")
        dev.close()
        return
    else:
        print("  ✗ No data without init command.\n")

    # Try each candidate
    winner = None
    for i, seq in enumerate(CANDIDATES):
        hex_str = " ".join(f"{b:02X}" for b in seq)
        print(f"Test {i+1}: writing [{hex_str}]… ", end="", flush=True)
        try:
            dev.write(seq)
        except Exception as exc:
            print(f"write failed: {exc}")
            continue
        time.sleep(0.05)
        if _has_data(dev, timeout_ms=600):
            print("✓ DATA RECEIVED!")
            winner = seq
            break
        else:
            print("no data")

    dev.close()

    print()
    if winner:
        hex_str = " ".join(f"{b:02X}" for b in winner)
        print(f"SUCCESS — init sequence found: [{hex_str}]")
        print()
        print("Add this to spectrum_viewer.py and device.py:")
        print(f"  _INIT_SEQUENCES = [{winner}]")
        print()
        print("Or use it directly:")
        print(f"  device._device.write({winner})")
    else:
        print("No candidate worked.")
        print()
        print("Next step: capture HID writes with a USB sniffer.")
        print("  1. Install USBPcap: https://desowin.org/usbpcap/")
        print("  2. Open Wireshark → capture USB interface where U.Discover is connected")
        print("  3. Open U.Discover software")
        print("  4. Filter: usb.transfer_type == 0x01 (interrupt) && usb.endpoint_address.direction == OUT")
        print("  5. Note the bytes in the first few OUT packets → that's the init sequence")


if __name__ == "__main__":
    main()
