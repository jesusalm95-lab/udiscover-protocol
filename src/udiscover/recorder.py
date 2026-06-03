"""
Frame recorder — reads from device and saves frames to disk.

Used by tools/record_frames.py. Separated here so other tools can
import the recording logic without duplicating it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .device import UDiscoverDevice
from .frame import UDiscoverFrame, UDiscoverFrameCollector
from .packet import parse_packet, PacketParseError

log = logging.getLogger(__name__)


class FrameRecorder:
    """
    Records complete frames from the U.Discover to a directory.

    Usage
    -----
    recorder = FrameRecorder(out_dir="captures/session_001")
    recorder.run(n_frames=100)
    """

    def __init__(
        self,
        out_dir: str | Path,
        device: UDiscoverDevice | None = None,
        save_individual: bool = True,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.device = device or UDiscoverDevice()
        self.save_individual = save_individual
        self._collector = UDiscoverFrameCollector()
        self._complete_frames: list[UDiscoverFrame] = []

    def run(self, n_frames: int) -> list[UDiscoverFrame]:
        """
        Read from the device until n_frames complete frames are captured.
        Returns the list of complete frames.
        """
        self.out_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = self.out_dir / "frames.jsonl"
        raw_path = self.out_dir / "frames_raw.txt"

        log.info("Recording %d complete frames to %s", n_frames, self.out_dir)

        with (
            self.device,
            open(jsonl_path, "w", encoding="utf-8") as jsonl_f,
            open(raw_path, "w", encoding="utf-8") as raw_f,
        ):
            while len(self._complete_frames) < n_frames:
                text = self.device.read_text_packet()
                if not text:
                    continue

                raw_f.write(text + "\n")
                raw_f.flush()

                try:
                    packet = parse_packet(text)
                except PacketParseError as exc:
                    log.warning("Parse error: %s", exc)
                    continue

                if packet is None:
                    continue

                sealed = self._collector.add_packet(packet)

                if sealed is not None and sealed.complete:
                    self._complete_frames.append(sealed)
                    self._save_frame(sealed, jsonl_f)
                    print(
                        f"\rFrames: {len(self._complete_frames)}/{n_frames}  "
                        f"(incomplete: {self._collector.frames_incomplete})",
                        end="",
                        flush=True,
                    )

        # Flush last in-progress frame
        last = self._collector.flush()
        if last is not None:
            log.info(
                "Last frame %d was in progress at stop (%s)",
                last.frame_number,
                "complete" if last.complete else "INCOMPLETE",
            )

        print()  # newline after progress line
        log.info(
            "Done. Complete: %d  Incomplete: %d  Total sealed: %d",
            len(self._complete_frames),
            self._collector.frames_incomplete,
            self._collector.frames_captured,
        )
        return self._complete_frames

    def _save_frame(self, frame: UDiscoverFrame, jsonl_f) -> None:
        data = frame.to_dict()
        jsonl_f.write(json.dumps(data) + "\n")
        jsonl_f.flush()

        if self.save_individual:
            fname = self.out_dir / f"frame_{frame.frame_number:06d}.json"
            fname.write_text(json.dumps(data, indent=2), encoding="utf-8")
