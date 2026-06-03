"""
UDiscoverDevice — low-level HID connection to Relacart U.Discover.

[CONFIRMED] The device streams ASCII text over HID without requiring
initialization commands from the host side.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

VENDOR_ID = 0x0F8B
PRODUCT_ID = 0x0051
DEFAULT_READ_SIZE = 64


class UDiscoverDevice:
    """Wraps a hidapi handle to the U.Discover spectrum analyzer."""

    def __init__(
        self,
        vid: int = VENDOR_ID,
        pid: int = PRODUCT_ID,
        read_size: int = DEFAULT_READ_SIZE,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.read_size = read_size
        self._device = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the HID device. Raises RuntimeError if not found."""
        try:
            import hid  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "hidapi not installed — run: pip install hidapi"
            ) from exc

        device = hid.device()
        try:
            device.open(self.vid, self.pid)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot open U.Discover (VID={self.vid:#06x} PID={self.pid:#06x}). "
                "Is the device connected and not claimed by another process?"
            ) from exc

        device.set_nonblocking(0)  # blocking reads
        self._device = device
        log.info(
            "Connected to U.Discover VID=%s PID=%s",
            hex(self.vid),
            hex(self.pid),
        )

    def disconnect(self) -> None:
        """Close the HID device if open."""
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
            log.info("Disconnected from U.Discover")

    def is_connected(self) -> bool:
        return self._device is not None

    def __enter__(self) -> "UDiscoverDevice":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_raw(self, timeout_ms: int | None = None) -> list[int]:
        """
        Read one HID report as a list of raw bytes.

        [CONFIRMED] Reports are 64 bytes. The first byte may be a HID
        report-ID (0x00 on this device) — kept here for transparency.

        Returns an empty list on timeout or if no data is available.
        """
        if self._device is None:
            raise RuntimeError("Device not connected — call connect() first.")

        if timeout_ms is not None:
            data = self._device.read(self.read_size, timeout_ms)
        else:
            data = self._device.read(self.read_size)

        return list(data) if data else []

    def read_text_packet(self, timeout_ms: int | None = None) -> str:
        """
        Read one HID report and decode it as ASCII text.

        [CONFIRMED] The U.Discover sends printable ASCII terminated
        with '#' and padded with null bytes to fill the 64-byte report.

        Returns an empty string if no data or timeout.
        """
        raw = self.read_raw(timeout_ms)
        if not raw:
            return ""

        text = bytes(raw).decode("ascii", errors="ignore")
        text = text.replace("\x00", "").strip()
        return text

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        status = "connected" if self.is_connected() else "disconnected"
        return f"UDiscoverDevice(vid={self.vid:#06x}, pid={self.pid:#06x}, {status})"
