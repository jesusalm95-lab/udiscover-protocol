"""
Analyze recorded frames: stats, diffs, payload interpretations, CSV export.

Usage:
    python tools/analyze_frames.py captures/session_001/frames.jsonl
    python tools/analyze_frames.py captures/session_001/frames.jsonl --csv output/session_001.csv
    python tools/analyze_frames.py captures/session_001/frames.jsonl --max 50
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from udiscover.frame import UDiscoverFrame, UDiscoverPacket
from udiscover.analyzer import (
    frame_stats,
    frame_diff,
    interpret_payload,
    summarize_interpretation,
    frames_to_csv_rows,
)


def load_frames(jsonl_path: Path) -> list[UDiscoverFrame]:
    frames = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            frame = _dict_to_frame(data)
            frames.append(frame)
    return frames


def _dict_to_frame(data: dict) -> UDiscoverFrame:
    from udiscover.packet import UDiscoverPacket

    packets = {}
    for label, block in data.get("blocks", {}).items():
        idx = int(label, 16)
        pkt = UDiscoverPacket(
            prefix="%Z",
            block_index=idx,
            block_label=label,
            payload_hex=block["payload_hex"],
            checksum_hex=block["checksum_hex"],
            raw_text=block["raw_text"],
        )
        packets[idx] = pkt

    frame = UDiscoverFrame(
        frame_number=data["frame_number"],
        packets=packets,
        created_at=data.get("created_at", 0.0),
        complete=data.get("complete", False),
    )
    return frame


def print_stats(frames: list[UDiscoverFrame]) -> None:
    print(f"\n{'='*60}")
    print(f"FRAME STATISTICS  ({len(frames)} frames)")
    print(f"{'='*60}")

    for frame in frames:
        s = frame_stats(frame)
        print(
            f"  Frame {s.frame_number:5d}  blocks={s.block_count:2d}  "
            f"payload_bytes={s.total_payload_bytes:5d}"
        )


def print_diffs(frames: list[UDiscoverFrame]) -> None:
    if len(frames) < 2:
        return
    print(f"\n{'='*60}")
    print("FRAME DIFFS (consecutive frames)")
    print(f"{'='*60}")

    for i in range(1, min(len(frames), 11)):  # show first 10 diffs
        d = frame_diff(frames[i - 1], frames[i])
        print(
            f"  Frame {d.frame_a}->{d.frame_b}  "
            f"changed={d.changed_bytes}/{d.total_bytes} bytes "
            f"({d.change_pct:.1f}%)"
        )
    if len(frames) > 11:
        print(f"  ... (showing first 10 diffs only)")


def print_interpretations(frames: list[UDiscoverFrame]) -> None:
    if not frames:
        return
    # Use first complete frame for the interpretation sample
    sample = next((f for f in frames if f.complete), frames[0])
    data = bytes.fromhex(sample.data_payload())

    print(f"\n{'='*60}")
    print(f"PAYLOAD INTERPRETATION SUMMARY  (frame {sample.frame_number})")
    print(f"Data payload: {len(data)} bytes")
    print(f"{'='*60}")
    print(f"  {'Interpretation':<20}  {'Count':>6}  {'Min':>12}  {'Max':>12}  {'Mean':>12}  {'Std':>10}")
    print(f"  {'-'*20}  {'-'*6}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*10}")

    interps = interpret_payload(data)
    for name, values in interps.items():
        s = summarize_interpretation(name, values)
        if s is None:
            continue
        notes = " | ".join(s.notes) if s.notes else ""
        print(
            f"  {s.name:<20}  {s.count:6d}  {s.min_val:12.2f}  {s.max_val:12.2f}  "
            f"{s.mean:12.2f}  {s.std:10.2f}  {notes}"
        )


def write_csv(frames: list[UDiscoverFrame], out_path: Path) -> None:
    rows = frames_to_csv_rows(frames)
    if not rows:
        print("No rows to write.")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV saved: {out_path}  ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze recorded U.Discover frames")
    parser.add_argument("jsonl", metavar="FRAMES_JSONL", help="Path to frames.jsonl")
    parser.add_argument("--csv", metavar="FILE", help="Export to CSV file")
    parser.add_argument("--max", type=int, default=0,
                        help="Limit to first N frames (0 = all)")
    args = parser.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    frames = load_frames(path)
    if args.max:
        frames = frames[: args.max]

    complete = [f for f in frames if f.complete]
    print(f"Loaded {len(frames)} frames  ({len(complete)} complete, {len(frames)-len(complete)} incomplete)")

    print_stats(frames)
    print_diffs(frames)
    print_interpretations(complete)

    if args.csv:
        write_csv(complete, Path(args.csv))


if __name__ == "__main__":
    main()
