# Source before running agent commands in Git Bash:  source scripts/env.sh
# (VS Code's shell predates the winget installs, so uv/ffmpeg aren't on its PATH.)
WG="$LOCALAPPDATA/Microsoft/WinGet/Packages"
WG="$(cygpath -u "$WG")"
export PATH="$(ls -d "$WG"/astral-sh.uv_*/ | head -1):$(ls -d "$WG"/Gyan.FFmpeg_*/ffmpeg-*/bin | head -1):$PATH"
export UV_LINK_MODE=copy   # project is in OneDrive; hardlinks fail there
export PYTHONIOENCODING=utf-8
