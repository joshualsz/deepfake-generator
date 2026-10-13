"""Build source->target face pairs from inputs/faces/manifest.json.

Usage: python scripts/make_pairs.py [--count 10] [--seed 0] [--faces inputs/faces] [--out inputs/pairs.json]

Pairs never reuse a face as both source and target of the same pair. Every generator uses
the same pairs file so outputs are directly comparable across generators.

--count is the TOTAL wanted. If --out exists, its pairs are kept unchanged and new pairs are built
only from faces not used in any existing pair (ids continue: p010, p011, ...).
"""
import argparse
import json
import random
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--count", type=int, default=10)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--faces", default="inputs/faces")
ap.add_argument("--out", default="inputs/pairs.json")
ap.add_argument("--prefix", default="p", help="pair_id prefix; use a distinct one per pairs file (outputs are named by pair_id)")
args = ap.parse_args()

faces = json.loads((Path(args.faces) / "manifest.json").read_text(encoding="utf-8"))["images"]
out = Path(args.out)
existing = json.loads(out.read_text(encoding="utf-8"))["pairs"] if out.exists() else []
used = {p["source_id"] for p in existing} | {p["target_id"] for p in existing}
free = [f for f in faces if f["id"] not in used]
need = args.count - len(existing)
if need <= 0:
    raise SystemExit(f"already have {len(existing)} pairs")
if len(free) < 2 * need:
    raise SystemExit(f"need {2 * need} unused faces, have {len(free)}; fetch more first")

shuffled = random.Random(f"{args.seed}-{len(existing)}" if existing else args.seed).sample(free, 2 * need)
new = [
    {
        "pair_id": f"{args.prefix}{i:03d}",
        "source": str(Path(args.faces) / src["file"]),  # identity to paste in
        "target": str(Path(args.faces) / tgt["file"]),  # image whose face gets replaced
        "source_id": src["id"],
        "target_id": tgt["id"],
    }
    for i, (src, tgt) in enumerate(zip(shuffled[:need], shuffled[need:]), start=len(existing))
]
pairs = existing + new
out.write_text(json.dumps({"seed": args.seed, "pairs": pairs}, indent=2), encoding="utf-8")
print(f"wrote {len(pairs)} pairs to {args.out} ({len(new)} new)")
