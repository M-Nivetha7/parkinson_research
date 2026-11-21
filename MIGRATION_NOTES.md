# MIGRATION_NOTES

Scope: only the two approved components of `M-Nivetha7/ParkiScribe` were reused -- MediaPipe hand tracking and
air-writing / fingertip trajectory capture. Nothing else from the old repository was read, ported or reused.

## 1. Old source files inspected (exactly two)

| File | Lines | Why |
|---|---|---|
| `src/hand_tracker.py` | 135 | approved component 1 |
| `app/web_app.py` | 348 | approved component 2: only `/api/process_frame` (lines ~263-333) and the `LiveHandTracker` / `live_fingers_up` usage |

Fetched as raw single files (`raw.githubusercontent.com`); the repository was not cloned and no other file was opened.

**Dependency not inspected:** `utils/constants.py::LANDMARK_INDEX_TIP`. Not opened (outside scope). The new code uses
the explicit MediaPipe constant `8` (index fingertip) and tests assert that raw samples equal landmark 8.

The rest of `web_app.py` (model loading, `/api/predict`, `/api/simulate`, `/api/decode_word`, the NLP/simulator/model
imports) was visible in the file but is **out of scope and was not ported**.

Stroke drawing / canvas code that lives in the browser (templates / JS) was **not inspected** (not one of the two
permitted files). The new stroke logic is therefore a re-implementation from the old *server-side* states
(`draw`, `pen_lift`, `fist`) and the project requirements, not a port of the old client code.

## 2. What the old components did

`HandTracker` (legacy `mp.solutions.hands`): converts a BGR frame to RGB, runs `Hands.process`, returns for every
detected hand a flat list `(id, int(x*w), int(y*h))` over all hands; `fingers_up` marks index/middle/ring/pinky "up" if
`tip.y < pip.y` in pixels; `classify_gesture` maps to `fist` (all down), `pen_lift` (index+middle), `draw` (index only),
`erase` (pinky only), `idle`, `none`.
`/api/process_frame`: receives one base64 image per HTTP request, runs the shared tracker, returns only the index
fingertip (normalized + pixel), the gesture state and the finger flags.

## 3. Audit findings (against Sections 6, 8, 12, 22.1)

| # | Question | Finding in old code |
|---|---|---|
| 1 | Fixed 30 Hz instead of real timestamps? | `process_frame` returns **no timestamp at all**. Elsewhere in `web_app.py` (`/api/predict`) timestamps are fabricated with `np.linspace(0, n/30, n)`. |
| 2 | Missing landmarks zero-filled? | Tracker itself does not zero-fill. `/api/predict` appends a **zero z column** (`np.zeros`) to 2-D trajectories and analyses `np.zeros((3,3))` when <3 points (recognition path; not ported). |
| 3 | Only fingertip saved? | Yes. All 21 are computed but only the tip is returned; z, visibility and handedness are dropped. Nothing is persisted. |
| 4 | Confidence / tracking loss recorded? | No. Detection/tracking confidence are only constructor thresholds; loss is just `detected: false`. |
| 5 | Processing before raw storage? | Pixel coordinates are truncated with `int()` (precision loss); frames arrive as re-encoded base64 images; raw data are never stored. |
| 6 | Normalized and pixel both kept? | Tip only (normalized and pixel). `get_landmarks` returns truncated integer pixels for the rest, no normalized/z. |
| 7 | Incomplete landmark safety? | `fingers_up` returns `[]` for <21 landmarks, but `process_frame` then indexes `fingers[0]` -> `IndexError` -> HTTP 500 (latent; MediaPipe normally yields 21). "No hand" and "incomplete hand" are conflated as `none`. |
| 8 | Multiple hands? | `get_landmarks` concatenates all hands into one list; with `max_hands>1`, indexing `lm_list[8]` silently means "first hand" with no handedness and no selection. |
| 9 | Strokes / pen-lift preserved? | Server returns per-frame state only; no stroke objects or intervals. Client code not inspected. |
| 10 | Timestamp consistency? | One HTTP request per frame, a **single global tracker instance** with mutable `self.results` shared across requests (not thread-safe), network jitter unrecorded. |
| extra | Orientation dependence | "Finger up" = pixel `tip.y < pip.y`: wrong for a rotated hand or tilted camera; not hand-size relative. |
| extra | Mirroring | Not handled/recorded server-side; handedness never reported. |
| extra | API | Legacy `mp.solutions.hands` (replaced by MediaPipe Tasks `HandLandmarker`). |

## 3b. What each audit finding became

All of the above are fixed in the new modules (see section 5 tests). Items 1-2 refer to code that was **not**
ported, so they are recorded as "do not repeat" rather than "fixed".

## 4. Ported / re-implemented

| Old behaviour | New location | Status |
|---|---|---|
| landmark extraction (21 pts) | `backend/app/collection/landmark_extractor.py` (Python, offline) and `frontend/src/features/hand-tracking/landmarks.ts` (live) | ported + extended (all 21, normalized + pixel + z + visibility/presence, per-hand objects, `None` for missing, explicit hand selection, mirrored-input conversion) |
| `fingers_up` / `classify_gesture` | `gesture_detector.py` / `gesture.ts` | ported; rule changed to wrist-distance ratio (rotation / scale / mirror invariant); `unknown` vs `none`; debounced transitions with onset timestamps |
| fingertip trajectory / pen-lift / clear | `trajectory_builder.py` / `trajectory.ts` | re-implemented: raw landmark-8 samples with `valid` flag, separate strokes, pen-lift intervals, tracking-loss events, time-gap splits, timestamp-quality report |
| per-frame HTTP processing | **not ported** | replaced by browser-side tracking (decision in master prompt Section 7) |
| session capture | `realtime_recorder.py` | new: start/pause/resume/stop, verbatim input retention, raw JSON + CSV, quality metadata |
| offline re-extraction | `landmark_extractor.extract_from_video` | written, **not yet validated on a real video** |

`gesture_detector.py` thresholds: `EXTENSION_RATIO = 1.10` is a documented default validated only on constructed poses.

## 5. Excluded on purpose

Old models, checkpoints, training, simulator, dataset generator, NLP decoder, preprocessing, motor analysis,
evaluation, tests, README figures, manuscript numbers, `/api/predict`, `/api/simulate`, `/api/decode_word`.

## 6. Tests validating the migration

`backend/tests/test_collection.py` (69 tests) and `frontend/tests/handtracking.test.ts` (53 tests) both read
`backend/tests/fixtures/landmark_fixtures.json`, generated by `make_fixtures.py`.

**Limits of that evidence (important):**
* The fixtures are **constructed geometric hands, not recordings of a person**. Expected values were written by hand
  from the construction. They prove the logic, not real-world accuracy.
* **Recorded-video tracker comparison (browser vs Python) has NOT been done.** No MediaPipe model file or video
  clip is available in this build environment. Numerical tolerances between the two trackers are therefore
  **undocumented / pending**.
* Python rounds half-to-even and JavaScript rounds half-up in the dropped-frame estimate
  (`round(gap/median)`); they differ only for exact `.5` ratios. Not exercised by the fixtures.
