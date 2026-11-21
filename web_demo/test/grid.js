const { createCanvas } = require("canvas"); const GR = require("../recognizer.js"); const samples = require("./samples.json");
for (const sw of [5,7,9]) for (const bp of [1,2]) for (const c of [false,true]) {
  const rec = GR.create({ makeCanvas:(w,h)=>createCanvas(w,h), fonts:["DejaVu Sans","Liberation Sans"], strokeWidth:sw, blurPasses:bp, center:c });
  let t1=0,t3=0; for (const s of samples){const r=rec.recognize(s.points.map(p=>[{x:p[0],y:p[1]}]),3);const top=r.top.map(x=>x.ch);t1+=top[0]===s.ch;t3+=top.includes(s.ch)}
  console.log(`stroke ${sw} blur ${bp} center ${c}: top1 ${(100*t1/samples.length).toFixed(1)} top3 ${(100*t3/samples.length).toFixed(1)}`);
}
