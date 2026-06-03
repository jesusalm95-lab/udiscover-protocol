"""
Show raw HID bytes (hex + ASCII) for diagnostic purposes.

Usage:
    python tools/read_raw.py
    python tools/read_raw.py --reports 20
"""

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.device import UDiscoverDevice


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump raw HID reports from U.Discover")
    parser.add_argument("--reports", type=int, default=0,
                        help="Stop after N reports (0 = run forever)")
    args = parser.parse_args()

    device = UDiscoverDevice()

    running = True

    def _stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)

    count = 0
    try:
        device.connect()
        print("Connected. Press Ctrl+C to stop.\n")
        print(f"{'Report':>6}  {'Hex':48s}  ASCII")
        print("-" * 80)

        while running:
            raw = device.read_raw()
            if not raw:
                continue

            hex_str = " ".join(f"{b:02X}" for b in raw)
            ascii_str = "".join(
                chr(b) if 0x20 <= b < 0x7F else "." for b in raw
            )

            count += 1
            print(f"{count:6d}  {hex_str:<48s}  {ascii_str}")

            if args.reports and count >= args.reports:
                break

    finally:
        device.disconnect()
        print(f"\nTotal reports: {count}")


if __name__ == "__main__":
    main()
