import csv
import json
import math
import os

import pytest

from app.collection.landmark_extractor import (parse_frame, parse_hand, select_hand, hand_size, NUM_LANDMARKS)
from app.collection.gesture_detector import (fingers_extended, classify_gesture, detect, GestureStateMachine)
from app.collection.trajectory_builder import build_raw_samples, segment_strokes, validate_timestamps
from app.collection.realtime_recorder import RecordingSession, RecordingError

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "landmark_fixtures.json")))
W, H = FX["image"]["width"], FX["image"]["height"]
SEQ = {s["name"]: s for s in FX["sequences"]}


def hand_of(pose):
    return parse_hand(pose["hand"], W, H, mirrored_input=pose["mirrored_input"])


# ---------- landmark extraction ----------
def test_all_21_landmarks_with_normalized_and_pixel_coords():
    h = parse_hand(FX["poses"][0]["hand"], W, H)
    assert len(h.landmarks) == NUM_LANDMARKS == 21 and h.complete and h.n_missing() == 0
    for l in h.landmarks:
        assert l.px == pytest.approx(l.x * W) and l.py == pytest.approx(l.y * H)
        assert l.visibility is not None and l.presence is not None


def test_missing_landmark_stays_none_never_zero():
    pose = next(p for p in FX["poses"] if p["name"] == "draw_missing_index_tip")
    h = hand_of(pose)
    assert h.landmarks[8] is None and not h.complete and h.n_missing() == 1


def test_short_landmark_list_padded_with_none():
    pose = next(p for p in FX["poses"] if p["name"] == "draw_only_15_landmarks")
    h = hand_of(pose)
    assert len(h.landmarks) == 21 and h.n_missing() == 6 and all(l is None for l in h.landmarks[15:])


def test_nan_and_inf_become_missing():
    raw = json.loads(json.dumps(FX["poses"][0]["hand"]))
    raw["landmarks"][3]["x"] = float("nan")
    raw["landmarks"][4]["y"] = float("inf")
    h = parse_hand(raw, W, H)
    assert h.landmarks[3] is None and h.landmarks[4] is None


@pytest.mark.parametrize("bad", [
    {"seq": 0, "timestamp_ms": float("nan"), "width": 640, "height": 480, "hands": []},
    {"seq": 0, "timestamp_ms": 10.0, "width": 0, "height": 480, "hands": []},
    {"seq": 0, "timestamp_ms": 10.0, "width": 640, "height": None, "hands": []},
    {"seq": 0, "timestamp_ms": None, "width": 640, "height": 480, "hands": []},
])
def test_invalid_frame_flagged(bad):
    assert parse_frame(bad).status == "invalid_frame"


def test_no_hand_frame():
    f = parse_frame({"seq": 1, "timestamp_ms": 5.0, "width": 640, "height": 480, "hands": []})
    assert f.status == "no_hand" and f.hands == []


def test_mirrored_input_is_converted_to_camera_frame_and_handedness_swapped():
    base = FX["poses"][0]["hand"]
    mirrored = json.loads(json.dumps(base))
    for l in mirrored["landmarks"]:
        l["x"] = 1.0 - l["x"]
    mirrored["handedness"] = "Left" if base["handedness"] == "Right" else "Right"
    h_plain = parse_hand(base, W, H)
    h_back = parse_hand(mirrored, W, H, mirrored_input=True)
    assert h_back.handedness == h_plain.handedness
    for a, b in zip(h_plain.landmarks, h_back.landmarks):
        assert a.x == pytest.approx(b.x) and a.px == pytest.approx(b.px)


# ---------- hand selection / multiple hands ----------
def test_multi_hand_selection_is_explicit():
    f = parse_frame(FX["multi_hand"]["frames"][0])
    e = FX["multi_hand"]["expected"]
    assert len(f.hands) == 2
    assert select_hand(f.hands, "highest_score") == e["highest_score_index"]
    assert select_hand(f.hands, "largest") == e["largest_index"]
    assert select_hand(f.hands, "preferred_handedness", "Right") == e["preferred_right_index"]
    assert select_hand(f.hands, "preferred_handedness", "Middle") == e["highest_score_index"]  # fallback
    assert select_hand([], "highest_score") is None


