"""Make format-matched copies of the audio dataset so a detector can't tell real from fake by file format.

Real VCTK clips are 48 kHz FLAC; CosyVoice output is 22.05 kHz WAV. This writes every usable clip
(latest 'ok' row per pair + its real counterpart) as 16 kHz mono 16-bit PCM WAV to
dataset_audio/normalized/{real,fake/<generator>}/ using ffmpeg. Originals are untouched.

Usage (Git Bash, after `source scripts/env.sh`): python scripts/normalize_audio.py [--rate 16000]
"""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--rate", type=int, default=16000)
args = ap.parse_args()

latest = {}
for line in open(ROOT / "dataset_audio" / "manifest.jsonl", encoding="utf-8"):
    r = json.loads(line)
    latest[(r["generator"], r["pair_id"])] = r
jobs = set()
for r in latest.values():
    if r["status"] == "ok":
        jobs.add((r["file"], f"fake/{r['generator']}/{Path(r['file']).stem}.wav"))
        jobs.add((r["real_counterpart"], f"real/{Path(r['real_counterpart']).stem}.wav"))
out_root = ROOT / "dataset_audio" / "normalized"
for src, rel in sorted(jobs):
    dst = out_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ROOT / src),
                    "-ac", "1", "-ar", str(args.rate), "-sample_fmt", "s16", str(dst)], check=True)
print(f"wrote {len(jobs)} files to {out_root} ({args.rate} Hz mono s16 wav)")
