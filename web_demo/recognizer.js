/* Glyph-template air-writing recognizer.
 *
 * NOT a trained model. It renders the written strokes to a small bitmap and compares it with bitmaps of
 * the characters drawn in several installed fonts (cosine similarity of blurred 32x32 images).
 * Scores are SIMILARITIES, not probabilities. Accuracy on real people is unmeasured.
 * Works in the browser (pass makeCanvas = (w,h) => canvas) and in Node with the `canvas` package.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.GlyphRecognizer = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const N = 32, BIG = 128, PAD = 3;
  let STROKE_W = 7, PASSES = 2, CENTER = false;
  const DEFAULT_CLASSES = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", ..."0123456789"];

  function boxBlur(a, r) {
    const t = new Float32Array(a.length), o = new Float32Array(a.length);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      let s = 0, c = 0;
      for (let dx = -r; dx <= r; dx++) { const xx = x + dx; if (xx >= 0 && xx < N) { s += a[y * N + xx]; c++; } }
      t[y * N + x] = s / c;
    }
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      let s = 0, c = 0;
      for (let dy = -r; dy <= r; dy++) { const yy = y + dy; if (yy >= 0 && yy < N) { s += t[yy * N + x]; c++; } }
      o[y * N + x] = s / c;
    }
    return o;
  }

  function create(opts) {
    const makeCanvas = opts.makeCanvas;
    if (opts.strokeWidth) STROKE_W = opts.strokeWidth;
    if (opts.blurPasses != null) PASSES = opts.blurPasses;
    if (opts.center != null) CENTER = opts.center;
    const fonts = opts.fonts || ["Helvetica", "Arial", "DejaVu Sans", "Liberation Sans", "sans-serif"];
    const classes = opts.classes || DEFAULT_CLASSES;

    // bitmap (BIG x BIG canvas, ink in alpha) -> normalized, blurred, unit-length vector
    function normalize(src) {
      const ctx = src.getContext("2d");
      const d = ctx.getImageData(0, 0, BIG, BIG).data;
      let x0 = BIG, y0 = BIG, x1 = -1, y1 = -1;
      for (let y = 0; y < BIG; y++) for (let x = 0; x < BIG; x++) if (d[(y * BIG + x) * 4 + 3] > 40) {
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
      if (x1 < 0) return null;
      const w = x1 - x0 + 1, h = y1 - y0 + 1, inner = N - 2 * PAD, s = inner / Math.max(w, h);
      const dst = makeCanvas(N, N), dc = dst.getContext("2d");
      dc.imageSmoothingEnabled = true;
      dc.drawImage(src, x0, y0, w, h, PAD + (inner - w * s) / 2, PAD + (inner - h * s) / 2, w * s, h * s);
      const px = dc.getImageData(0, 0, N, N).data, a = new Float32Array(N * N);
      for (let i = 0; i < N * N; i++) a[i] = px[i * 4 + 3] / 255;
      let b = a;
      for (let i = 0; i < PASSES; i++) b = boxBlur(b, 1);
      if (CENTER) { let m = 0; for (let i = 0; i < b.length; i++) m += b[i]; m /= b.length; b = b.map(v => v - m); }
      let n = 0;
      for (let i = 0; i < b.length; i++) n += b[i] * b[i];
      n = Math.sqrt(n) || 1;
      for (let i = 0; i < b.length; i++) b[i] /= n;
      return b;
    }

    function renderStrokes(strokes) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, n = 0;
      for (const s of strokes) for (const p of s) { n++; x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y); }
      if (!n) return null;
      const w = x1 - x0, h = y1 - y0, m = Math.max(w, h);
      if (m <= 0) return null;
      const sc = 96 / m, ox = (BIG - w * sc) / 2, oy = (BIG - h * sc) / 2;
      const cv = makeCanvas(BIG, BIG), c = cv.getContext("2d");
      c.strokeStyle = c.fillStyle = "#000"; c.lineWidth = STROKE_W; c.lineCap = c.lineJoin = "round";
      for (const s of strokes) {
        const P = s.map(p => [ox + (p.x - x0) * sc, oy + (p.y - y0) * sc]);
        if (P.length === 1) { c.beginPath(); c.arc(P[0][0], P[0][1], STROKE_W / 2, 0, 7); c.fill(); continue; }
        c.beginPath(); c.moveTo(P[0][0], P[0][1]); for (let i = 1; i < P.length; i++) c.lineTo(P[i][0], P[i][1]); c.stroke();
      }
      return cv;
    }

    const templates = [];   // {ch, vec}; each glyph also rendered with mild width/shear distortions
    const AUG = opts.augment === false ? [[1, 0]] : [[1, 0], [0.75, 0], [1.3, 0], [1, -0.15], [1, 0.15], [0.8, 0.15], [0.8, -0.15], [1.2, 0.15], [1.2, -0.15]];
    for (const ch of classes) for (const f of fonts) for (const [sx, sh] of AUG) {
      const cv = makeCanvas(BIG, BIG), c = cv.getContext("2d");
      c.fillStyle = "#000"; c.textBaseline = "alphabetic";
      c.font = `normal 84px "${f}", sans-serif`;
      c.setTransform(sx, 0, sh, 1, 0, 0);
      c.fillText(ch, 20, 100);
      const v = normalize(cv);
      if (v) templates.push({ ch, vec: v });
    }

    function recognize(strokes, k = 3) {
      const nPts = strokes.reduce((a, s) => a + s.length, 0);
      if (nPts < 6) return { error: "too_short" };
      const cv = renderStrokes(strokes);
      const v = cv && normalize(cv);
      if (!v) return { error: "too_short" };
      const best = new Map();
      for (const t of templates) {
        let s = 0; for (let i = 0; i < v.length; i++) s += v[i] * t.vec[i];
        if (!best.has(t.ch) || best.get(t.ch) < s) best.set(t.ch, s);
      }
      const ranked = [...best.entries()].sort((a, b) => b[1] - a[1]);
      const top = ranked.slice(0, k).map(([ch, score]) => ({ ch, score }));
      return { top, margin: ranked.length > 1 ? ranked[0][1] - ranked[1][1] : null, n_templates: templates.length };
    }
    return { recognize, templates: templates.length, classes };
  }
  return { create, DEFAULT_CLASSES };
});
