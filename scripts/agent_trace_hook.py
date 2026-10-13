"""Claude Code hook: append one structured JSON line per agent event to logs/agent_events.jsonl.

Wired up in .claude/settings.json for SessionStart/End, UserPromptSubmit, Pre/PostToolUse,
PostToolUseFailure, SubagentStart/Stop and Stop. Reads the hook payload from stdin.

trace_id is the Claude Code session id; tool calls are spans keyed by tool_use_id; a subagent's
Agent tool call is its span, and the subagent's final ```json block is logged as agent_result.
Set AGENT_TRACE_DEBUG=1 to also record the payload's key names (for discovering new fields).

Never blocks or fails the agent: every error goes to logs/agent_trace_errors.log and exit is 0.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
LOG_DIR = ROOT / "logs"
MAX_CMD = 500
MAX_SIG = 200

SECRETS = [
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "hf_***"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh*_***"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1***"),
    (re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret)(\s*[=:]\s*)[^\s&\"']+"), r"\1\2***"),
]
REPO_RE = re.compile(r"repos[/\\]+([A-Za-z0-9._-]+)")
# Last line that looks like an error: Python exception, "error:", or a Windows error code.
ERROR_RE = re.compile(r"(?im)^.*\b(?:\w*(?:Error|Exception)\b|error:|FAILED|WinError \d+|fatal:).*$")
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def redact(s: str, limit: int) -> str:
    for pat, repl in SECRETS:
        s = pat.sub(repl, s)
    return s if len(s) <= limit else s[:limit] + f"...[+{len(s) - limit}]"


def flatten_text(obj) -> str:
    """All string content inside a (possibly nested) tool response, joined."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(flatten_text(v) for v in obj.values())
    if isinstance(obj, list):
        return "\n".join(flatten_text(v) for v in obj)
    return ""


def error_sig(text: str):
    hits = ERROR_RE.findall(text or "")
    return redact(hits[-1].strip(), MAX_SIG) if hits else None


def summarize_input(tool: str, ti: dict) -> dict:
    if tool in ("Bash", "PowerShell"):
        return {"cmd": redact(ti.get("command", ""), MAX_CMD), "desc": ti.get("description"),
                "background": ti.get("run_in_background") or None}
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        return {"path": ti.get("file_path") or ti.get("notebook_path")}
    if tool in ("Agent", "Task"):
        return {"subagent": ti.get("subagent_type") or "general-purpose", "desc": ti.get("description"),
                "prompt_chars": len(ti.get("prompt", "")) or None}
    if tool == "Skill":
        return {"skill": ti.get("skill"), "args": redact(ti.get("args") or "", 200) or None}
    if tool == "WebFetch":
        return {"url": redact(ti.get("url", ""), 300)}
    if tool == "WebSearch":
        return {"query": ti.get("query")}
    if tool in ("Grep", "Glob"):
        return {"pattern": ti.get("pattern"), "path": ti.get("path")}
    return {"input_keys": sorted(ti)[:10]}


def build_event(p: dict) -> dict:
    ev_name = p.get("hook_event_name", "unknown")
    ev = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": ev_name,
        "trace_id": p.get("session_id"),
        "agent_id": p.get("agent_id"),
        "agent_type": p.get("agent_type"),
    }
    tool = p.get("tool_name")
    if tool:
        ev["tool"] = tool
        ev["span_id"] = p.get("tool_use_id")
        ev.update(summarize_input(tool, p.get("tool_input") or {}))

    if ev_name == "PostToolUse":
        resp = p.get("tool_response")
        ev["outcome"] = "ok"
        if isinstance(resp, dict):
            # Keep cheap numeric facts (durations, token counts, exit codes) when the harness supplies them.
            ev["metrics"] = {k: v for k, v in resp.items()
                             if isinstance(v, (int, float)) and not isinstance(v, bool)} or None
            if resp.get("interrupted"):
                ev["outcome"] = "interrupted"
        text = flatten_text(resp)
        if tool in ("Bash", "PowerShell"):
            ev["error_sig"] = error_sig(text)
        if tool in ("Agent", "Task"):
            blocks = JSON_BLOCK_RE.findall(text)
            if blocks:
                try:
                    ev["agent_result"] = json.loads(blocks[-1])
                except json.JSONDecodeError:
                    ev["agent_result_error"] = "unparseable json block"
            else:
                ev["agent_result_error"] = "no json block"
    elif ev_name == "PostToolUseFailure":
        ev["outcome"] = "error"
        text = flatten_text(p.get("error") or p.get("tool_response"))
        code = re.search(r"Exit code (\d+)", text)
        ev["exit_code"] = int(code.group(1)) if code else None
        # No exception-looking line: fall back to the last meaningful line (usually the message).
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("Exit code")]
        ev["error_sig"] = error_sig(text) or (redact(lines[-1], MAX_SIG) if lines else None)
    elif ev_name == "UserPromptSubmit":
        prompt = p.get("prompt", "")
        # Never log prompt text; just its size and any slash command it starts with.
        m = re.match(r"\s*/([\w:-]+)", prompt)
        ev.update(prompt_chars=len(prompt), command=m.group(1) if m else None)
    elif ev_name == "SessionStart":
        ev["source"] = p.get("source")
    elif ev_name == "SessionEnd":
        ev["reason"] = p.get("reason")

    blob = " ".join(str(v) for v in (ev.get("cmd"), ev.get("path"), ev.get("args"), ev.get("pattern")) if v)
    repo = REPO_RE.search(blob)
    if repo:
        ev["repo"] = repo.group(1)
    if os.environ.get("AGENT_TRACE_DEBUG") == "1":
        ev["payload_keys"] = sorted(p)
    return {k: v for k, v in ev.items() if v is not None}


def main() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        line = json.dumps(build_event(payload), ensure_ascii=False) + "\n"
        with open(LOG_DIR / "agent_events.jsonl", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:  # logging must never break the agent
        with open(LOG_DIR / "agent_trace_errors.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
