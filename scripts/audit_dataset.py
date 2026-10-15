"""Audit dataset/manifest.jsonl against files on disk and the pairs files.

Usage: python scripts/audit_dataset.py
"""
import hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = [json.loads(l) for l in (ROOT / "dataset/manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
pairs = {}
for pf in ("inputs/pairs.json", "inputs/pairs_p3.json"):
    for p in json.loads((ROOT / pf).read_text(encoding="utf-8"))["pairs"]:
        pairs[p["pair_id"]] = p

problems = []
ok = defaultdict(set)
for r in rows:
    if r.get("label") != "fake" or r.get("status") != "ok":
        continue
    f = ROOT / r["file"]
    if not f.exists():
        problems.append(f"missing file {r['file']}"); continue
    if hashlib.sha256(f.read_bytes()).hexdigest() != r["sha256"]:
        problems.append(f"sha mismatch {r['file']}")
    rc = r.get("real_counterpart")
    if rc and not (ROOT / rc).exists():
        problems.append(f"missing real counterpart {rc} for {r['file']}")
    ok[r["generator"]].add(r["pair_id"])

on_disk = {str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "dataset/fake").rglob("*") if p.is_file()}
listed = {r["file"].replace("\\", "/") for r in rows if r.get("label") == "fake" and r.get("status") == "ok"}
orphans = on_disk - listed
for o in sorted(orphans):
    problems.append(f"orphan (on disk, not in manifest) {o}")

gens = sorted({g for g in ok})
print(f"{'generator':40} {'p':>4} {'q':>4}")
for g in gens:
    c = Counter(pid[0] for pid in ok[g])
    print(f"{g:40} {c['p']:>4} {c['q']:>4}")
print(f"\npairs defined: {Counter(k[0] for k in pairs)}  ok fakes: {sum(len(v) for v in ok.values())}")
missing = {g: sorted(set(pairs) - ok[g]) for g in gens if set(pairs) - ok[g]}
for g, m in missing.items():
    print(f"  {g}: {len(m)} pairs without ok fake ({m[:5]}...)")
print(f"\n{len(problems)} problems")
for p in problems[:30]:
    print(" ", p)
sys.exit(1 if problems else 0)
