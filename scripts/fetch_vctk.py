"""Fetch a small, reproducible VCTK sample (consented research speech, CC BY 4.0) for the audio dataset.

Source: VCTK 0.92 (https://datashare.ed.ac.uk/handle/10283/3443) via the HF mirror sanchit-gandhi/vctk,
read row-by-row through the HF datasets-server API, so only the chosen clips are downloaded.
Only mic1 recordings are used.

Usage: python scripts/fetch_vctk.py [--speakers 10] [--per-speaker 6] [--out inputs/voices]

For each speaker: 1 reference clip (the voice prompt CosyVoice clones from) + (per-speaker - 1) target
sentences. Writes <out>/<speaker>/<file>.flac, <out>/manifest.json and inputs/audio_pairs.json
(pair_id a000.., one pair per target sentence: clone <speaker> from its reference, saying the target text;
the real recording of that target sentence is the matching "real" clip).
"""
import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://datasets-server.huggingface.co/rows?dataset=sanchit-gandhi/vctk&config=default&split=train"
TOTAL_ROWS = 88156


def get_rows(offset: int, length: int = 100) -> list[dict]:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(f"{API}&offset={offset}&length={length}", timeout=60) as r:
                return [x["row"] for x in json.load(r)["rows"]]
        except Exception as e:  # datasets-server is occasionally slow / 5xx
            print(f"  retry {attempt + 1} for offset {offset}: {e}")
            time.sleep(5)
    raise SystemExit(f"could not fetch rows at offset {offset}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speakers", type=int, default=10)
    ap.add_argument("--per-speaker", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="inputs/voices")
    ap.add_argument("--pairs-out", default="inputs/audio_pairs.json")
    args = ap.parse_args()

    out = Path(args.out)
    rng = random.Random(args.seed)
    speakers, pairs = [], []
    step = TOTAL_ROWS // args.speakers
    for k in range(args.speakers):
        offset = k * step + step // 2  # land mid-speaker block
        rows = [r for r in get_rows(offset) if r["file"].endswith("_mic1.flac")]
        spk = max({r["speaker_id"] for r in rows}, key=lambda s: sum(r["speaker_id"] == s for r in rows))
        rows = [r for r in rows if r["speaker_id"] == spk and r["text"].strip()]
        # reference prompt: a mid-length sentence (8-16 words) gives CosyVoice ~3-6 s of voice
        ref_candidates = [r for r in rows if 8 <= len(r["text"].split()) <= 16] or rows
        ref = rng.choice(ref_candidates)
        targets = rng.sample([r for r in rows if r is not ref], args.per_speaker - 1)

        meta = {k2: rows[0][k2] for k2 in ("speaker_id", "gender", "age", "accent", "region")}
        clips = []
        for r in [ref] + targets:
            name = Path(r["file"]).name
            dest = out / spk / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(r["audio"][0]["src"], dest)
            clips.append({"file": str(dest).replace("\\", "/"), "text": r["text"].strip(), "text_id": r["text_id"],
                          "role": "reference" if r is ref else "target"})
        speakers.append({**meta, "clips": clips})
        print(f"{spk} {meta['gender']} {meta['age']} {meta['accent']}: {len(clips)} clips")

        ref_clip = clips[0]
        for c in clips[1:]:
            pairs.append({
                "pair_id": f"a{len(pairs):03d}",
                "speaker_id": spk,
                "prompt_wav": ref_clip["file"],
                "prompt_text": ref_clip["text"],
                "target_text": c["text"],
                "real_wav": c["file"],
                "target_id": Path(c["file"]).stem,
            })

    (out / "manifest.json").write_text(json.dumps({
        "source": "VCTK Corpus 0.92 (CSTR, University of Edinburgh) - speakers consented to research use",
        "source_url": "https://datashare.ed.ac.uk/handle/10283/3443",
        "license": "CC BY 4.0 (attribution: Yamagishi, Veaux, MacDonald, CSTR VCTK Corpus 0.92)",
        "mirror": "https://huggingface.co/datasets/sanchit-gandhi/vctk (via datasets-server rows API)",
        "mic": "mic1",
        "seed": args.seed,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "speakers": speakers,
    }, indent=2), encoding="utf-8")
    Path(args.pairs_out).write_text(json.dumps({"seed": args.seed, "pairs": pairs}, indent=2), encoding="utf-8")
    print(f"{len(speakers)} speakers, {len(pairs)} pairs -> {args.pairs_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
