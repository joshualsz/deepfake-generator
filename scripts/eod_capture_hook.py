"""Hook for the eod-report skill.

PostToolUse (Edit/Write/MultiEdit/NotebookEdit): append the raw before/after of the
edit to eod_report/.pending.jsonl so the skill can write it up later.

Stop: if there are pending captures, block the stop once and ask Claude to run the
eod-report skill while the reasoning behind the edits is still in context.
"""
import json
import os
import sys
from datetime import datetime

MAX_CHARS = 4000  # cap stored snippets so the pending file stays small


def clip(text):
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + f"\n... [{len(text) - MAX_CHARS} more chars]"


def patch_to_text(patch):
    if not isinstance(patch, list):
        return None
    lines = []
    for hunk in patch:
        lines.append(f"@@ -{hunk.get('oldStart')},{hunk.get('oldLines')} +{hunk.get('newStart')},{hunk.get('newLines')} @@")
        lines.extend(hunk.get("lines", []))
    return "\n".join(lines)


def main():
    if os.environ.get("DEEPFAKE_EVAL_RUN"):
        return  # eval trials edit throwaway workspaces; nothing to report
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    report_dir = os.path.join(project, "eod_report")
    pending = os.path.join(report_dir, ".pending.jsonl")
    event = data.get("hook_event_name")

    if event == "PostToolUse":
        tool_input = data.get("tool_input") or {}
        resp = data.get("tool_response") or {}
        if not isinstance(resp, dict):
            resp = {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        # Never log edits to the report itself.
        if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(report_dir))):
            return

        try:
            rel = os.path.relpath(path, project) if path else ""
        except ValueError:  # different drive on Windows
            rel = path
        if rel.startswith(".."):
            rel = path
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "tool": data.get("tool_name"),
            "file": rel,
            "session": data.get("session_id"),
        }
        diff = patch_to_text(resp.get("structuredPatch"))
        if diff:
            entry["diff"] = clip(diff)
        elif "old_string" in tool_input:
            entry["before"] = clip(tool_input.get("old_string"))
            entry["after"] = clip(tool_input.get("new_string"))
        elif "edits" in tool_input:
            entry["edits"] = [{"before": clip(e.get("old_string")), "after": clip(e.get("new_string"))}
                              for e in tool_input["edits"]]
        else:
            entry["before"] = clip(resp.get("originalFile"))
            entry["after"] = clip(tool_input.get("content") or tool_input.get("new_source"))
        if resp.get("type") == "create" or (data.get("tool_name") == "Write" and not resp.get("originalFile")):
            entry["new_file"] = True

        os.makedirs(report_dir, exist_ok=True)
        with open(pending, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    elif event == "Stop":
        if data.get("stop_hook_active"):
            return  # already blocked once this turn; don't loop
        if not os.path.exists(pending):
            return
        with open(pending, encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
        if count:
            print(json.dumps({
                "decision": "block",
                "reason": f"{count} file edit(s) this session are not yet in the EOD report. "
                          "Invoke the eod-report skill to document them (before / problem / solution / result), "
                          "then finish.",
            }))


if __name__ == "__main__":
    main()
