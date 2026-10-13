"""Build a target|output contact sheet for one generator from dataset/manifest.jsonl.

Usage: python scripts/contact_sheet.py <generator> [--out path.jpg] [--tile 160]
Rows: one per successful pair (latest attempt), two pairs per row: target, output, target, output.
"""
import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("generator")
ap.add_argument("--out")
ap.add_argument("--tile", type=int, default=160)
args = ap.parse_args()

latest = {}
for line in open(ROOT / "dataset" / "manifest.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["generator"] == args.generator:
        latest[r["pair_id"]] = r
rows = [r for _, r in sorted(latest.items()) if r["status"] == "ok"]
if not rows:
    raise SystemExit(f"no ok outputs for {args.generator}")

t = args.tile
tiles = []
for r in rows:
    for p in (r["real_counterpart"], r["file"]):
        tiles.append(Image.open(ROOT / p).convert("RGB").resize((t, t)))
cols = 4
sheet = Image.new("RGB", (t * cols, t * ((len(tiles) + cols - 1) // cols)), "white")
for i, im in enumerate(tiles):
    sheet.paste(im, ((i % cols) * t, (i // cols) * t))
out = Path(args.out) if args.out else ROOT / "dataset" / "sheets" / f"{args.generator}.jpg"
out.parent.mkdir(parents=True, exist_ok=True)
sheet.save(out, quality=90)
print(out)
