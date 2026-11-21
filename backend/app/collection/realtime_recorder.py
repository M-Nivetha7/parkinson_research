"""Recording session: start / pause / resume / stop, raw persistence, quality metadata.

Raw data are written BEFORE any processed representation and are never overwritten by it:
  raw_landmarks.json   every frame, every detected hand, all 21 landmarks (None for missing)
  raw_fingertip.csv    landmark 8 per frame, empty cells for missing (never 0)
  gesture_events.json  debounced gesture transitions with onset timestamps
  strokes.json         strokes, pen-lift intervals, tracking-loss events (derived, separate file)
  recording_meta.json  device / camera / timing-quality / control events
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional

from .landmark_extractor import FrameObservation, parse_frame
from .trajectory_builder import build_raw_samples, segment_strokes, validate_timestamps

CSV_COLUMNS = ["seq", "timestamp_ms", "valid", "x", "y", "z", "px", "py", "raw_state", "state",
               "handedness", "hand_count"]


class RecordingError(RuntimeError):
    pass


class RecordingSession:
    def __init__(self, participant_id: str, session_id: str, task_label: Optional[str] = None, *,
                 device_info: Optional[Dict[str, Any]] = None, mirrored_preview: bool = False,
                 timestamp_source: str = "unknown", hand_strategy: str = "highest_score",
                 preferred_handedness: Optional[str] = None, debounce_frames: int = 2):
        self.participant_id, self.session_id, self.task_label = participant_id, session_id, task_label
        self.device_info = device_info or {}
        self.mirrored_preview = mirrored_preview
        self.timestamp_source = timestamp_source
        self.hand_strategy, self.preferred_handedness, self.debounce_frames = hand_strategy, preferred_handedness, debounce_frames
        self.state = "idle"                      # idle | recording | paused | stopped
        self.frames: List[FrameObservation] = []
        self.raw_input: List[Dict[str, Any]] = []   # untouched input dicts, preserved verbatim
        self.control_events: List[Dict[str, Any]] = []
        self._last_ts: Optional[float] = None

    # ---- lifecycle ----
    def _event(self, name: str, ts: Optional[float]):
        self.control_events.append({"event": name, "timestamp_ms": ts})

    def start(self, timestamp_ms: Optional[float] = None):
        if self.state != "idle":
            raise RecordingError(f"cannot start from state {self.state}")
        self.state = "recording"; self._event("start", timestamp_ms)

    def pause(self, timestamp_ms: Optional[float] = None):
        if self.state != "recording":
            raise RecordingError(f"cannot pause from state {self.state}")
        self.state = "paused"; self._event("pause", timestamp_ms)

    def resume(self, timestamp_ms: Optional[float] = None):
        if self.state != "paused":
            raise RecordingError(f"cannot resume from state {self.state}")
        self.state = "recording"; self._event("resume", timestamp_ms)

    def stop(self, timestamp_ms: Optional[float] = None):
        if self.state not in ("recording", "paused"):
            raise RecordingError(f"cannot stop from state {self.state}")
        self.state = "stopped"; self._event("stop", timestamp_ms)

    def add_frame(self, raw_frame: Dict[str, Any]) -> FrameObservation:
        """Add one captured frame (dict). Frames received while not recording are rejected, not dropped silently."""
        if self.state != "recording":
            raise RecordingError(f"not recording (state={self.state})")
        self.raw_input.append(raw_frame)                    # keep original, pre-parse
        f = parse_frame(raw_frame, mirrored_input=self.mirrored_preview)
        if not f.timestamp_source or f.timestamp_source == "unknown":
            f.timestamp_source = self.timestamp_source
        self.frames.append(f)
        return f

    # ---- outputs ----
    def finalize(self) -> Dict[str, Any]:
        if self.state == "recording":
            self.stop()
        built = build_raw_samples(self.frames, hand_strategy=self.hand_strategy,
                                  preferred_handedness=self.preferred_handedness, debounce_frames=self.debounce_frames)
        samples = built["samples"]
        seg = segment_strokes(samples)
        ts = [f.timestamp_ms for f in self.frames if f.status != "invalid_frame"]
        tq = validate_timestamps(ts)
        n = len(samples)
        valid = sum(1 for s in samples if s.valid)
        meta = {
            "participant_id": self.participant_id, "session_id": self.session_id, "task_label": self.task_label,
            "device_info": self.device_info, "mirrored_preview": self.mirrored_preview,
            "stored_coordinate_convention": "original camera frame (un-mirrored), origin top-left, x right, y down",
            "timestamp_source": self.timestamp_source,
            "camera_resolution": ({"width": self.frames[0].width, "height": self.frames[0].height} if self.frames else None),
            "timestamp_quality": tq,
            "n_frames": n, "n_valid_fingertip": valid,
            "tracking_failure_rate": (1 - valid / n) if n else None,
            "n_invalid_frames": sum(1 for f in self.frames if f.status == "invalid_frame"),
            "n_incomplete_hands": sum(1 for f in self.frames for h in f.hands if not h.complete),
            "n_multi_hand_frames": sum(1 for f in self.frames if len(f.hands) > 1),
            "control_events": self.control_events,
            "processing_applied_to_raw": False,
        }
        return {"meta": meta, "samples": samples, "gesture_events": built["gesture_events"], **seg}

    def save(self, out_dir: str) -> Dict[str, str]:
        os.makedirs(out_dir, exist_ok=True)
        res = self.finalize()
        paths = {k: os.path.join(out_dir, v) for k, v in {
            "raw_landmarks": "raw_landmarks.json", "raw_fingertip": "raw_fingertip.csv",
            "gesture_events": "gesture_events.json", "strokes": "strokes.json", "meta": "recording_meta.json"}.items()}
        with open(paths["raw_landmarks"], "w") as fh:
            json.dump({"frames": [f.to_dict() for f in self.frames]}, fh)
        with open(paths["raw_fingertip"], "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(CSV_COLUMNS)
            for s in res["samples"]:
                d = s.to_dict()
                w.writerow(["" if d[c] is None else d[c] for c in CSV_COLUMNS])
        with open(paths["gesture_events"], "w") as fh:
            json.dump(res["gesture_events"], fh)
        with open(paths["strokes"], "w") as fh:
            json.dump({k: res[k] for k in ("strokes", "pen_lift_intervals", "tracking_loss_events")}, fh)
        with open(paths["meta"], "w") as fh:
            json.dump(res["meta"], fh, indent=2)
        return paths
