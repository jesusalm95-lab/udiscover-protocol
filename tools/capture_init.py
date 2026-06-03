"""
Capture the U.Discover HID initialization sequence using Windows ETW USB tracing.
No USBPcap needed — uses Windows built-in USB monitoring.

Steps performed automatically:
  1. Start Windows USB ETW trace
  2. Wait for you to open U.Discover software
  3. Stop trace
  4. Convert ETL → pcapng (etl2pcapng)
  5. Parse pcapng with tshark to find HID output reports

Usage (run as Administrator):
    python tools/capture_init.py

Requirements:
    - etl2pcapng  (winget install Microsoft.etl2pcapng)
    - tshark      (already installed at C:\\Program Files\\Wireshark\\tshark.exe)
    - Run as Administrator (ETW USB tracing requires it)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
ETL_FILE = Path(tempfile.gettempdir()) / "udiscover_usbtrace.etl"
PCAP_FILE = Path(tempfile.gettempdir()) / "udiscover_usbtrace.pcapng"

TARGET_VID = "0F8B"
TARGET_PID = "0051"


def check_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def start_trace() -> None:
    print("Starting Windows USB ETW trace...")
    # Stop any existing trace first
    run(["logman", "stop", "udiscover_usbtrace", "-ets"])
    result = run([
        "logman", "start", "udiscover_usbtrace",
        "-p", "Microsoft-Windows-USB-USBHUB3", "0xFFFF", "0xFF",
        "-p", "Microsoft-Windows-USB-UCX", "0xFFFF", "0xFF",
        "-o", str(ETL_FILE),
        "-ets"
    ])
    if result.returncode != 0:
        # Try with fewer providers
        result = run([
            "logman", "start", "udiscover_usbtrace",
            "-p", "{36DA592D-E43A-4E28-AF6F-4BC57C5A11E8}", "0xFFFF", "0xFF",
            "-o", str(ETL_FILE),
            "-ets"
        ])
    if result.returncode != 0:
        print(f"ERROR starting trace: {result.stderr}")
        print("Make sure you are running as Administrator.")
        sys.exit(1)
    print("Trace started.")


def stop_trace() -> None:
    print("Stopping trace...")
    run(["logman", "stop", "udiscover_usbtrace", "-ets"])


def convert_etl() -> bool:
    print(f"Converting {ETL_FILE} → {PCAP_FILE} ...")
    result = run(["etl2pcapng", str(ETL_FILE), str(PCAP_FILE)])
    if result.returncode != 0 or not PCAP_FILE.exists():
        print(f"Conversion failed: {result.stderr}")
        print("Try running: etl2pcapng from a new terminal (PATH may need refresh).")
        return False
    print(f"Converted: {PCAP_FILE} ({PCAP_FILE.stat().st_size:,} bytes)")
    return True


def extract_hid_writes() -> list[str]:
    """Use tshark to extract HID output reports sent to our device."""
    if not Path(TSHARK).exists():
        print(f"tshark not found at {TSHARK}")
        return []

    print(f"\nParsing USB traffic for VID={TARGET_VID} PID={TARGET_PID}...")

    # Read all USB interrupt OUT packets
    result = run([
        TSHARK, "-r", str(PCAP_FILE),
        "-Y", "usb.transfer_type == 0x01",  # interrupt transfers
        "-T", "fields",
        "-e", "frame.number",
        "-e", "usb.endpoint_address",
        "-e", "usb.endpoint_address.direction",
        "-e", "usb.data_len",
        "-e", "usb.capdata",
        "-e", "usb.device_address",
    ])

    if result.returncode != 0:
        # Try without USB-specific fields
        result = run([
            TSHARK, "-r", str(PCAP_FILE),
            "-T", "fields",
            "-e", "frame.number",
            "-e", "usb.capdata",
        ])

    lines = [l for l in result.stdout.splitlines() if l.strip()]
    print(f"Found {len(lines)} USB packets")
    return lines


def main() -> None:
    if not check_admin():
        print("WARNING: Not running as Administrator.")
        print("ETW USB tracing requires Administrator privileges.")
        print("Right-click your terminal and choose 'Run as Administrator', then retry.")
        print()

    print("=" * 60)
    print("U.Discover HID Init Sequence Capture")
    print("=" * 60)
    print()
    print("Instructions:")
    print("  1. Make sure U.Discover software is CLOSED")
    print("  2. Press Enter to start USB monitoring")
    print("  3. Open U.Discover software")
    print("  4. Wait for it to show the spectrum (~3 seconds)")
    print("  5. Press Enter again to stop and analyze")
    print()
    input("Press Enter to start monitoring...")

    start_trace()
    print()
    print(">>> Open U.Discover software NOW and wait for spectrum to appear <<<")
    print()
    input("Press Enter when spectrum is visible to stop capture...")

    stop_trace()

    if not ETL_FILE.exists():
        print(f"ERROR: ETL file not found: {ETL_FILE}")
        sys.exit(1)

    if not convert_etl():
        print()
        print("Fallback: manual analysis steps:")
        print(f"  etl2pcapng {ETL_FILE} output.pcapng")
        print(f"  tshark -r output.pcapng -Y 'usb.transfer_type == 0x01' -x")
        sys.exit(1)

    packets = extract_hid_writes()

    if not packets:
        print()
        print("No USB interrupt packets found in capture.")
        print(f"Try opening {PCAP_FILE} manually in Wireshark.")
        print("Filter: usb.transfer_type == 0x01")
        sys.exit(1)

    print("\nUSB interrupt packets captured:")
    print("-" * 60)
    for i, pkt in enumerate(packets[:40], 1):
        print(f"  {i:3d}: {pkt}")

    print()
    print(f"Full capture saved to: {PCAP_FILE}")
    print(f"Open in Wireshark and filter: usb.transfer_type == 0x01 && usb.endpoint_address.direction == 0")
    print("The OUT packets (direction=0) sent shortly after opening are the init sequence.")

    # Clean up
    try:
        ETL_FILE.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    main()
