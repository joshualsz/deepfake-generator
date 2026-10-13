"""Fetch a small, reproducible sample of synthetic faces (SFHQ) without downloading the full zip.

SFHQ (https://github.com/SelfishGene/SFHQ-dataset, MIT) is mirrored on HuggingFace as large zips.
We read the zip's central directory and only the chosen members via HTTP Range requests.

Usage:
    python scripts/fetch_synthetic_faces.py --count 20 [--seed 0] [--part 1] [--out inputs/faces]

--count is the TOTAL wanted. If <out>/manifest.json exists, its faces are kept (same ids/files)
and only the missing ones are added, so existing pairs and outputs stay valid.

Writes <out>/<id>.jpg and <out>/manifest.json (provenance for every image).
"""
import argparse
import io
import json
import random
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = "bitmind/SyntheticFacesHQ"
URL = "https://huggingface.co/datasets/{repo}/resolve/main/SFHQ-part{part}.zip"
IMAGE_EXT = (".jpg", ".jpeg", ".png")


class HttpRangeFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP Range requests (enough for zipfile)."""

    def __init__(self, url: str):
        self.url = url
        self.pos = 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as r:
            self.size = int(r.headers["Content-Length"])
            self.url = r.url  # follow redirect to the CDN once
        self.bytes_fetched = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        self.pos += len(data)
        self.bytes_fetched += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--part", type=int, default=1, choices=[1, 2, 3, 4])
    ap.add_argument("--out", default="inputs/faces")
    args = ap.parse_args()

    url = URL.format(repo=REPO, part=args.part)
    remote = HttpRangeFile(url)
    zf = zipfile.ZipFile(io.BufferedReader(remote, buffer_size=1 << 20))
    names = sorted(n for n in zf.namelist() if n.lower().endswith(IMAGE_EXT))
    print(f"{len(names)} images in SFHQ part {args.part} ({remote.size / 1e9:.1f} GB zip)")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    records = []
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old["part"] != args.part:
            raise SystemExit(f"existing faces are from part {old['part']}; use --part {old['part']}")
        records = old["images"]
    have = {r["zip_member"] for r in records}
    need = args.count - len(records)
    if need <= 0:
        print(f"already have {len(records)} faces")
        return 0
    rng = random.Random(f"{args.seed}-{len(records)}")  # new draw per extension, reproducible
    chosen = rng.sample([n for n in names if n not in have], need)
    for i, name in enumerate(chosen, start=len(records)):
        face_id = f"sfhq{args.part}_{i:04d}"
        dest = out / (face_id + Path(name).suffix.lower())
        dest.write_bytes(zf.read(name))
        records.append({"id": face_id, "file": dest.name, "zip_member": name})
        print(f"  {dest}")

    manifest = {
        "source": "SFHQ (Synthetic Faces High Quality) — all faces are synthetic, no real identities",
        "source_url": "https://github.com/SelfishGene/SFHQ-dataset",
        "license": "MIT (per SFHQ repo)",
        "mirror": url,
        "part": args.part,
        "seed": args.seed,
        "note": "faces are appended on extension; draw seed for each batch = '<seed>-<faces before batch>'",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "images": records,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"done; fetched {remote.bytes_fetched / 1e6:.1f} MB total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
