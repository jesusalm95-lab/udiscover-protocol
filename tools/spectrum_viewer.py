"""
Real-time RF spectrum viewer for Relacart U.Discover.

Reads live HID frames and plots frequency (MHz) vs level (dBm)
at the device's native refresh rate (~10-15 frames/sec).

Usage:
    python tools/spectrum_viewer.py
    python tools/spectrum_viewer.py --peak-hold
    python tools/spectrum_viewer.py --avg 5

Requires: pyqtgraph PyQt6  (pip install pyqtgraph PyQt6)
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from udiscover.device import UDiscoverDevice
from udiscover.frame import UDiscoverFrameCollector
from udiscover.packet import parse_packet, PacketParseError

# ── Calibration (confirmed from hardware + CSV comparison) ──────────────────
FREQ_REG_START = 31275
FREQ_REG_END   = 43674
START_MHZ      = 500.0
END_MHZ        = 699.0
LEVEL_MIN_DBM  = -102.0
LEVEL_MAX_DBM  = -62.0

# ── Colours ─────────────────────────────────────────────────────────────────
COLOR_LIVE      = (0, 220, 100)     # green
COLOR_PEAK      = (255, 80, 80)     # red
COLOR_AVG       = (80, 160, 255)    # blue
COLOR_GRID      = (60, 60, 60)
COLOR_BG        = (18, 18, 18)


def freq_reg_to_mhz(reg: int) -> float:
    span = FREQ_REG_END - FREQ_REG_START
    return START_MHZ + (reg - FREQ_REG_START) / span * (END_MHZ - START_MHZ)


def level_byte_to_dbm(b: int) -> float:
    return LEVEL_MIN_DBM + (b / 255.0) * (LEVEL_MAX_DBM - LEVEL_MIN_DBM)


def decode_frame(frame) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (freqs_mhz, levels_dbm) arrays from a complete frame."""
    freqs, levels = [], []
    for idx in range(1, 37):
        block = frame.packets.get(idx)
        if block is None:
            continue
        raw = block.payload_hex
        if len(raw) < 49:
            raw = raw.ljust(49, "0")
        for i in range(0, 49, 7):
            g = raw[i:i + 7]
            if len(g) < 7:
                break
            freq_reg    = int(g[0:4], 16)
            level_byte  = (int(g[4], 16) << 4) | int(g[6], 16)
            freqs.append(freq_reg_to_mhz(freq_reg))
            levels.append(level_byte_to_dbm(level_byte))
    if not freqs:
        return None
    return np.array(freqs), np.array(levels)


# ── Device reader thread ─────────────────────────────────────────────────────

