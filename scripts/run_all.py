"""Run every registered generator (scripts/generators.json) over inputs/pairs.json, one at a time.

Usage (Git Bash):  source scripts/env.sh && python scripts/run_all.py [--only slug,...] [--skip slug,...]

Pairs that already have an output are skipped by run_pairs.py, so this is safe to re-run after
extending the pairs or after an interruption. Per-pair logs go to
repos/<name>/_agent/logs/<slug>/; a JSON summary per generator is printed and appended to
dataset/run_all.log.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def expand(entry):
    """One registry entry -> one or more concrete generators (entries with "models" fan out)."""
    for model in entry.get("models", [None]):
        sub = lambda s: s.replace("{model}", model) if model else s
        yield {
            "slug": sub(entry["slug"]),
            "repo": entry["repo"],
            "ext": entry["ext"],
            "timeout": entry["timeout"],
            "path_prepend": entry.get("path_prepend", []),
            "settings": json.loads(sub(json.dumps(entry["settings"]))),
            "cmd": sub(entry["cmd"]),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--pairs", default="inputs/pairs.json")
    args = ap.parse_args()
    only = set(filter(None, args.only.split(",")))
    skip = set(filter(None, args.skip.split(",")))

    registry = json.loads((ROOT / "scripts" / "generators.json").read_text(encoding="utf-8"))
    gens = [g for e in registry["generators"] for g in expand(e)
            if (not only or g["slug"] in only) and g["slug"] not in skip]

    failed = []
    for g in gens:
        t0 = time.time()
        cmd = [sys.executable, str(ROOT / "scripts" / "run_pairs.py"),
               "--generator", g["slug"], "--repo", g["repo"], "--ext", g["ext"], "--pairs", args.pairs,
               "--timeout", str(g["timeout"]), "--settings", json.dumps(g["settings"]),
               "--log-dir", f"_agent/logs/{g['slug']}", "--cmd", g["cmd"]]
        for p in g["path_prepend"]:
            cmd += ["--path-prepend", p]
        print(f"=== {g['slug']}", flush=True)
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        summary_line = (proc.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            summary = json.loads(summary_line)
        except json.JSONDecodeError:
            summary = {"generator": g["slug"], "error": (proc.stderr or proc.stdout)[-500:]}
        summary["minutes"] = round((time.time() - t0) / 60, 1)
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(summary), flush=True)
        with open(ROOT / "dataset" / "run_all.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
        if proc.returncode != 0:
            failed.append(g["slug"])

    print(f"done; failed: {failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
