// TypeScript port of backend/app/collection/landmark_extractor.py (live browser capture).
// Same rules: all 21 landmarks, normalized + pixel coords, missing = null (never zero), each hand separate,
// stored coordinates are the ORIGINAL camera frame (mirrored-preview input is converted explicitly).

export const NUM_LANDMARKS = 21;
export const WRIST = 0, MIDDLE_MCP = 9;
export const INDEX_PIP = 6, INDEX_TIP = 8, MIDDLE_PIP = 10, MIDDLE_TIP = 12;
export const RING_PIP = 14, RING_TIP = 16, PINKY_PIP = 18, PINKY_TIP = 20;

export interface Landmark {
  index: number; x: number; y: number; z: number; px: number; py: number;
  visibility: number | null; presence: number | null;
}
export interface HandObservation {
  handedness: string | null; handedness_score: number | null;
  landmarks: (Landmark | null)[]; complete: boolean;
}
export interface FrameObservation {
  seq: number; timestamp_ms: number; width: number; height: number;
  hands: HandObservation[]; status: "ok" | "no_hand" | "invalid_frame"; timestamp_source: string;
}

type RawLm = { x?: unknown; y?: unknown; z?: unknown; visibility?: number | null; presence?: number | null } | null;
export interface RawHand { handedness?: string | null; score?: number | null; landmarks?: RawLm[] }
export interface RawFrame {
  seq?: number; timestamp_ms?: unknown; width?: unknown; height?: unknown;
  hands?: RawHand[]; timestamp_source?: string;
}

const validNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function swapHandedness(label: string | null | undefined): string | null {
  if (label === "Left") return "Right";
  if (label === "Right") return "Left";
  return label ?? null;
}

export function parseHand(raw: RawHand, width: number, height: number, mirroredInput = false): HandObservation {
  const lms: (Landmark | null)[] = [];
  const src = raw.landmarks ?? [];
  for (let i = 0; i < NUM_LANDMARKS; i++) {
    const it = src[i];
    if (!it || !validNum(it.x) || !validNum(it.y) || !validNum(it.z)) { lms.push(null); continue; }
    const x = mirroredInput ? 1 - it.x : it.x;
    lms.push({ index: i, x, y: it.y, z: it.z, px: x * width, py: it.y * height,
      visibility: it.visibility ?? null, presence: it.presence ?? null });
  }
  let label = raw.handedness ?? null;
  if (mirroredInput) label = swapHandedness(label);
  return { handedness: label, handedness_score: raw.score ?? null, landmarks: lms, complete: lms.every((l) => l !== null) };
}

export function parseFrame(raw: RawFrame, mirroredInput = false): FrameObservation {
  const { width: w, height: h, timestamp_ms: ts } = raw;
  const bad = !Number.isInteger(w) || !Number.isInteger(h) || (w as number) <= 0 || (h as number) <= 0 || !validNum(ts);
  if (bad) {
    return { seq: raw.seq ?? -1, timestamp_ms: validNum(ts) ? ts : NaN,
      width: Number.isInteger(w) ? (w as number) : 0, height: Number.isInteger(h) ? (h as number) : 0,
      hands: [], status: "invalid_frame", timestamp_source: raw.timestamp_source ?? "unknown" };
  }
  const hands = (raw.hands ?? []).map((hr) => parseHand(hr, w as number, h as number, mirroredInput));
  return { seq: raw.seq as number, timestamp_ms: ts as number, width: w as number, height: h as number, hands,
    status: hands.length ? "ok" : "no_hand", timestamp_source: raw.timestamp_source ?? "unknown" };
}

export function handSize(hand: HandObservation): number | null {
  const a = hand.landmarks[WRIST], b = hand.landmarks[MIDDLE_MCP];
  if (!a || !b) return null;
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export type HandStrategy = "highest_score" | "largest" | "preferred_handedness";

export function selectHand(hands: HandObservation[], strategy: HandStrategy = "highest_score",
                           preferred: string | null = null): number | null {
  if (!hands.length) return null;
  let cand = hands.map((_, i) => i);
  if (strategy === "preferred_handedness" && preferred) {
    const pref = cand.filter((i) => hands[i].handedness === preferred);
    if (pref.length) cand = pref;
  }
  const key = (i: number) => strategy === "largest" ? (handSize(hands[i]) ?? -1) : (hands[i].handedness_score ?? -1);
  let best = cand[0];
  for (const i of cand) if (key(i) > key(best)) best = i;   // ties -> lowest index
  return best;
}
