"""Synthetic sanity samples: skeletons of characters rendered in fonts that are NOT used as templates,
then distorted (rotation, anisotropic scale, shear, jitter). This is NOT human data and NOT an accuracy claim."""
import json, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.morphology import skeletonize

FONTS = {"DejaVu Serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
         "DejaVu Sans Mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "Liberation Serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"}
CLASSES = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
rng = random.Random(7)
out = []
for fname, path in FONTS.items():
    try:
        font = ImageFont.truetype(path, 180)
    except OSError:
        continue
    for ch in CLASSES:
        im = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(im).text((60, 40), ch, fill=255, font=font)
        sk = skeletonize(np.array(im) > 128)
        ys, xs = np.nonzero(sk)
        base = np.column_stack([xs, ys]).astype(float)
        if len(base) < 10: continue
        base -= base.mean(0)
        for rep in range(3):
            a = math.radians(rng.uniform(-8, 8)); sx, sy = rng.uniform(.85, 1.15), rng.uniform(.85, 1.15); sh = rng.uniform(-.12, .12)
            R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            p = base * [sx, sy]; p[:, 0] += sh * p[:, 1]; p = p @ R.T
            p += np.random.RandomState(rng.randint(0, 9999)).normal(0, 2.5, p.shape)
            out.append({"font": fname, "ch": ch, "points": p.round(1).tolist()})
json.dump(out, open("test/samples.json", "w"))
print(len(out), "samples")
