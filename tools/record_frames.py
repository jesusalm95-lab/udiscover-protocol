"""
Record complete frames from the U.Discover to disk.

Usage:
    python tools/record_frames.py --frames 100 --out captures/session_001
    python tools/record_frames.py --frames 50 --out captures/test_001 --no-individual
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.recorder import FrameRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="Record U.Discover frames to disk")
    parser.add_argument("--frames", type=int, default=100,
                        help="Number of complete frames to capture (default: 100)")
    parser.add_argument("--out", metavar="DIR", default="captures/session_001",
                        help="Output directory (default: captures/session_001)")
    parser.add_argument("--no-individual", action="store_true",
                        help="Skip saving per-frame JSON files (faster for large sessions)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    out_dir = Path(args.out)

    recorder = FrameRecorder(
        out_dir=out_dir,
        save_individual=not args.no_individual,
    )

    try:
        frames = recorder.run(n_frames=args.frames)
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)

    print(f"\nSaved {len(frames)} complete frames to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