class DeviceReader(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.latest: tuple[np.ndarray, np.ndarray] | None = None
        self.frame_count = 0
        self.fps = 0.0
        self.error: str | None = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()

    def run(self):
        device    = UDiscoverDevice()
        collector = UDiscoverFrameCollector()
        try:
            device.connect()
        except RuntimeError as e:
            self.error = str(e)
            return

        fps_frames, fps_t0 = 0, time.time()

        while not self._stop_evt.is_set():
            text = device.read_text_packet(timeout_ms=100)
            if not text:
                continue
            try:
                pkt = parse_packet(text)
            except PacketParseError:
                continue
            if pkt is None:
                continue

            sealed = collector.add_packet(pkt)
            if sealed and sealed.complete:
                result = decode_frame(sealed)
                if result:
                    with self._lock:
                        self.latest = result
                        self.frame_count += 1
                    fps_frames += 1
                    if fps_frames >= 10:
                        dt = time.time() - fps_t0
                        self.fps = fps_frames / dt if dt > 0 else 0
                        fps_frames, fps_t0 = 0, time.time()

        last = collector.flush()
        device.disconnect()

    def get_latest(self) -> tuple[np.ndarray, np.ndarray] | None:
        with self._lock:
            return self.latest

    def stop(self):
        self._stop_evt.set()


# ── Main window ──────────────────────────────────────────────────────────────

class SpectrumViewer(QMainWindow):
    def __init__(self, peak_hold: bool = False, avg_count: int = 1):
        super().__init__()
        self.peak_hold = peak_hold
        self.avg_count = max(1, avg_count)

        self.setWindowTitle("U.Discover — RF Spectrum Analyzer")
        self.resize(1280, 600)

        # ── Layout ──────────────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.status_label = QLabel("Connecting to U.Discover...")
        self.status_label.setStyleSheet("color: #aaa; font-size: 11px; padding: 2px 6px;")
        layout.addWidget(self.status_label)

        # ── Plot ─────────────────────────────────────────────────────────────
        pg.setConfigOptions(antialias=True, background=COLOR_BG, foreground="#cccccc")
        self.plot_widget = pg.PlotWidget()
        layout.addWidget(self.plot_widget)

        pw = self.plot_widget
        pw.setLabel("left",   "Level",     units="dBm")
        pw.setLabel("bottom", "Frequency", units="MHz")
        pw.setXRange(START_MHZ, END_MHZ, padding=0.01)
        pw.setYRange(LEVEL_MIN_DBM - 5, LEVEL_MAX_DBM + 5, padding=0)
        pw.showGrid(x=True, y=True, alpha=0.3)
        pw.addLegend(offset=(10, 10))

        # noise floor reference line
        noise_line = pg.InfiniteLine(
            pos=LEVEL_MIN_DBM, angle=0,
            pen=pg.mkPen(color=(100, 100, 100), width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
            label="noise floor",
            labelOpts={"color": "#666", "position": 0.02},
        )
        pw.addItem(noise_line)

        # ── Curves ───────────────────────────────────────────────────────────
        self.curve_live = pw.plot(
            [], [], name="Live",
            pen=pg.mkPen(color=COLOR_LIVE, width=1.5),
        )
        self.curve_peak = pw.plot(
            [], [], name="Peak hold",
            pen=pg.mkPen(color=COLOR_PEAK, width=1, style=pg.QtCore.Qt.PenStyle.DotLine),
        ) if peak_hold else None

        self.curve_avg = pw.plot(
            [], [], name=f"Avg ({avg_count})",
            pen=pg.mkPen(color=COLOR_AVG, width=1.5),
        ) if avg_count > 1 else None

        # ── State ─────────────────────────────────────────────────────────────
        self._peak_freqs: np.ndarray | None = None
        self._peak_levels: np.ndarray | None = None
        self._avg_buf: deque[np.ndarray] = deque(maxlen=avg_count)

        # ── Device reader ─────────────────────────────────────────────────────
        self.reader = DeviceReader()
        self.reader.start()

        # ── Refresh timer ─────────────────────────────────────────────────────
        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh)
        self.timer.start(50)   # 20 Hz UI refresh

    # ─────────────────────────────────────────────────────────────────────────

    def _refresh(self):
        if self.reader.error:
            self.status_label.setText(f"ERROR: {self.reader.error}")
            self.timer.stop()
            return

        data = self.reader.get_latest()
        if data is None:
            return

        freqs, levels = data

        # ── Live curve ────────────────────────────────────────────────────────
        self.curve_live.setData(freqs, levels)

        # ── Peak hold ─────────────────────────────────────────────────────────
        if self.curve_peak is not None:
            if self._peak_levels is None or len(self._peak_levels) != len(levels):
                self._peak_freqs  = freqs.copy()
                self._peak_levels = levels.copy()
            else:
                self._peak_levels = np.maximum(self._peak_levels, levels)
            self.curve_peak.setData(self._peak_freqs, self._peak_levels)

        # ── Running average ───────────────────────────────────────────────────
        if self.curve_avg is not None:
            self._avg_buf.append(levels)
            avg_levels = np.mean(np.stack(self._avg_buf), axis=0)
            self.curve_avg.setData(freqs, avg_levels)

        # ── Status bar ────────────────────────────────────────────────────────
        peak_idx   = int(np.argmax(levels))
        peak_freq  = freqs[peak_idx]
        peak_level = levels[peak_idx]
        self.status_label.setText(
            f"Frames: {self.reader.frame_count}  |  "
            f"FPS: {self.reader.fps:.1f}  |  "
            f"Peak: {peak_level:.1f} dBm @ {peak_freq:.3f} MHz  |  "
            f"Samples/frame: {len(freqs)}"
        )

    def closeEvent(self, event):
        self.timer.stop()
        self.reader.stop()
        self.reader.join(timeout=2)
        super().closeEvent(event)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="U.Discover real-time spectrum viewer")
    parser.add_argument("--peak-hold", action="store_true",
                        help="Show peak-hold trace in red")
    parser.add_argument("--avg", type=int, default=1, metavar="N",
                        help="Show N-frame running average in blue (default: 1 = off)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = SpectrumViewer(peak_hold=args.peak_hold, avg_count=args.avg)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
