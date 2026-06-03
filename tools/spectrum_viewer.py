"""
Real-time RF spectrum viewer for Relacart U.Discover.

Usage:
    python tools/spectrum_viewer.py
    python tools/spectrum_viewer.py --peak-hold
    python tools/spectrum_viewer.py --avg 5
    python tools/spectrum_viewer.py --peak-hold --avg 5

Requires: pyqtgraph PyQt6 numpy  (pip install pyqtgraph PyQt6 numpy)
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
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QVBoxLayout, QWidget,
)

from udiscover.device import UDiscoverDevice
from udiscover.frame import UDiscoverFrameCollector
from udiscover.packet import parse_packet, PacketParseError

# ── Calibration ───────────────────────────────────────────────────────────────
FREQ_REG_START = 31275
FREQ_REG_END   = 43674
START_MHZ      = 500.0
END_MHZ        = 699.0

# Level calibration — derived from simultaneous HID+official-software comparison:
#   level_byte = 221  →  -63 dBm  (confirmed: 597 MHz peak matches official CSV)
#   level_byte = 0    →  -80 dBm  (noise floor observed in official software)
# Formula: level_dBm = -80 + (level_byte / 255) * 20
LEVEL_BYTE_SCALE = 255.0
LEVEL_MIN_DBM    = -80.0   # noise floor
LEVEL_MAX_DBM    = -60.0   # saturation / strongest expected signal

# ── Palette ───────────────────────────────────────────────────────────────────
C_LIVE   = (0,   210,  90)
C_FILL   = (0,   210,  90,  50)   # translucent green fill
C_PEAK   = (255,  70,  70)
C_AVG    = ( 80, 160, 255)
C_CURSOR = (255, 220,   0)
C_BG     = ( 15,  15,  15)
C_TEXT   = "#cccccc"


def freq_reg_to_mhz(reg: int) -> float:
    span = FREQ_REG_END - FREQ_REG_START
    return START_MHZ + (reg - FREQ_REG_START) / span * (END_MHZ - START_MHZ)


def level_byte_to_dbm(b: int) -> float:
    return LEVEL_MIN_DBM + (b / 255.0) * (LEVEL_MAX_DBM - LEVEL_MIN_DBM)


def decode_frame(frame) -> tuple[np.ndarray, np.ndarray] | None:
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
            freq_reg   = int(g[0:4], 16)
            level_byte = (int(g[4], 16) << 4) | int(g[6], 16)
            freqs.append(freq_reg_to_mhz(freq_reg))
            levels.append(level_byte_to_dbm(level_byte))
    if not freqs:
        return None
    return np.array(freqs, dtype=np.float32), np.array(levels, dtype=np.float32)


# ── Device reader thread ──────────────────────────────────────────────────────

class DeviceReader(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.latest:      tuple[np.ndarray, np.ndarray] | None = None
        self.frame_count: int   = 0
        self.fps:         float = 0.0
        self.error:       str | None = None
        self._stop  = threading.Event()
        self._lock  = threading.Lock()
        self._times: deque[float] = deque(maxlen=20)   # rolling FPS window

    def run(self):
        device    = UDiscoverDevice()
        collector = UDiscoverFrameCollector()
        try:
            device.connect()
        except RuntimeError as e:
            self.error = str(e)
            return

        while not self._stop.is_set():
            text = device.read_text_packet(timeout_ms=200)
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
                    now = time.monotonic()
                    with self._lock:
                        self.latest = result
                        self.frame_count += 1
                        self._times.append(now)
                        if len(self._times) >= 2:
                            dt = self._times[-1] - self._times[0]
                            self.fps = (len(self._times) - 1) / dt if dt > 0 else 0.0

        collector.flush()
        device.disconnect()

    def get(self) -> tuple[np.ndarray, np.ndarray] | None:
        with self._lock:
            return self.latest

    def stop(self):
        self._stop.set()


# ── Main window ───────────────────────────────────────────────────────────────

class SpectrumViewer(QMainWindow):
    def __init__(self, peak_hold: bool, avg_count: int):
        super().__init__()
        self.peak_hold = peak_hold
        self.avg_count = max(1, avg_count)

        self.setWindowTitle("U.Discover — RF Spectrum Analyzer")
        self.resize(1300, 640)
        self.setStyleSheet(f"background: rgb{C_BG};")

        # ── Root layout ───────────────────────────────────────────────────────
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(6, 4, 6, 4)
        vbox.setSpacing(4)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QHBoxLayout()
        vbox.addLayout(top)

        mono = QFont("Consolas", 10)

        self.lbl_status = QLabel("Connecting…")
        self.lbl_status.setFont(mono)
        self.lbl_status.setStyleSheet(f"color: {C_TEXT};")
        top.addWidget(self.lbl_status)

        top.addStretch()

        self.btn_reset_peak = QPushButton("Reset peak")
        self.btn_reset_peak.setFixedHeight(24)
        self.btn_reset_peak.setStyleSheet(
            "QPushButton { color:#ccc; background:#2a2a2a; border:1px solid #444;"
            " border-radius:3px; padding:0 8px; }"
            "QPushButton:hover { background:#3a3a3a; }"
        )
        self.btn_reset_peak.clicked.connect(self._reset_peak)
        self.btn_reset_peak.setVisible(peak_hold)
        top.addWidget(self.btn_reset_peak)

        # ── Plot ──────────────────────────────────────────────────────────────
        pg.setConfigOptions(antialias=True, background=C_BG, foreground=C_TEXT)
        self.pw = pg.PlotWidget()
        vbox.addWidget(self.pw)

        self.pw.setLabel("left",   "Level",     units="dBm", color=C_TEXT)
        self.pw.setLabel("bottom", "Frequency", units="MHz", color=C_TEXT)
        self.pw.setXRange(START_MHZ, END_MHZ, padding=0.02)
        self.pw.setYRange(LEVEL_MIN_DBM - 5, LEVEL_MAX_DBM + 5, padding=0)
        self.pw.showGrid(x=True, y=True, alpha=0.25)
        self.pw.getAxis("left").setTickSpacing(major=10, minor=5)
        self.pw.setMouseEnabled(x=True, y=True)    # allow zoom/pan

        legend = self.pw.addLegend(offset=(10, 10), labelTextColor=C_TEXT)
        legend.setColumnCount(3)

        # noise floor
        self.pw.addItem(pg.InfiniteLine(
            pos=LEVEL_MIN_DBM, angle=0,
            pen=pg.mkPen(color=(90, 90, 90), width=1,
                         style=Qt.PenStyle.DashLine),
        ))

        # ── Curves ────────────────────────────────────────────────────────────
        # filled live trace
        self.fill = pg.FillBetweenItem(
            pg.PlotDataItem([START_MHZ, END_MHZ], [LEVEL_MIN_DBM, LEVEL_MIN_DBM]),
            pg.PlotDataItem([START_MHZ, END_MHZ], [LEVEL_MIN_DBM, LEVEL_MIN_DBM]),
            brush=pg.mkBrush(color=C_FILL),
        )
        self.pw.addItem(self.fill)

        self._ref_line = pg.PlotDataItem(
            [START_MHZ, END_MHZ], [LEVEL_MIN_DBM, LEVEL_MIN_DBM],
        )
        self.pw.addItem(self._ref_line)

        self.curve_live = self.pw.plot(
            [], [], name="Live",
            pen=pg.mkPen(color=C_LIVE, width=1.5),
        )

        self.curve_peak = self.pw.plot(
            [], [], name="Peak hold",
            pen=pg.mkPen(color=C_PEAK, width=1,
                         style=Qt.PenStyle.DotLine),
        ) if peak_hold else None

        self.curve_avg = self.pw.plot(
            [], [], name=f"Avg {self.avg_count}f",
            pen=pg.mkPen(color=C_AVG, width=2),
        ) if self.avg_count > 1 else None

        # ── Cursor crosshair ──────────────────────────────────────────────────
        self._vline = pg.InfiniteLine(angle=90, movable=False,
                                      pen=pg.mkPen(C_CURSOR, width=1,
                                                   style=Qt.PenStyle.DashLine))
        self._hline = pg.InfiniteLine(angle=0,  movable=False,
                                      pen=pg.mkPen(C_CURSOR, width=1,
                                                   style=Qt.PenStyle.DashLine))
        self.pw.addItem(self._vline, ignoreBounds=True)
        self.pw.addItem(self._hline, ignoreBounds=True)

        self.lbl_cursor = pg.TextItem(anchor=(0, 1), color=C_CURSOR)
        self.lbl_cursor.setFont(mono)
        self.pw.addItem(self.lbl_cursor)

        self.pw.scene().sigMouseMoved.connect(self._on_mouse_move)

        # ── Internal state ────────────────────────────────────────────────────
        self._peak_f: np.ndarray | None = None
        self._peak_l: np.ndarray | None = None
        self._avg_buf: deque[np.ndarray] = deque(maxlen=self.avg_count)
        self._last_freqs:  np.ndarray | None = None
        self._last_levels: np.ndarray | None = None

        # ── Device + timer ────────────────────────────────────────────────────
        self.reader = DeviceReader()
        self.reader.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh)
        self.timer.start(40)   # 25 Hz UI cap

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_mouse_move(self, pos):
        if not self.pw.sceneBoundingRect().contains(pos):
            return
        mp = self.pw.getPlotItem().vb.mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._vline.setPos(x)
        self._hline.setPos(y)

        # snap to nearest sample
        label = f"{x:.3f} MHz\n{y:.1f} dBm"
        if self._last_freqs is not None:
            idx = int(np.argmin(np.abs(self._last_freqs - x)))
            snapped_level = float(self._last_levels[idx])
            label = f"{x:.3f} MHz\n{snapped_level:.1f} dBm"

        self.lbl_cursor.setText(label)
        self.lbl_cursor.setPos(x, y)

    def _reset_peak(self):
        self._peak_f = None
        self._peak_l = None
        if self.curve_peak is not None:
            self.curve_peak.setData([], [])

    def _refresh(self):
        if self.reader.error:
            self.lbl_status.setText(f"ERROR: {self.reader.error}")
            self.timer.stop()
            return

        data = self.reader.get()
        if data is None:
            return

        freqs, levels = data
        self._last_freqs  = freqs
        self._last_levels = levels

        # live + fill
        self.curve_live.setData(freqs, levels)
        floor = np.full_like(levels, LEVEL_MIN_DBM)
        self._ref_line.setData(freqs, floor)
        live_item = pg.PlotDataItem(freqs, levels)
        ref_item  = pg.PlotDataItem(freqs, floor)
        self.fill.setCurves(live_item, ref_item)

        # peak hold
        if self.curve_peak is not None:
            if self._peak_l is None or len(self._peak_l) != len(levels):
                self._peak_f = freqs.copy()
                self._peak_l = levels.copy()
            else:
                self._peak_l = np.maximum(self._peak_l, levels)
            self.curve_peak.setData(self._peak_f, self._peak_l)

        # average
        if self.curve_avg is not None:
            self._avg_buf.append(levels)
            avg = np.mean(np.stack(self._avg_buf), axis=0)
            self.curve_avg.setData(freqs, avg)

        # status bar
        peak_idx   = int(np.argmax(levels))
        peak_freq  = float(freqs[peak_idx])
        peak_level = float(levels[peak_idx])
        self.lbl_status.setText(
            f"Frames: {self.reader.frame_count:,}  │  "
            f"FPS: {self.reader.fps:.1f}  │  "
            f"Peak: {peak_level:.1f} dBm @ {peak_freq:.3f} MHz  │  "
            f"Samples: {len(freqs)}"
        )

    def closeEvent(self, event):
        self.timer.stop()
        self.reader.stop()
        self.reader.join(timeout=3)
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="U.Discover real-time RF spectrum viewer")
    parser.add_argument("--peak-hold", action="store_true",
                        help="Show peak-hold trace (red dotted)")
    parser.add_argument("--avg", type=int, default=1, metavar="N",
                        help="N-frame running average trace (blue, default off)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = SpectrumViewer(peak_hold=args.peak_hold, avg_count=args.avg)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
