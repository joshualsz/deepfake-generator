---
name: collect-dataset
description: Build a deepfake-detection dataset by spinning up each open-source face-swap generator (from repos/candidates.md) in its own venv and running it over a fixed set of synthetic face pairs. Use when the user says "/collect-dataset" or asks to collect data from the generators.
---

# collect-dataset — run every generator over the same synthetic pairs

Goal (agreed with the user): fake media for a **deepfake detection dataset**. First pass covers
**image face swap only**, **synthetic faces only** (SFHQ), about **10 pairs per generator**.

Arguments (`$ARGUMENTS`, all optional): `--count N` (pairs, default 10), `--only <repo>`,
`--skip <repo,...>`.

## Hard rules
- Inputs are **only** synthetic faces from `inputs/faces/` (SFHQ, fetched by `scripts/fetch_synthetic_faces.py`).
  Never use photos of real people, never scrape faces, never accept a repo's own sample
  images of real people as source or target. If the user wants other inputs, they must be licensed
  research data or consenting participants that they supply; ask first.
- All the `/run-repo` rules apply (venv per repo via uv, no conda, only ffmpeg/uv system installs,
  build C extensions from source with MSVC, no third-party wheels outside PyPI/official indexes,
  ask before any single download > 2 GB).
- One generator at a time: the 4 GB GPU can't run two.

## Steps

0. **Shell setup.** In Git Bash, run `source scripts/env.sh` first (it puts uv and ffmpeg on PATH and sets UV_LINK_MODE=copy).
1. **Inputs.** Both scripts **extend** and never replace: `--count` is the total wanted, and existing faces and pairs keep
   their ids, so existing outputs stay valid. Run `python scripts/fetch_synthetic_faces.py --count <2×count>`, then
   `python scripts/make_pairs.py --count <count>`. Never delete or reshuffle `inputs/pairs.json`.
   `run_pairs.py` skips any pair_id that already has an output, so a changed pair would silently keep a stale image.
2. **Scaling up / re-running known generators.** Every verified generator is in `scripts/generators.json`.
   `python scripts/run_all.py [--only a,b] [--skip c]` runs them all sequentially over all pairs, skipping
   existing outputs, and writes a summary line per generator to `dataset/run_all.log`. After it finishes,
   check the noop and failed counts, rebuild the contact sheets for the new pairs, and spot-check them.
3. **Candidates.** If `repos/candidates.md` is missing, delegate to the `repo-triage` subagent.
   Show the user the recommended list and get a go-ahead before the first run of a new list.
4. **Per new generator**, in the order of the recommended table, skipping those with PASS in `repos/RESULTS.md`
   that already have outputs in `dataset/fake/<slug>/`:
   a. Follow the `/run-repo` skill steps 1–7 (clone, plan, venv, install, models, launch check, fixes).
   b. **Generate.** Work out the repo's headless single-image command from its README/CLI help
      (`--help`). Smoke-test it on **one** pair with
      `python scripts/run_pairs.py --generator <slug> --repo repos/<name> --cmd "<template>" --limit 1 --settings '<json>'`.
      Look at the output image (Read tool). It must be a plausible swap, not a copy of the target, blank,
      or an error image. Then run all pairs (same command without `--limit`).
      - `run_pairs.py` rejects outputs nearly identical to the target as `noop`. Swappers often do this
        when the face detector misses the face. The SFHQ faces are large close-ups (1024px), so try a
        smaller detector input size first (Deep-Live-Cam needed `--det-size 320`).
      - Pass `--path-prepend` for anything the run needs on PATH (venv `nvidia/*/bin` DLLs, ffmpeg).
      - Confirm the GPU provider was actually used by grepping `repos/<name>/_agent/generate_logs/*.log`.
      - After the full run, build a contact sheet (`python scripts/contact_sheet.py <slug>`) and look at it.
      - **Check for watermarks/logos** (zoom into corners of one full-resolution output). Some tools
        stamp outputs on purpose (simswap-inference-pytorch's `blend_module.jit` adds "Deepfake"
        bottom-right). A watermark is a shortcut a detector would learn. **Never strip, crop, or bypass an
        intentional watermark on your own.** Move the outputs to `dataset/quarantine/<slug>-watermarked/`,
        mark their manifest rows `excluded(watermark)`, and record the repo as EXCLUDED in `repos/RESULTS.md`.
        Standing decision (user, 2026-10-06): watermarked generators are excluded. Don't ask again; just report it.
        Check the source for watermark code (grep `watermark|logo`) **before** downloading weights, and skip if found.
        A documented, author-provided off-switch (e.g. a CLI flag) is still the user's call.
      Record the exact template and settings (model, provider, enhancer on/off) in `_agent/plan.md`.
      If the repo has no headless mode, write a small wrapper script in `repos/<name>/_agent/` that
      imports the repo's own modules to do one swap. Don't modify the repo's files.
   c. Failures → `repo-fixer` (3 rounds max per step), then mark FAIL and move on to the next repo.
   d. Update `repos/<name>/_agent/report.md` and the `repos/RESULTS.md` row (add `outputs ok/total`).
   e. **Register it.** Add the verified generator (slug, repo, ext, timeout, path_prepend, settings, cmd) to
      `scripts/generators.json` so `run_all.py` covers it in future scale-ups.
5. **Summary.** Run `python scripts/build_dataset_readme.py` to regenerate `dataset/README.md` (layout, counts per generator,
   input provenance (copy the faces manifest header), generator versions (commits), and the caveat that
   the "real" class consists of synthetic SFHQ faces. Then tell the user the per-generator results briefly.

## Dataset layout
```
dataset/
  real/<target_id>.jpg            # un-swapped targets (synthetic SFHQ faces)
  fake/<generator>/<pair_id>.png  # swapped outputs
  manifest.jsonl                  # one row per attempt: generator, commit, pair, settings, sha256, status, time
  README.md
```