def test_multi_hand_does_not_corrupt_indexing():
    f = parse_frame(FX["multi_hand"]["frames"][0])
    out = build_raw_samples([f], hand_strategy="preferred_handedness", preferred_handedness="Right", debounce_frames=1)
    s = out["samples"][0]
    assert s.valid and s.x == pytest.approx(FX["multi_hand"]["expected"]["preferred_right_tip_x"]) and s.hand_count == 2
    out2 = build_raw_samples([f], debounce_frames=1)
    assert out2["samples"][0].x == pytest.approx(FX["multi_hand"]["expected"]["highest_score_tip_x"])


# ---------- gestures ----------
@pytest.mark.parametrize("pose", FX["poses"], ids=lambda p: p["name"])
def test_pose_gesture_and_fingers(pose):
    h = hand_of(pose)
    assert fingers_extended(h) == pose["expected_fingers"]
    assert detect(h) == pose["expected_gesture"]


def test_classification_rules_match_old_behaviour():
    assert classify_gesture([False] * 4) == "fist"
    assert classify_gesture([True, True, False, False]) == "pen_lift"
    assert classify_gesture([True, False, False, False]) == "draw"
    assert classify_gesture([False, False, False, True]) == "erase"
    assert classify_gesture([False, False, True, False]) == "idle"
    assert classify_gesture([]) == "none"
    assert classify_gesture([True, False]) == "unknown"
    assert classify_gesture([None, False, False, False]) == "unknown"


def test_no_hand_is_none_not_unknown():
    assert detect(None) == "none"


def test_gesture_state_machine_debounce_and_onset_timestamp():
    sm = GestureStateMachine(min_frames=2)
    seq = ["draw", "pen_lift", "draw", "draw", "draw", "pen_lift", "pen_lift"]  # 1-frame flicker ignored
    for i, s in enumerate(seq):
        sm.update(s, 100.0 + 10 * i, i)
    assert [(e.from_state, e.to_state, e.seq) for e in sm.events] == [("none", "draw", 2), ("draw", "pen_lift", 5)]
    assert sm.events[0].timestamp_ms == 120.0     # onset of the confirmed run, not the confirmation frame


# ---------- timestamps ----------
def test_timestamp_validation_regular():
    ts = [i * 16.7 for i in range(100)]
    r = validate_timestamps(ts)
    assert r["monotonic"] and r["n_dropped_suspected"] == 0 and r["median_fps"] == pytest.approx(1000 / 16.7)


def test_timestamp_validation_dropped_frames_and_duplicates_and_nonmonotonic():
    ts = [i * 16.7 for i in range(20)]
    ts = ts[:10] + [t + 33.4 for t in ts[10:]]              # one gap of 3 periods -> 2 missing
    assert validate_timestamps(ts)["n_dropped_suspected"] == 2
    dup = [0.0, 16.7, 16.7, 33.4, 50.1]
    r = validate_timestamps(dup)
    assert r["n_duplicates"] == 1 and not r["monotonic"] and not r["usable"]
    back = [0.0, 16.7, 10.0, 33.4]
    assert not validate_timestamps(back)["monotonic"]


def test_timestamp_validation_too_short_or_nan():
    assert validate_timestamps([0.0, 1.0])["usable"] is False
    assert validate_timestamps([0.0, float("nan"), 2.0])["usable"] is False


# ---------- strokes, pen lift, tracking loss ----------
def run_sequence(name, debounce=2):
    seq = SEQ[name]
    frames = [parse_frame(f) for f in seq["frames"]]
    built = build_raw_samples(frames, debounce_frames=debounce)
    return seq, frames, built, segment_strokes(built["samples"])


