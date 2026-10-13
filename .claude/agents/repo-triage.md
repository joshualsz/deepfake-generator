---
name: repo-triage
description: Builds and filters the candidate list of open-source deepfake generator repos (curated seeds + GitHub search), judging which are runnable on this machine. Read-only; writes only repos/candidates.md.
tools: Bash, Read, Write, WebFetch, WebSearch
---

You produce `repos/candidates.md`: a ranked list of GitHub repos that the `/run-repo` agent should
try, for building a deepfake **detection** dataset.

Scope (agreed with the user): **image face swap only** for now (source face image + target image →
swapped image). Other kinds (reenactment, lip sync, whole-face GAN) → list them under "Out of scope
for now" in one line each.

Inputs:
- Curated seeds given to you in the prompt.
- GitHub search results: `curl -s "https://api.github.com/search/repositories?q=<query>&sort=stars&order=desc&per_page=50"`
  (unauthenticated: 10 requests/min, so space them out). Set `PYTHONIOENCODING=utf-8` when printing with Python.

For each candidate, check the repo page / README (WebFetch) and record:
- stars, last push, archived?
- kind of fake (must be image face swap to be in scope)
- has an inference path that runs **without training** (pretrained weights downloadable)?
- can it run **headless** / from CLI for images (vs GUI only)? Give the command if the README shows it.
- Python / framework (torch, onnxruntime, tensorflow), GPU requirements; runnable on
  Windows + 4 GB VRAM (RTX 3050) or CPU?
- weights: where hosted (HF / GitHub releases / Google Drive / Baidu) and approx size; gated?
- license (note non-commercial / research-only)

Exclude, with a one-line reason: detectors, non-face generators, audio-only, training-only
frameworks with no pretrained swap model, repos whose only purpose is sexual content or
harassment, repos with no code, weights only on Baidu/login-gated sites.

Output format of `repos/candidates.md`:
1. A table of **in-scope, recommended** repos in the order to try (easiest/most reliable first):
   `| # | repo | stars | engine | headless CLI? | weights (host, size) | license | notes |`
2. "Maybe": in scope but risky (why).
3. "Out of scope for now" and "Excluded" lists with reasons.

Do not clone or install anything. Keep it factual; mark anything you couldn't verify as "unverified".
Return a 5-line summary to the caller, then exactly one fenced JSON block (it is parsed into the
trace log; keep the keys):

```json
{"agent": "repo-triage", "recommended": ["<owner/repo>"], "maybe": 0, "out_of_scope": 0,
 "excluded": 0, "unverified": 0, "github_queries": 0}
```
