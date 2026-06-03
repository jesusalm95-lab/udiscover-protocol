"""
List all HID devices and highlight the U.Discover.

Usage:
    python tools/list_devices.py
    python tools/list_devices.py --all      # show every HID device
"""

import argparse
import sys

TARGET_VID = 0x0F8B
TARGET_PID = 0x0051


def main() -> None:
    parser = argparse.ArgumentParser(description="List HID devices")
    parser.add_argument("--all", action="store_true", help="Show all HID devices, not just U.Discover")
    args = parser.parse_args()

    try:
        import hid
    except ImportError:
        print("ERROR: hidapi not installed. Run: pip install hidapi", file=sys.stderr)
        sys.exit(1)

    devices = hid.enumerate()
    if not devices:
        print("No HID devices found.")
        sys.exit(0)

    found_target = False

    for dev in devices:
        is_target = dev["vendor_id"] == TARGET_VID and dev["product_id"] == TARGET_PID

        if is_target:
            found_target = True
            print("=" * 60)
            print("  *** Found U.Discover! ***")
            print("=" * 60)
            _print_device(dev)
            print()
        elif args.all:
            _print_device(dev)
            print()

    if not found_target:
        print(
            f"U.Discover NOT detected (VID={TARGET_VID:#06x} PID={TARGET_PID:#06x}).\n"
            "Make sure the device is plugged in and no other software has it open."
        )

    if args.all:
        print(f"Total HID devices found: {len(devices)}")


def _print_device(dev: dict) -> None:
    vid = dev["vendor_id"]
    pid = dev["product_id"]
    print(f"  VID:          {vid:#06x}  ({vid})")
    print(f"  PID:          {pid:#06x}  ({pid})")
    print(f"  Manufacturer: {dev.get('manufacturer_string', '')}")
    print(f"  Product:      {dev.get('product_string', '')}")
    print(f"  Serial:       {dev.get('serial_number', '')}")
    up = dev.get("usage_page", 0)
    u  = dev.get("usage", 0)
    print(f"  Usage Page:   {up:#04x}  ({up})")
    print(f"  Usage:        {u:#04x}  ({u})")
    print(f"  Interface:    {dev.get('interface_number', '')}")
    print(f"  Path:         {dev.get('path', b'').decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
