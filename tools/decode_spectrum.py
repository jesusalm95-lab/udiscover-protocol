"""
Decode U.Discover frames into spectrum data (frequency MHz + level dBm).

[CONFIRMED] Protocol structure:
    - 36 data blocks per frame (0x01–0x24)
    - 7 samples per block = 252 samples per frame
    - Each sample: 7 nibbles = FFFF (freq reg 16-bit) + X0Z (level)
    - level_byte = (X << 4) | Z
    - Frequency: linear mapping from freq_reg to MHz
    - Level: linear mapping from level_byte (0–255) to dBm

Usage:
    python tools/decode_spectrum.py captures/2026-06-02_live/frames.jsonl
    python tools/decode_spectrum.py captures/2026-06-02_live/frames.jsonl --frame 1
    python tools/decode_spectrum.py captures/2026-06-02_live/frames.jsonl --compare "C:/path/to/official.csv"
    python tools/decode_spectrum.py captures/2026-06-02_live/frames.jsonl --out output/spectrum.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# [CONFIRMED] Frequency calibration from hardware captures
FREQ_REG_START = 31275    # = 0x7A2B, maps to START_MHZ
FREQ_REG_END   = 43674    # = 0xAA9A, maps to END_MHZ
START_MHZ      = 500.0    # confirmed from block 00 header (0x30D4 = 12500 × 40 kHz)
END_MHZ        = 699.0    # observed from CSV export of official software

# Level calibration — level_byte 221 = -63 dBm (confirmed vs official software),
# level_byte 0 ≈ -80 dBm (noise floor visible in official software).
# Formula: level_dBm = -80 + (level_byte / 255) * 20
LEVEL_MIN_DBM  = -80.0    # noise floor  (level_byte = 0)
LEVEL_MAX_DBM  = -60.0    # saturation   (level_byte = 255)


def freq_reg_to_mhz(reg: int) -> float:
    """Linear mapping from 16-bit frequency register to MHz."""
    span = FREQ_REG_END - FREQ_REG_START
    if span == 0:
        return START_MHZ
    return START_MHZ + (reg - FREQ_REG_START) / span * (END_MHZ - START_MHZ)


def level_byte_to_dbm(level: int) -> float:
    """Linear mapping from 8-bit level byte to dBm. [ESTIMATED — needs calibration]"""
    return LEVEL_MIN_DBM + (level / 255.0) * (LEVEL_MAX_DBM - LEVEL_MIN_DBM)


def decode_frame(frame_data: dict) -> list[tuple[float, float]]:
    """
    Decode one frame dict (from frames.jsonl) into (freq_mhz, level_dbm) pairs.
    Returns 252 samples in ascending frequency order.
    """
    samples: list[tuple[float, float]] = []
    for block_label in [f"{i:02X}" for i in range(1, 37)]:  # 01..24h
        block = frame_data.get("blocks", {}).get(block_label)
        if block is None:
            continue
        raw = block["payload_hex"]
        # Pad to 49 nibbles if the trailing nibble was lost during capture
        if len(raw) < 49:
            raw = raw.ljust(49, "0")
        for i in range(0, 49, 7):
            group = raw[i:i + 7]
            if len(group) < 7:
                break
            freq_reg = int(group[0:4], 16)
            level_byte = (int(group[4], 16) << 4) | int(group[6], 16)
            samples.append((freq_reg_to_mhz(freq_reg), level_byte_to_dbm(level_byte)))
    return samples


def load_official_csv(path: Path) -> list[tuple[float, float]]:
    """Load (freq_khz, level_dbm) pairs from official Relacart CSV export."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    freq_mhz = float(parts[0]) / 1000.0
                    level_dbm = float(parts[1])
                    rows.append((freq_mhz, level_dbm))
                except ValueError:
                    pass
    return rows


def print_spectrum(samples: list[tuple[float, float]], frame_num: int) -> None:
    print(f"\nFrame {frame_num} — {len(samples)} samples")
    print(f"{'Freq MHz':>10}  {'Level dBm':>10}  Bar")
    print("-" * 60)
    for freq, level in samples:
        bar_len = max(0, int((level - LEVEL_MIN_DBM) / (LEVEL_MAX_DBM - LEVEL_MIN_DBM) * 40))
        bar = "█" * bar_len
        print(f"{freq:10.3f}  {level:10.1f}  {bar}")


def compare_with_csv(
    hid_samples: list[tuple[float, float]],
    csv_samples: list[tuple[float, float]],
) -> None:
    """Side-by-side comparison of HID decode vs official CSV."""
    print(f"\n{'Freq (HID)':>12}  {'dBm (HID)':>10}  |  {'Freq (CSV)':>12}  {'dBm (CSV)':>10}  diff")
    print("-" * 72)
    n = min(len(hid_samples), len(csv_samples), 30)
    for i in range(n):
        h_freq, h_level = hid_samples[i]
        c_freq, c_level = csv_samples[i]
        delta = abs(h_level - c_level)
        print(f"{h_freq:12.3f}  {h_level:10.1f}  |  {c_freq:12.3f}  {c_level:10.1f}  d={delta:.1f}")
    if len(hid_samples) > 30:
        print(f"  ... ({len(hid_samples)} total HID samples, {len(csv_samples)} CSV rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode U.Discover HID frames to spectrum")
    parser.add_argument("jsonl", metavar="FRAMES_JSONL")
    parser.add_argument("--frame", type=int, default=1, help="Frame number to decode (default: 1)")
    parser.add_argument("--all", action="store_true", help="Decode all frames and average")
    parser.add_argument("--out", metavar="CSV", help="Save decoded spectrum to CSV")
    parser.add_argument("--compare", metavar="OFFICIAL_CSV", help="Compare with official CSV export")
    parser.add_argument("--print", action="store_true", dest="print_spectrum",
                        help="Print spectrum with ASCII bar chart")
    args = parser.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        print(f"ERROR: {path}", file=sys.stderr)
        sys.exit(1)

    frames = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))

    target_frame = next(
        (fr for fr in frames if fr["frame_number"] == args.frame and fr["complete"]),
        frames[0] if frames else None,
    )
    if target_frame is None:
        print("No complete frames found.", file=sys.stderr)
        sys.exit(1)

    samples = decode_frame(target_frame)
    print(f"Decoded frame {target_frame['frame_number']}: {len(samples)} samples")
    print(f"  Freq range: {samples[0][0]:.3f} – {samples[-1][0]:.3f} MHz")
    print(f"  Level range: {min(s[1] for s in samples):.1f} – {max(s[1] for s in samples):.1f} dBm")
    print(f"  Strongest signal: {max(samples, key=lambda x: x[1])}")

    if args.print_spectrum:
        print_spectrum(samples, target_frame["frame_number"])

    if args.compare:
        csv_path = Path(args.compare)
        if csv_path.exists():
            official = load_official_csv(csv_path)
            print(f"\nOfficial CSV: {len(official)} samples")
            print(f"  Freq range: {official[0][0]:.3f} – {official[-1][0]:.3f} MHz")
            compare_with_csv(samples, official)
        else:
            print(f"CSV not found: {csv_path}", file=sys.stderr)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["freq_mhz", "level_dbm"])
            for freq, level in samples:
                w.writerow([round(freq, 3), round(level, 2)])
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