def test_three_strokes_loss_penlift_and_dropped_frames():
    seq, frames, built, seg = run_sequence("three_strokes_with_loss_and_dropped_frames")
    e = seq["expected"]
    assert [s["n_samples"] for s in seg["strokes"]] == e["stroke_sample_counts"]
    assert [s["end_reason"] for s in seg["strokes"]] == e["stroke_end_reasons"]
    assert len(seg["pen_lift_intervals"]) == e["n_pen_lift_intervals"]
    assert len(seg["tracking_loss_events"]) == e["n_tracking_loss_events"]
    assert [x["n_frames"] for x in seg["tracking_loss_events"]] == e["tracking_loss_frames"]
    assert sum(1 for s in built["samples"] if s.valid) == e["n_valid_fingertip"]
    assert [g["to"] for g in built["gesture_events"]] == e["gesture_event_to_states"]
    tq = validate_timestamps([f.timestamp_ms for f in frames])
    assert tq["n_dropped_suspected"] == e["n_dropped_suspected"]
    assert tq["median_interval_ms"] == pytest.approx(e["median_interval_ms"], abs=1e-6)


def test_raw_fingertip_equals_landmark8_exactly_and_missing_is_none():
    seq, frames, built, _ = run_sequence("three_strokes_with_loss_and_dropped_frames")
    for s, f, tgt in zip(built["samples"], frames, seq["tip_targets"]):
        if tgt is None:
            assert not s.valid and s.x is None and s.y is None and s.px is None   # not 0.0
        else:
            tip = f.hands[0].landmarks[8]
            assert s.x == tip.x and s.y == tip.y and s.z == tip.z and s.px == tip.px
            assert s.x == pytest.approx(tgt[0], abs=1e-9) and s.y == pytest.approx(tgt[1], abs=1e-9)
        assert s.timestamp_ms == f.timestamp_ms          # captured timestamp, not synthesized


def test_strokes_are_not_joined_across_pen_lift():
    _, _, built, seg = run_sequence("three_strokes_with_loss_and_dropped_frames")
    a, b = seg["strokes"][0], seg["strokes"][1]
    assert max(a["sample_indices"]) < min(b["sample_indices"])
    assert set(a["sample_indices"]).isdisjoint(b["sample_indices"])
    assert all(built["samples"][i].state != "draw" for i in range(a["end_index"] + 1, b["start_index"]))


def test_time_gap_splits_stroke():
    seq, _, _, seg = run_sequence("time_gap_splits_stroke")
    e = seq["expected"]
    assert [s["n_samples"] for s in seg["strokes"]] == e["stroke_sample_counts"]
    assert [s["end_reason"] for s in seg["strokes"]] == e["stroke_end_reasons"]


def test_debounce_one_frame_gives_same_stroke_counts():
    seq, _, _, seg = run_sequence("three_strokes_with_loss_and_dropped_frames", debounce=1)
    assert [s["n_samples"] for s in seg["strokes"]] == seq["expected"]["stroke_sample_counts"]


def test_fist_ends_stroke_with_fist_reason():
    from app.collection.landmark_extractor import parse_frame as pf
    draw = FX["sequences"][0]["frames"][0]
    fist = next(p for p in FX["poses"] if p["name"] == "fist_upright")["hand"]
    frames = [pf(dict(draw, seq=i, timestamp_ms=i * 16.7)) for i in range(4)]
    frames += [pf({"seq": 4 + i, "timestamp_ms": (4 + i) * 16.7, "width": W, "height": H, "hands": [fist]}) for i in range(3)]
    built = build_raw_samples(frames, debounce_frames=2)
    seg = segment_strokes(built["samples"])
    assert len(seg["strokes"]) == 1 and seg["strokes"][0]["end_reason"] == "fist_clear"


