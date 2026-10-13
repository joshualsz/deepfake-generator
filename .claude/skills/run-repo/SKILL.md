---
name: run-repo
description: Given a GitHub repo URL (e.g. a deepfake generator), clone it, set up an isolated venv, install dependencies and models per its README, and launch the app to verify it starts. Use when the user says "/run-repo <url>" or asks to spin up / run a GitHub repo.
---

# run-repo — spin up one GitHub repo in its own venv

Input: a GitHub URL (`$ARGUMENTS`). You are the **orchestrator**: you plan and run the
steps yourself, and delegate to subagents when something breaks or needs verifying.

Project root: the current working directory. Helper scripts live in `scripts/`.

## Standing rules (agreed with the user)

- **Isolation:** everything for a repo lives in `repos/<name>/`; its venv is `repos/<name>/.venv`.
  Never `pip install` into the system Python. Never use conda.
- **Python version:** read the version the README / `pyproject.toml` / `setup.py` / `.python-version`
  asks for. Create the venv with `uv venv --python <ver> .venv` (uv downloads that Python if needed).
  If nothing is specified, use 3.10. Install packages with `uv pip install --python .venv ...`.
  **Always `export UV_LINK_MODE=copy`**, because the project is in OneDrive and uv's hardlinks fail there
  (os error 396) partway through an install. Check the install log for `error:` even when the tail looks fine.
- **System tools:** only `ffmpeg` and `uv` may be installed outside the venv, via
  `winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements` and
  `winget install --id astral-sh.uv -e ...`. After a winget install, the current shell's PATH is stale:
  locate the binary (e.g. under `%LOCALAPPDATA%\Microsoft\WinGet\Packages`) and prepend it to PATH
  for subsequent commands. Anything else system-level → stop and ask the user.
- **C/C++ builds:** the user installs Microsoft C++ Build Tools manually. Packages without Windows
  wheels (e.g. `insightface`) are built from source. Never use third-party prebuilt wheels from
  outside PyPI / official index URLs. If a build fails with "Microsoft Visual C++ 14.0 or greater
  is required", stop and ask the user to install or repair Build Tools.
- **Model downloads:** download any model files the README links to, into the location the README says.
  If a single download is > 2 GB, stop and ask first. Prefer `curl -L -o` and verify size > 0 afterward.
- **GPU:** RTX 3050 Laptop, 4 GB VRAM, driver CUDA 12.3, no CUDA toolkit. Try the GPU path first
  (e.g. `onnxruntime-gpu`, CUDA torch wheels via the README's index URL). If the launch fails with
  a CUDA/OOM/provider error, fall back to the CPU install/flags and note it in the report.
  - onnxruntime-gpu needs the CUDA/cuDNN DLLs. Never install cuDNN or CUDA system-wide. Install NVIDIA's
    PyPI wheels into the venv (`nvidia-cuda-runtime-cu12`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`,
    `nvidia-cufft-cu12`, `nvidia-curand-cu12`, `nvidia-cuda-nvrtc-cu12`, matching the CUDA/cuDNN major
    versions that onnxruntime build expects) and prepend `.venv/Lib/site-packages/nvidia/*/bin` to PATH
    when running. (torch CUDA wheels bundle their own DLLs.)
  - **torch:** other requirements (timm, facexlib, ...) pull in the `+cpu` torch from PyPI. After installing
    requirements, install torch last with `--no-deps --reinstall-package torch ... --index-url <pytorch cuXXX index>`
    (index only, no PyPI extra index, because uv prefers the first index that has the package) and verify
    `torch.version.cuda` / `torch.cuda.is_available()`. cu121 wheels run on this driver (CUDA 12.3).
    **Caveat:** Windows torch ≤2.3 depends on `mkl`, and `--no-deps` drops it (`shm.dll` WinError 126 on import).
    For those, install CUDA torch **first, with deps**: `--index-url <cu index> --extra-index-url https://pypi.org/simple
    --index-strategy unsafe-best-match`, then the other requirements (with torch removed from them).
- **Old sdists that import `pkg_resources`** (e.g. openai-whisper 20231117) fail with current setuptools. Install
  `"setuptools<70" wheel` into the venv and add `--no-build-isolation-package <pkg>`.
  - **ORT falls back to CPU with no error.** Always grep the run log for `Applied providers` /
    `Error loading ...providers_cuda.dll` to confirm which provider actually ran.
- **PATH is stale in this session** after winget installs. ffmpeg lives at
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin` and uv at
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*`. Prepend them explicitly.
- **Success = the app launches.** Stop the app after the check unless the user asks otherwise.
  Generating data is a separate step owned by `/collect-dataset`.
- **Never** run face swaps on real people's images. The only allowed inputs are the synthetic faces
  in `inputs/faces/` (see `/collect-dataset`).
- Don't edit the repo's own source code unless it's the only way to launch; if you do, record the diff in the report.

## Steps

1. **Prereqs.** `python scripts/check_prereqs.py`. Install missing `uv` / `ffmpeg` per the rules above if the repo needs them.
2. **Clone.** `git clone --depth 1 <url> repos/<name>` (skip if it exists; then `git -C repos/<name> pull`).
   Create `repos/<name>/_agent/` for logs and the report.
3. **Read & plan.** Read the README (and `requirements*.txt`, `pyproject.toml`, any install docs it links to).
   Write `repos/<name>/_agent/plan.md` with: Python version, install commands (Windows/venv variants),
   models to download (URL → destination, approx size), GPU vs CPU choice, launch command, and
   how to tell it launched (web port? GUI window? CLI `--help`?). Translate Linux/conda/Mac-only
   steps into Windows + venv equivalents.
4. **Venv + install.** Run the plan. Log every command and its outcome to `_agent/install.log`
   (append; use `2>&1 | tee -a`). Long installs: use a generous timeout (up to 10 min per command).
5. **Models.** Download per plan; check files exist with sensible sizes.
6. **Launch check.** Delegate to the `launch-verifier` subagent with: repo path, launch command
   (using `.venv/Scripts/python.exe`), expected port if any, and wait time (30s; 90s for heavy apps).
7. **On any failure (install or launch):** delegate to the `repo-fixer` subagent with the repo path,
   the failing command, the log tail, what's been tried, the step name, and "fix round N of 3".
   Apply its fix, retry. Maximum **3 fix rounds** per failing step; then stop and report the blocker.
   (Subagent replies end with a JSON block that the trace hook logs; don't strip it when relaying.)
8. **Report.** Write `repos/<name>/_agent/report.md`:
   - Result: PASS / FAIL, and at which step
   - Python version, GPU or CPU, launch command
   - System tools installed, models downloaded (+ sizes)
   - Deviations from the README and fixes applied (with reasons)
   - Remaining issues / next steps
   Then append one line to `repos/RESULTS.md`: `| <name> | <url> | PASS/FAIL | <date> | <one-line note> |`
   (create the table header if the file is new).
9. Tell the user the result in 2–4 sentences with a link to the report.
