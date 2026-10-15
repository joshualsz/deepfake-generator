"""Write dataset/splits.json: train/val/test assignment for every usable fake and real image.

Split unit is the pair_id, so every generator's output for a pair, and the pair's real target,
land in the same split (no near-duplicate leakage across splits). Face ids shared between
pairs can still cross splits; faces are synthetic, so identity leakage is not a privacy issue,
but it is noted in `notes`.

Two generators are also held out entirely ("heldout_generators") for leave-generator-out
evaluation: do not train on them.

Usage: python scripts/make_splits.py [--seed 0]
"""
import argparse, json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELDOUT = ["facefusion-uniface_256", "faceswap-dlib-3d"]  # one GAN-family model, one classical method

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=0)
args = ap.parse_args()

rows = [json.loads(l) for l in (ROOT / "dataset/manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
fakes = [r for r in rows if r.get("label") == "fake" and r.get("status") == "ok"
         and "quarantine" not in r["file"]]
pair_ids = sorted({r["pair_id"] for r in fakes})
rng = random.Random(args.seed)
rng.shuffle(pair_ids)
n = len(pair_ids)
cut = {"train": int(n * 0.7), "val": int(n * 0.85)}
split_of = {pid: ("train" if i < cut["train"] else "val" if i < cut["val"] else "test")
            for i, pid in enumerate(pair_ids)}

out = {"seed": args.seed, "heldout_generators": HELDOUT,
       "notes": "split by pair_id; reals are the pair targets; face ids may repeat across pairs",
       "train": {"fake": [], "real": []}, "val": {"fake": [], "real": []}, "test": {"fake": [], "real": []}}
reals_seen = {}
for r in fakes:
    s = split_of[r["pair_id"]]
    out[s]["fake"].append({"file": r["file"], "generator": r["generator"], "pair_id": r["pair_id"]})
    rc = r.get("real_counterpart")
    if rc:
        # a real image used by pairs in several splits goes to the earliest-priority one: test > val > train,
        # so held-out splits never contain an image that is also in train
        prio = {"train": 0, "val": 1, "test": 2}
        if rc not in reals_seen or prio[s] > prio[reals_seen[rc]]:
            reals_seen[rc] = s
for rc, s in sorted(reals_seen.items()):
    out[s]["real"].append(rc)

(ROOT / "dataset/splits.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
for s in ("train", "val", "test"):
    gens = {f["generator"] for f in out[s]["fake"]}
    print(f"{s:5} fake={len(out[s]['fake']):5} real={len(out[s]['real']):3} pairs={sum(1 for v in split_of.values() if v==s)}")
