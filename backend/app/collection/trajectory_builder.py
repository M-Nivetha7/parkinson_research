"""Raw fingertip trajectory, stroke segmentation, pen-lift intervals and timestamp-quality validation.

Behavioural port of the old air-writing capture logic (draw while index-only is up, lift on index+middle,
clear on fist) with the ParkiScribe raw-data rules:

* every frame yields one raw sample of landmark 8 (index fingertip) with a ``valid`` flag; missing samples
  keep ``None`` coordinates -- they are never zero-filled, interpolated or smoothed here;
* strokes are never silently joined: a stroke ends on pen-lift, any non-draw state, tracking loss, an invalid
  frame, or a time gap larger than ``max_gap_ms``;
* timestamps are the captured ones; irregular sampling is preserved and quantified.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .landmark_extractor import FrameObservation, HandObservation, INDEX_TIP, select_hand
from .gesture_detector import GestureStateMachine, detect

DEFAULT_MAX_GAP_MS = 250.0


@dataclass
class RawSample:
    seq: int
    timestamp_ms: float
    valid: bool
    x: Optional[float]            # normalized, original camera frame (landmark 8)
    y: Optional[float]
    z: Optional[float]
    px: Optional[float]
    py: Optional[float]
    raw_state: str                # un-debounced gesture state for this frame
    state: str                    # debounced state used for stroke logic
    handedness: Optional[str]
    hand_count: int

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def validate_timestamps(ts_ms: Sequence[float], dropped_factor: float = 1.5) -> Dict[str, Any]:
    """Quantify sampling quality from capture timestamps. Nothing is repaired or resampled."""
    n = len(ts_ms)
    rep: Dict[str, Any] = {"n_frames": n, "monotonic": True, "n_duplicates": 0, "n_non_increasing": 0,
                           "median_interval_ms": None, "mean_fps": None, "median_fps": None,
                           "interval_std_ms": None, "max_interval_ms": None,
                           "n_dropped_suspected": 0, "dropped_fraction": None, "usable": False}
    if n < 3 or any(t != t for t in ts_ms):
        return rep
    d = [ts_ms[i + 1] - ts_ms[i] for i in range(n - 1)]
    rep["n_duplicates"] = sum(1 for x in d if x == 0)
    rep["n_non_increasing"] = sum(1 for x in d if x <= 0)
    rep["monotonic"] = rep["n_non_increasing"] == 0
    pos = sorted(x for x in d if x > 0)
    if not pos:
        return rep
    med = pos[len(pos) // 2] if len(pos) % 2 else 0.5 * (pos[len(pos) // 2 - 1] + pos[len(pos) // 2])
    mean = sum(pos) / len(pos)
    rep["median_interval_ms"] = med
    rep["median_fps"] = 1000.0 / med
    span = ts_ms[-1] - ts_ms[0]
    rep["mean_fps"] = 1000.0 * (n - 1) / span if span > 0 else None
    rep["interval_std_ms"] = math.sqrt(sum((x - mean) ** 2 for x in pos) / len(pos))
    rep["max_interval_ms"] = max(pos)
    # a gap of k*median is counted as (round(gap/median)-1) missing frames
    missing = sum(max(0, round(x / med) - 1) for x in pos if x > dropped_factor * med)
    rep["n_dropped_suspected"] = missing
    rep["dropped_fraction"] = missing / (n + missing)
    rep["usable"] = rep["monotonic"]
    return rep


def build_raw_samples(frames: Sequence[FrameObservation], *, hand_strategy: str = "highest_score",
                      preferred_handedness: Optional[str] = None, debounce_frames: int = 2,
                      finger_ratio: Optional[float] = None) -> Dict[str, Any]:
    """Frame observations -> raw samples + gesture events (hand explicitly selected per frame)."""
    sm = GestureStateMachine(debounce_frames)
    samples: List[RawSample] = []
    for f in frames:
        if f.status == "invalid_frame":
            samples.append(RawSample(f.seq, f.timestamp_ms, False, None, None, None, None, None,
                                     "invalid", "invalid", None, 0))
            continue
        sel = select_hand(f.hands, hand_strategy, preferred_handedness)
        hand: Optional[HandObservation] = f.hands[sel] if sel is not None else None
        raw_state = detect(hand) if finger_ratio is None else detect(hand, finger_ratio)
        n_ev = len(sm.events)
        state = sm.update(raw_state, f.timestamp_ms, f.seq)
        if len(sm.events) > n_ev and sm.min_frames > 1:
            # Debounce confirmed a transition: the onset frames that were part of the confirming run get the
            # new debounced state retroactively (raw_state is untouched), so strokes start at the true onset.
            for prev in samples[-(sm.min_frames - 1):]:
                prev.state = state
        tip = hand.lm(INDEX_TIP) if hand is not None else None
        if tip is None:
            samples.append(RawSample(f.seq, f.timestamp_ms, False, None, None, None, None, None, raw_state, state,
                                     hand.handedness if hand else None, len(f.hands)))
        else:
            samples.append(RawSample(f.seq, f.timestamp_ms, True, tip.x, tip.y, tip.z, tip.px, tip.py, raw_state,
                                     state, hand.handedness, len(f.hands)))
    return {"samples": samples, "gesture_events": [e.to_dict() for e in sm.events]}


def segment_strokes(samples: Sequence[RawSample], max_gap_ms: float = DEFAULT_MAX_GAP_MS) -> Dict[str, Any]:
    """Split raw samples into separate strokes and pen-lift intervals. Samples themselves are not modified."""
    strokes: List[Dict[str, Any]] = []
    pen_lifts: List[Dict[str, Any]] = []
    tracking_loss: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    lift_start: Optional[int] = None  # index into samples where an inter-stroke interval began
    lost_start: Optional[int] = None

    def close(reason: str, end_i: int):
        nonlocal cur, lift_start
        if cur is None:
            return
        cur["end_reason"] = reason
        cur["end_index"] = end_i
        cur["end_ms"] = samples[end_i].timestamp_ms
        cur["n_samples"] = len(cur["sample_indices"])
        strokes.append(cur)
        cur = None
        lift_start = end_i

    for i, s in enumerate(samples):
        # tracking-loss bookkeeping (valid == tip observed)
        if not s.valid:
            if lost_start is None:
                lost_start = i
        elif lost_start is not None:
            tracking_loss.append({"start_ms": samples[lost_start].timestamp_ms, "end_ms": s.timestamp_ms,
                                  "start_index": lost_start, "end_index": i, "n_frames": i - lost_start})
            lost_start = None

        drawing = s.valid and s.state == "draw"
        if cur is not None:
            prev = samples[cur["sample_indices"][-1]]
            if s.timestamp_ms - prev.timestamp_ms > max_gap_ms:
                close("time_gap", cur["sample_indices"][-1])
        if drawing:
            if cur is None:
                if lift_start is not None:
                    pen_lifts.append({"start_ms": samples[lift_start].timestamp_ms, "end_ms": s.timestamp_ms,
                                      "start_index": lift_start, "end_index": i})
                    lift_start = None
                cur = {"start_index": i, "start_ms": s.timestamp_ms, "sample_indices": []}
            cur["sample_indices"].append(i)
        elif cur is not None:
            reason = ("tracking_loss" if not s.valid else
                      "pen_lift" if s.state == "pen_lift" else
                      "fist_clear" if s.state == "fist" else "state_change")
            close(reason, cur["sample_indices"][-1])
    if cur is not None:
        close("recording_end", cur["sample_indices"][-1])
    if lost_start is not None:
        tracking_loss.append({"start_ms": samples[lost_start].timestamp_ms, "end_ms": None,
                              "start_index": lost_start, "end_index": None,
                              "n_frames": len(samples) - lost_start})
    return {"strokes": strokes, "pen_lift_intervals": pen_lifts, "tracking_loss_events": tracking_loss}
