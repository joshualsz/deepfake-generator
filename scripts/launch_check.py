"""Launch a repo's app, watch it for a while, then stop it and report PASS/FAIL.

Usage:
    python scripts/launch_check.py --cwd repos/<name> --log repos/<name>/_agent/launch.log \
        [--wait 30] [--port 7860] [--keep-open] -- <command> [args...]

PASS means: the process is still alive after --wait seconds, no Python traceback /
fatal error appeared in its output, and (if --port is given) the port accepts a
TCP connection. Exit code 0 = PASS, 1 = FAIL. A JSON summary is printed last.
"""
import argparse
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

FATAL = re.compile(
    r"Traceback \(most recent call last\)|ModuleNotFoundError|ImportError|"
    r"CUDA out of memory|Segmentation fault|FileNotFoundError",
)


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--wait", type=int, default=30)
    ap.add_argument("--port", type=int)
    ap.add_argument("--keep-open", action="store_true", help="leave the app running on PASS")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        ap.error("no command given after --")
    # Popen on Windows doesn't resolve a relative executable against cwd; do it here.
    exe = Path(args.cwd) / cmd[0]
    if not Path(cmd[0]).is_absolute() and exe.exists():
        cmd[0] = str(exe.resolve())

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            cmd, cwd=args.cwd, stdout=log, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
        deadline = time.time() + args.wait
        port_ok = None
        while time.time() < deadline and proc.poll() is None:
            if args.port and port_open(args.port):
                port_ok = True
            time.sleep(1)
        if args.port and port_ok is None:
            port_ok = port_open(args.port)

    output = log_path.read_text(encoding="utf-8", errors="replace")
    fatal = FATAL.search(output)
    alive = proc.poll() is None
    passed = alive and not fatal and (port_ok if args.port else True)

    if not (passed and args.keep_open):
        kill_tree(proc)

    summary = {
        "result": "PASS" if passed else "FAIL",
        "alive_after_wait": alive,
        "exit_code": None if alive else proc.returncode,
        "fatal_match": fatal.group(0) if fatal else None,
        "port": args.port,
        "port_open": port_ok,
        "left_running": bool(passed and args.keep_open),
        "pid": proc.pid,
        "log": str(log_path),
        "log_tail": output[-2000:],
    }
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