def test_invalid_frame_ends_stroke_and_is_not_valid_sample():
    from app.collection.landmark_extractor import parse_frame as pf
    draw = FX["sequences"][0]["frames"][0]
    frames = [pf(dict(draw, seq=i, timestamp_ms=i * 16.7)) for i in range(4)]
    frames.append(pf({"seq": 4, "timestamp_ms": float("nan"), "width": 640, "height": 480, "hands": []}))
    frames += [pf(dict(draw, seq=5 + i, timestamp_ms=(5 + i) * 16.7)) for i in range(4)]
    built = build_raw_samples(frames, debounce_frames=1)
    assert built["samples"][4].valid is False and built["samples"][4].raw_state == "invalid"
    assert len(segment_strokes(built["samples"])["strokes"]) == 2


# ---------- recorder ----------
def make_session(**kw):
    return RecordingSession("TEST001", "session_001", "A", device_info={"ua": "pytest"}, timestamp_source="constructed", **kw)


def test_recorder_lifecycle_and_rejects_frames_when_not_recording():
    s = make_session()
    with pytest.raises(RecordingError):
        s.add_frame(SEQ["time_gap_splits_stroke"]["frames"][0])
    s.start()
    s.add_frame(SEQ["time_gap_splits_stroke"]["frames"][0])
    s.pause()
    with pytest.raises(RecordingError):
        s.add_frame(SEQ["time_gap_splits_stroke"]["frames"][1])
    s.resume(); s.stop()
    with pytest.raises(RecordingError):
        s.start()
    assert [e["event"] for e in s.control_events] == ["start", "pause", "resume", "stop"]


def test_recorder_saves_raw_files_without_overwriting_raw_with_processed(tmp_path):
    seq = SEQ["three_strokes_with_loss_and_dropped_frames"]
    s = make_session()
    s.start()
    for f in seq["frames"]:
        s.add_frame(f)
    paths = s.save(str(tmp_path))
    assert set(paths) == {"raw_landmarks", "raw_fingertip", "gesture_events", "strokes", "meta"}
    raw = json.load(open(paths["raw_landmarks"]))["frames"]
    assert len(raw) == len(seq["frames"])
    assert len(raw[0]["hands"][0]["landmarks"]) == 21                      # all 21 persisted
    assert raw[0]["hands"][0]["landmarks"][8]["px"] == pytest.approx(raw[0]["hands"][0]["landmarks"][8]["x"] * W)
    rows = list(csv.DictReader(open(paths["raw_fingertip"])))
    lost = [r for r in rows if r["valid"] == "False"]
    assert len(lost) == 3 and all(r["x"] == "" and r["y"] == "" for r in lost)   # empty, not 0
    meta = json.load(open(paths["meta"]))
    assert meta["processing_applied_to_raw"] is False
    assert meta["camera_resolution"] == {"width": W, "height": H}
    assert meta["timestamp_quality"]["n_dropped_suspected"] == 2
    assert meta["tracking_failure_rate"] == pytest.approx(3 / len(seq["frames"]))
    assert meta["timestamp_source"] == "constructed"


def test_recorder_mirrored_preview_stores_camera_frame(tmp_path):
    frame = json.loads(json.dumps(SEQ["time_gap_splits_stroke"]["frames"][0]))
    cam_x = frame["hands"][0]["landmarks"][8]["x"]
    for h in frame["hands"]:
        for l in h["landmarks"]:
            l["x"] = 1.0 - l["x"]
    s = make_session(mirrored_preview=True)
    s.start(); s.add_frame(frame)
    paths = s.save(str(tmp_path))
    stored = json.load(open(paths["raw_landmarks"]))["frames"][0]["hands"][0]["landmarks"][8]["x"]
    assert stored == pytest.approx(cam_x)
    assert json.load(open(paths["meta"]))["mirrored_preview"] is True


def test_recorder_keeps_original_input_verbatim():
    s = make_session(); s.start()
    f = SEQ["time_gap_splits_stroke"]["frames"][0]
    s.add_frame(f)
    assert s.raw_input[0] is f
