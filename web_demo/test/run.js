const { createCanvas } = require("canvas");
const GR = require("../recognizer.js");
const samples = require("./samples.json");
const rec = GR.create({ makeCanvas: (w, h) => createCanvas(w, h), fonts: ["DejaVu Sans", "Liberation Sans"] });
let t1 = 0, t3 = 0; const conf = {}; const byFont = {};
for (const s of samples) {
  // each skeleton pixel becomes its own one-point stroke (unordered), rendered as dots
  const r = rec.recognize(s.points.map(p => [{ x: p[0], y: p[1] }]), 3);
  const top = r.top.map(x => x.ch);
  const ok1 = top[0] === s.ch, ok3 = top.includes(s.ch);
  t1 += ok1; t3 += ok3;
  byFont[s.font] = byFont[s.font] || [0, 0]; byFont[s.font][0] += ok1; byFont[s.font][1]++;
  if (!ok1) { const k = s.ch + "->" + top[0]; conf[k] = (conf[k] || 0) + 1; }
}
console.log(`templates: ${rec.templates} (${rec.classes.length} classes x 2 fonts)`);
console.log(`synthetic top-1 ${(100 * t1 / samples.length).toFixed(1)}%  top-3 ${(100 * t3 / samples.length).toFixed(1)}%  n=${samples.length}`);
for (const [f, [a, b]] of Object.entries(byFont)) console.log(`  ${f}: ${(100 * a / b).toFixed(1)}% (${b})`);
console.log("most common errors:", Object.entries(conf).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => `${k}(${v})`).join(" "));
