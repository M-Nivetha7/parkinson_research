// TypeScript port of backend/app/collection/trajectory_builder.py.
// Raw fingertip (landmark 8) samples keep null for missing data (never 0); strokes are never silently joined.
import { FrameObservation, HandObservation, INDEX_TIP, HandStrategy, selectHand } from "./landmarks";
import { GestureStateMachine, GestureEvent, detect } from "./gesture";

export const DEFAULT_MAX_GAP_MS = 250;

export interface RawSample {
  seq: number; timestamp_ms: number; valid: boolean;
  x: number | null; y: number | null; z: number | null; px: number | null; py: number | null;
  raw_state: string; state: string; handedness: string | null; hand_count: number;
}

export interface TimestampQuality {
  n_frames: number; monotonic: boolean; n_duplicates: number; n_non_increasing: number;
  median_interval_ms: number | null; mean_fps: number | null; median_fps: number | null;
  interval_std_ms: number | null; max_interval_ms: number | null;
  n_dropped_suspected: number; dropped_fraction: number | null; usable: boolean;
}

export function validateTimestamps(ts: number[], droppedFactor = 1.5): TimestampQuality {
  const n = ts.length;
  const rep: TimestampQuality = { n_frames: n, monotonic: true, n_duplicates: 0, n_non_increasing: 0,
    median_interval_ms: null, mean_fps: null, median_fps: null, interval_std_ms: null, max_interval_ms: null,
    n_dropped_suspected: 0, dropped_fraction: null, usable: false };
  if (n < 3 || ts.some((t) => Number.isNaN(t))) return rep;
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push(ts[i + 1] - ts[i]);
  rep.n_duplicates = d.filter((x) => x === 0).length;
  rep.n_non_increasing = d.filter((x) => x <= 0).length;
  rep.monotonic = rep.n_non_increasing === 0;
  const pos = d.filter((x) => x > 0).sort((a, b) => a - b);
  if (!pos.length) return rep;
  const m = pos.length >> 1;
  const med = pos.length % 2 ? pos[m] : 0.5 * (pos[m - 1] + pos[m]);
  const mean = pos.reduce((a, b) => a + b, 0) / pos.length;
  rep.median_interval_ms = med; rep.median_fps = 1000 / med;
  const span = ts[n - 1] - ts[0];
  rep.mean_fps = span > 0 ? (1000 * (n - 1)) / span : null;
  rep.interval_std_ms = Math.sqrt(pos.reduce((a, x) => a + (x - mean) ** 2, 0) / pos.length);
  rep.max_interval_ms = pos[pos.length - 1];
  // JS Math.round rounds .5 up; Python rounds half to even. Equal except on exact .5 ratios (documented tolerance).
  const missing = pos.filter((x) => x > droppedFactor * med).reduce((a, x) => a + Math.max(0, Math.round(x / med) - 1), 0);
  rep.n_dropped_suspected = missing; rep.dropped_fraction = missing / (n + missing);
  rep.usable = rep.monotonic;
  return rep;
}

export interface BuildOptions { handStrategy?: HandStrategy; preferredHandedness?: string | null; debounceFrames?: number }

export function buildRawSamples(frames: FrameObservation[], opt: BuildOptions = {}): { samples: RawSample[]; gesture_events: GestureEvent[] } {
  const sm = new GestureStateMachine(opt.debounceFrames ?? 2);
  const samples: RawSample[] = [];
  for (const f of frames) {
    if (f.status === "invalid_frame") {
      samples.push({ seq: f.seq, timestamp_ms: f.timestamp_ms, valid: false, x: null, y: null, z: null, px: null, py: null,
        raw_state: "invalid", state: "invalid", handedness: null, hand_count: 0 });
      continue;
    }
    const sel = selectHand(f.hands, opt.handStrategy ?? "highest_score", opt.preferredHandedness ?? null);
    const hand: HandObservation | null = sel !== null ? f.hands[sel] : null;
    const raw = detect(hand);
    const nEv = sm.events.length;
    const state = sm.update(raw, f.timestamp_ms, f.seq);
    if (sm.events.length > nEv && sm.minFrames > 1) {
      // onset frames of the confirming run take the new debounced state retroactively (raw_state untouched)
      for (const prev of samples.slice(-(sm.minFrames - 1))) prev.state = state;
    }
    const tip = hand ? hand.landmarks[INDEX_TIP] : null;
    if (!tip) samples.push({ seq: f.seq, timestamp_ms: f.timestamp_ms, valid: false, x: null, y: null, z: null, px: null, py: null,
      raw_state: raw, state, handedness: hand?.handedness ?? null, hand_count: f.hands.length });
    else samples.push({ seq: f.seq, timestamp_ms: f.timestamp_ms, valid: true, x: tip.x, y: tip.y, z: tip.z, px: tip.px, py: tip.py,
      raw_state: raw, state, handedness: hand!.handedness, hand_count: f.hands.length });
  }
  return { samples, gesture_events: sm.events };
}

export interface Stroke { start_index: number; start_ms: number; sample_indices: number[]; end_reason: string; end_index: number; end_ms: number; n_samples: number }
export interface Interval { start_ms: number; end_ms: number | null; start_index: number; end_index: number | null; n_frames?: number }

export function segmentStrokes(samples: RawSample[], maxGapMs = DEFAULT_MAX_GAP_MS) {
  const strokes: Stroke[] = [], penLifts: Interval[] = [], loss: Interval[] = [];
  let cur: { start_index: number; start_ms: number; sample_indices: number[] } | null = null;
  let liftStart: number | null = null, lostStart: number | null = null;

  const close = (reason: string, endI: number) => {
    if (!cur) return;
    strokes.push({ ...cur, end_reason: reason, end_index: endI, end_ms: samples[endI].timestamp_ms, n_samples: cur.sample_indices.length });
    cur = null; liftStart = endI;
  };

  samples.forEach((s, i) => {
    if (!s.valid) { if (lostStart === null) lostStart = i; }
    else if (lostStart !== null) {
      loss.push({ start_ms: samples[lostStart].timestamp_ms, end_ms: s.timestamp_ms, start_index: lostStart, end_index: i, n_frames: i - lostStart });
      lostStart = null;
    }
    const drawing = s.valid && s.state === "draw";
    if (cur) {
      const last = cur.sample_indices[cur.sample_indices.length - 1];
      if (s.timestamp_ms - samples[last].timestamp_ms > maxGapMs) close("time_gap", last);
    }
    if (drawing) {
      if (!cur) {
        if (liftStart !== null) { penLifts.push({ start_ms: samples[liftStart].timestamp_ms, end_ms: s.timestamp_ms, start_index: liftStart, end_index: i }); liftStart = null; }
        cur = { start_index: i, start_ms: s.timestamp_ms, sample_indices: [] };
      }
      cur.sample_indices.push(i);
    } else if (cur) {
      const reason = !s.valid ? "tracking_loss" : s.state === "pen_lift" ? "pen_lift" : s.state === "fist" ? "fist_clear" : "state_change";
      close(reason, cur.sample_indices[cur.sample_indices.length - 1]);
    }
  });
  if (cur) close("recording_end", (cur as { sample_indices: number[] }).sample_indices.slice(-1)[0]);
  if (lostStart !== null) loss.push({ start_ms: samples[lostStart].timestamp_ms, end_ms: null, start_index: lostStart, end_index: null, n_frames: samples.length - lostStart });
  return { strokes, pen_lift_intervals: penLifts, tracking_loss_events: loss };
}
