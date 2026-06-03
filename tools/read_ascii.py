"""
Read and print ASCII packets from the U.Discover in real time.

Usage:
    python tools/read_ascii.py
    python tools/read_ascii.py --log logs/live_ascii.txt
    python tools/read_ascii.py --packets 500
"""

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.device import UDiscoverDevice
from udiscover.packet import parse_packet, PacketParseError


def main() -> None:
    parser = argparse.ArgumentParser(description="Read ASCII packets from U.Discover")
    parser.add_argument("--log", metavar="FILE", help="Also write packets to this file")
    parser.add_argument("--packets", type=int, default=0,
                        help="Stop after N packets (0 = run forever)")
    args = parser.parse_args()

    log_f = None
    if args.log:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "w", encoding="utf-8")
        print(f"Logging to: {log_path}")

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

        while running:
            text = device.read_text_packet()
            if not text:
                continue

            try:
                pkt = parse_packet(text)
            except PacketParseError as exc:
                print(f"[PARSE ERROR] {exc}")
                pkt = None

            if pkt is not None:
                label = f"[{pkt.block_label}]"
                print(f"{label:5s}  {pkt.raw_text}")
            else:
                print(f"[???]  {text!r}")

            if log_f:
                log_f.write(text + "\n")
                log_f.flush()

            count += 1
            if args.packets and count >= args.packets:
                break

    finally:
        device.disconnect()
        if log_f:
            log_f.close()
        print(f"\nTotal packets received: {count}")


if __name__ == "__main__":
    main()
