"""
Probe checksum algorithms against captured packets.

Can be run against live data or a saved raw log file.

Usage:
    python tools/checksum_probe.py --file logs/live_ascii.txt
    python tools/checksum_probe.py --live --packets 200
"""

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.packet import parse_packet, PacketParseError, UDiscoverPacket
from udiscover.checksum import probe_packets, CANDIDATES


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe checksum algorithms")
    parser.add_argument("--file", metavar="FILE",
                        help="Read packets from a raw ASCII log file")
    parser.add_argument("--live", action="store_true",
                        help="Read packets from the connected device")
    parser.add_argument("--packets", type=int, default=200,
                        help="Number of packets to collect (live mode, default: 200)")
    args = parser.parse_args()

    if not args.file and not args.live:
        parser.error("Specify --file or --live")

    packets: list[UDiscoverPacket] = []

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                pkt = parse_packet(line)
            except PacketParseError:
                continue
            if pkt is not None:
                packets.append(pkt)
        print(f"Loaded {len(packets)} packets from {path}")

    elif args.live:
        from udiscover.device import UDiscoverDevice
        device = UDiscoverDevice()

        running = True

        def _stop(*_):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _stop)

        try:
            device.connect()
            print(f"Collecting {args.packets} packets from device... (Ctrl+C to stop early)")
            while running and len(packets) < args.packets:
                text = device.read_text_packet()
                if not text:
                    continue
                try:
                    pkt = parse_packet(text)
                except PacketParseError:
                    continue
                if pkt is not None:
                    packets.append(pkt)
                    print(f"\r  {len(packets)}/{args.packets}", end="", flush=True)
        finally:
            device.disconnect()
            print()

    if not packets:
        print("No valid packets found — cannot probe.")
        sys.exit(1)

    print(f"\nProbing {len(CANDIDATES)} checksum candidates against {len(packets)} packets...")
    results = probe_packets(packets)

    print(f"\n{'Candidate':<40s}  {'Match':>8}  {'Rate':>6}")
    print("-" * 60)
    for r in results:
        marker = "  <<< EXACT MATCH" if r.matches == r.total else ""
        print(f"  {r}{marker}")

    best = results[0]
    if best.matches == best.total:
        print(f"\n[SUCCESS] Perfect match found: {best.candidate_name}")
    elif best.matches > 0:
        print(
            f"\n[PARTIAL] Best candidate: {best.candidate_name} "
            f"({best.matches}/{best.total} packets)"
        )
    else:
        print("\n[NONE] No candidate matched. The algorithm may not be in the list.")


if __name__ == "__main__":
    main()
