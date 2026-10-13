"""Run one generator over every pair and record results in dataset/manifest.jsonl.

Usage:
    python scripts/run_pairs.py --generator deep-live-cam --repo repos/Deep-Live-Cam \
        --cmd "{python} run.py -s {source} -t {target} -o {output} --execution-provider cuda" \
        [--pairs inputs/pairs.json] [--ext .png] [--timeout 300] [--settings '{"provider": "cuda"}'] [--limit N]         [--path-prepend ".venv/Lib/site-packages/nvidia/*/bin" --path-prepend "<ffmpeg bin dir>"]

Placeholders in --cmd: {python} (repo venv python), {source}, {target}, {output} — all absolute, already quoted.
The command runs with cwd = repo. Outputs go to dataset/fake/<generator>/<pair_id><ext>.
Targets are copied once to dataset/real/<target_id>.<ext> (the un-swapped counterpart).
Re-running skips pairs whose output already exists (use --force to redo).
Outputs that are (nearly) identical to the target are rejected as "noop" and deleted: many swappers
silently return the target unchanged when no face is detected.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def diff_from_target(out: Path, target: Path) -> float:
    """Mean absolute pixel difference (0-255) between output and target, on the target's size."""
    t = Image.open(target).convert("RGB")
    o = Image.open(out).convert("RGB").resize(t.size)
    return float(np.abs(np.asarray(o, dtype=np.int16) - np.asarray(t, dtype=np.int16)).mean())


def git_commit(repo: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generator", required=True, help="short slug, e.g. deep-live-cam")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--cmd", required=True)
    ap.add_argument("--pairs", default="inputs/pairs.json")
    ap.add_argument("--ext", default=".png")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--settings", default="{}", help="JSON of generator settings to record")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--log-dir", default="_agent/generate_logs", help="per-pair logs, relative to repo")
    ap.add_argument("--path-prepend", action="append", default=[],
                    help="dir (or glob, relative to repo) to put on PATH for the command; repeatable")
    ap.add_argument("--noop-threshold", type=float, default=0.5,
                    help="mean abs diff vs target below which an output counts as unchanged")
    args = ap.parse_args()

    repo = (ROOT / args.repo).resolve()
    python = repo / ".venv" / "Scripts" / "python.exe"
    pairs = json.loads((ROOT / args.pairs).read_text(encoding="utf-8"))["pairs"][: args.limit]
    settings = json.loads(args.settings)
    commit = git_commit(repo)
    extra = [d for pat in args.path_prepend
             for d in sorted(glob.glob(pat if os.path.isabs(pat) else str(repo / pat)))]
    env = {**os.environ, "PATH": os.pathsep.join(extra + [os.environ.get("PATH", "")])}

    fake_dir = DATASET / "fake" / args.generator
    real_dir = DATASET / "real"
    log_dir = repo / args.log_dir
    for d in (fake_dir, real_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    ok = fail = skipped = 0
    with open(DATASET / "manifest.jsonl", "a", encoding="utf-8") as manifest:
        for p in pairs:
            src, tgt = (ROOT / p["source"]).resolve(), (ROOT / p["target"]).resolve()
            out = fake_dir / f"{p['pair_id']}{args.ext}"
            real = real_dir / f"{p['target_id']}{tgt.suffix}"
            if not real.exists():
                shutil.copy2(tgt, real)
            if out.exists() and not args.force:
                skipped += 1
                continue

            q = lambda x: f'"{x}"'  # Windows: pass one command string, quote each path
            cmd = args.cmd.format(python=q(python), source=q(src), target=q(tgt), output=q(out))
            t0 = time.time()
            with open(log_dir / f"{p['pair_id']}.log", "w", encoding="utf-8", errors="replace") as log:
                try:
                    rc = subprocess.run(cmd, cwd=repo, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=args.timeout).returncode
                except subprocess.TimeoutExpired:
                    rc = "timeout"
            seconds = round(time.time() - t0, 1)
            success = rc == 0 and out.exists() and out.stat().st_size > 0
            diff = round(diff_from_target(out, tgt), 2) if success else None
            status = "ok" if success else f"failed(rc={rc})"
            if success and diff < args.noop_threshold:
                success, status = False, f"noop(diff={diff})"
                out.unlink()
            ok += success
            fail += not success

            record = {
                "label": "fake",
                "generator": args.generator,
                "repo_commit": commit,
                "pair_id": p["pair_id"],
                "source_id": p["source_id"],
                "target_id": p["target_id"],
                "file": str(out.relative_to(ROOT)).replace("\\", "/") if success else None,
                "sha256": sha256(out) if success else None,
                "real_counterpart": str(real.relative_to(ROOT)).replace("\\", "/"),
                "settings": settings,
                "status": status,
                "diff_from_target": diff,
                "seconds": seconds,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest.write(json.dumps(record) + "\n")
            manifest.flush()
            print(f"{p['pair_id']}: {record['status']} in {seconds}s")

    print(json.dumps({"generator": args.generator, "ok": ok, "failed": fail, "skipped": skipped}))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
