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
        """Open the HID device and send initialization commands."""
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

        device.set_nonblocking(0)
        self._device = device
        log.info("Connected to U.Discover VID=%s PID=%s", hex(self.vid), hex(self.pid))

        # [CONFIRMED] Initialization sequence captured via USBPcap.
        # The official software sends these two commands on open, then repeats
        # them every ~4 seconds as keep-alive. Without them the device is silent.
        self._send_init()

    # ------------------------------------------------------------------
    # Initialization / keep-alive
    # ------------------------------------------------------------------

    # [CONFIRMED] Commands captured from official U.Discover v1.1.0 via USBPcap.
    # Sent on open and repeated every ~4 s as keep-alive.
    _CMD_Y = b"%Y,01,F107#"   # start/keep-alive command A
    _CMD_Z25 = b"%Z,25,F1E0#"  # start/keep-alive command B  (block 0x25 = control)
    _KEEPALIVE_INTERVAL = 4.0  # seconds between keep-alive pairs

    def _make_report(self, cmd: bytes) -> list[int]:
        """Build a 64-byte HID output report from a text command."""
        payload = list(cmd) + [0] * (63 - len(cmd))
        return [0x00] + payload  # prepend report ID 0x00 (required by Windows HID)

    def _send_init(self) -> None:
        """Send the initialization command pair to start scanning."""
        if self._device is None:
            return
        try:
            self._device.write(self._make_report(self._CMD_Y))
            self._device.write(self._make_report(self._CMD_Z25))
            log.debug("Init commands sent")
        except Exception as exc:
            log.warning("Init write failed: %s", exc)

    def send_keepalive(self) -> None:
        """
        Send the keep-alive command pair.
        Must be called every ~4 seconds or the device will stop streaming.
        Call this from your read loop.
        """
        self._send_init()

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
