# Relacart U.Discover — Python SDK & Protocol Analyzer

> **Status: Research / Reverse Engineering in Progress**
> This project documents and analyzes the HID protocol of the Relacart U.Discover
> RF spectrum analyzer. Sections marked **[CONFIRMED]** are verified with real hardware.
> Sections marked **[HYPOTHESIS]** are working assumptions pending validation.

---

## What we know about the device

| Field          | Value                                    | Status      |
|----------------|------------------------------------------|-------------|
| VID            | `0x0F8B`                                 | CONFIRMED   |
| PID            | `0x0051`                                 | CONFIRMED   |
| Manufacturer   | GigaDevice                               | CONFIRMED   |
| Product        | U.Discover                               | CONFIRMED   |
| HID report size | 64 bytes                                | CONFIRMED   |
| Data encoding  | ASCII text, null-padded                  | CONFIRMED   |
| Protocol       | `%Z,NN,PAYLOAD_HEX,CHECKSUM#`           | CONFIRMED   |
| Frame size     | 25 blocks (0x00–0x24)                    | HYPOTHESIS  |
| Block 0x00     | Frame header / metadata                  | HYPOTHESIS  |
| Blocks 0x01–0x24 | Spectrum sweep data                   | HYPOTHESIS  |
| Checksum algo  | Unknown — under investigation            | OPEN        |
| Payload units  | Unknown — under investigation            | OPEN        |

---

## Project structure

```
udiscover_protocol/
    README.md
    requirements.txt
    src/
        udiscover/
            __init__.py     — package exports + constants
            device.py       — HID connection (UDiscoverDevice)
            packet.py       — packet parser (UDiscoverPacket)
            frame.py        — frame reconstruction (UDiscoverFrame, UDiscoverFrameCollector)
            recorder.py     — frame recording to disk (FrameRecorder)
            analyzer.py     — payload analysis and CSV export
            checksum.py     — checksum algorithm probing
    tools/
        list_devices.py     — enumerate HID devices
        read_ascii.py       — print live ASCII packets
        read_raw.py         — dump raw HID bytes for diagnostics
        record_frames.py    — record complete frames to disk
        analyze_frames.py   — statistics, diffs, payload interpretations
        checksum_probe.py   — brute-force checksum algorithm detection
    captures/               — recorded sessions (git-ignored)
    logs/                   — raw ASCII logs (git-ignored)
    output/                 — CSV exports and reports (git-ignored)
```

---

## Installation

```bash
cd udiscover_protocol
pip install -r requirements.txt
```

> **Windows note:** If `hidapi` installation fails, try:
> `pip install hidapi --pre`

---

## Usage

### 1. Verify the device is detected

```bash
python tools/list_devices.py
```

Expected output:
```
============================================================
  *** Found U.Discover! ***
============================================================
  VID:          0x0f8b  (3979)
  PID:          0x0051  (81)
  Manufacturer: GigaDevice
  Product:      U.Discover
  ...
```

### 2. Read live ASCII packets

```bash
python tools/read_ascii.py
python tools/read_ascii.py --log logs/live_ascii.txt
python tools/read_ascii.py --packets 500
```

### 3. Dump raw bytes (diagnostic)

```bash
python tools/read_raw.py
python tools/read_raw.py --reports 20
```

### 4. Record frames to disk

```bash
python tools/record_frames.py --frames 100 --out captures/session_001
```

Creates:
```
captures/session_001/
    frames.jsonl          — all frames, one JSON per line
    frames_raw.txt        — raw ASCII lines as received
    frame_000001.json     — individual frame (complete only)
    frame_000002.json
    ...
```

### 5. Analyze recorded frames

```bash
python tools/analyze_frames.py captures/session_001/frames.jsonl
python tools/analyze_frames.py captures/session_001/frames.jsonl --csv output/session_001.csv
python tools/analyze_frames.py captures/session_001/frames.jsonl --max 50
```

Reports:
- Frame statistics (block count, payload bytes per frame)
- Byte-level diff between consecutive frames
- Payload interpreted as uint8/int8/uint16/int16/float32 (LE and BE)
- Plausibility hints for RF levels and frequency axis (NOT ground truth)

### 6. Probe checksum algorithm

From a saved log:
```bash
python tools/checksum_probe.py --file logs/live_ascii.txt
```

From live device:
```bash
python tools/checksum_probe.py --live --packets 200
```

---

## Protocol notes

### Packet structure (CONFIRMED)

```
%Z,NN,PAYLOAD_HEX,CCCC#

%Z          — fixed prefix
NN          — block index, 2-digit hex (00..24)
PAYLOAD_HEX — variable-length hex string (even number of chars)
CCCC        — 4-digit hex checksum (algorithm under investigation)
#           — end-of-message sentinel
```

### Frame structure (HYPOTHESIS)

- One complete scan frame = 25 consecutive blocks (0x00..0x24)
- Block 0x00 has a shorter payload (8 bytes) — likely metadata
- Blocks 0x01..0x24 carry the sweep data (~24 bytes each = ~576 bytes/frame)
- A new block 0x00 always starts a new frame

### Payload decoding (OPEN)

No confirmed mapping from payload bytes to frequency/level yet.
Next step: compare HID payload against CSV exported by the official software.

---

## Current protocol status

| Component          | Status                            |
|--------------------|-----------------------------------|
| Device connection  | Working                           |
| ASCII decoding     | Working                           |
| Packet parsing     | Working                           |
| Frame assembly     | Working (hypothesis-based)        |
| Frame recording    | Working                           |
| Checksum           | Unknown — probing framework ready |
| Payload units      | Unknown — analysis tools ready    |
| Spectrum display   | NOT YET — next phase              |

---

## Next steps (NOT implemented yet)

1. Confirm frame structure (0x00..0x24) with longer captures
2. Identify checksum algorithm using `checksum_probe.py`
3. Export CSV from official Relacart software during a capture session
4. Compare HID payload bytes against official CSV to infer payload scale
5. Map (byte_offset, value) → (frequency_MHz, level_dBm)
6. Build real-time spectrum display (pyqtgraph)
7. Load channel tables for wireless equipment
8. Detect occupied frequencies and calculate IM3/IM5 intermodulation
9. Suggest optimal frequency combinations

---

## Contributing / workflow

All captures and logs are gitignored. Commit only source code and documentation.
Each analysis session should be saved with a descriptive name:

```bash
python tools/record_frames.py --frames 200 --out captures/2026-06-02_initial
```
