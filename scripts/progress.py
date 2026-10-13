"""Show per-generator progress over inputs/pairs.json, read live from dataset/manifest.jsonl.

Usage: python scripts/progress.py          (one snapshot)
       python scripts/progress.py --watch  (refresh every 10 s, Ctrl+C to stop)
       add --pairs=inputs/pairs_p3.json for another pairs file
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from run_all import expand  # noqa: E402

WIDTH = 30


def snapshot() -> str:
    pairs_file = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--pairs=")), "inputs/pairs.json")
    pair_ids = {p["pair_id"] for p in json.loads((ROOT / pairs_file).read_text(encoding="utf-8"))["pairs"]}
    total = len(pair_ids)
    registry = json.loads((ROOT / "scripts" / "generators.json").read_text(encoding="utf-8"))
    slugs = [g["slug"] for e in registry["generators"] for g in expand(e)]

    latest = {}
    for line in open(ROOT / "dataset" / "manifest.jsonl", encoding="utf-8"):
        r = json.loads(line)
        latest[(r["generator"], r["pair_id"])] = r["status"]

    lines, done_all = [], 0
    for s in slugs:
        statuses = [v for (g, p), v in latest.items() if g == s and p in pair_ids]
        ok = sum(v == "ok" for v in statuses)
        bad = len(statuses) - ok
        done_all += ok
        filled = int(WIDTH * ok / total)
        bar = "#" * filled + "-" * (WIDTH - filled)
        flag = "  done" if ok == total else (f"  {bad} failed/noop" if bad else "")
        lines.append(f"{s:36s} [{bar}] {ok:3d}/{total}{flag}")
    grand = total * len(slugs)
    lines.append(f"\nTOTAL {done_all}/{grand} images ({100 * done_all / grand:.0f}%)")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        try:
            while True:
                print("\033[2J\033[H" + time.strftime("%H:%M:%S") + "\n" + snapshot(), flush=True)
                time.sleep(10)
        except KeyboardInterrupt:
            pass
    else:
        print(snapshot())
