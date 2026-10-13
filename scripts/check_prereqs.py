"""Report which system tools the run-repo agent relies on are available (JSON)."""
import json
import shutil
import subprocess


def version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return None


tools = {name: shutil.which(name) for name in ["git", "uv", "ffmpeg", "winget", "nvidia-smi"]}
info = {
    "tools": tools,
    "uv_version": version(["uv", "--version"]) if tools["uv"] else None,
    "ffmpeg_version": version(["ffmpeg", "-version"]) if tools["ffmpeg"] else None,
    "gpu": version(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader"]) if tools["nvidia-smi"] else None,
}
print(json.dumps(info, indent=2))
