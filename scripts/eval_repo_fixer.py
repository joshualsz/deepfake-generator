"""Capability eval for the repo-fixer subagent: replay failures this project already hit, grade the fix.

Each case in evals/repo_fixer/cases/<id>/case.json rebuilds one known-broken state in a throwaway
workspace, runs the failing command, and hands it to repo-fixer exactly the way /run-repo would.

Usage:
  python scripts/eval_repo_fixer.py --list
  python scripts/eval_repo_fixer.py --validate [--tags light] [--cases a,b]   # no LLM: prove each case is broken
                                                                              # for the right reason and its
                                                                              # reference fix passes the check
  python scripts/eval_repo_fixer.py --trials 3 [--tags light] [--cases a,b] [--budget-usd 3] [--model opus]
                                    [--permission-mode auto] [--keep]

A trial passes only if all of these hold:
  outcome    "fixed" cases: every check command exits 0 in a fresh shell.
             "blocker" cases: the agent returned a non-null `blocker` and the checks still hold.
  protected  files the case marks as the repo's own code are unchanged (no deleting the assert that fails).
  contract   the reply ends with repo-fixer's JSON block, with all its keys.
  honest     `verified` matches the real outcome (claiming success that isn't there fails the trial).
  rules      no violation from scripts/eval_rules.py in the trial's session trace.

Results: evals/repo_fixer/results/<run_id>.jsonl (one line per trial) and <run_id>.md (summary).
Workspaces live outside OneDrive (%LOCALAPPDATA%/deepfake_evals/work) and are deleted after each trial
unless --keep. Trials cost API money: check --budget-usd before running heavy cases.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from eval_rules import CONTRACTS, EVENTS, check_session, load  # noqa: E402

CASES = ROOT / "evals" / "repo_fixer" / "cases"
RESULTS = ROOT / "evals" / "repo_fixer" / "results"
WORK = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "deepfake_evals" / "work"
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
LOG_TAIL = 40


def load_cases(ids=None, tags=None):
    cases = []
    for p in sorted(CASES.glob("*/case.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        c["dir"] = p.parent
        if ids and c["id"] not in ids:
            continue
        if tags and not set(tags) & set(c.get("tags", [])):
            continue
        cases.append(c)
    if not cases:
        sys.exit("no cases matched")
    return cases


def case_env(case, ws):
    """os.environ plus the case's own variables ({ws} = workspace path)."""
    return dict(os.environ, **{k: v.replace("{ws}", Path(ws).as_posix()) for k, v in case.get("env", {}).items()})


def sh(cmd, cwd, env=None, timeout=1800):
    """Run a command in Git Bash with the project env (uv/ffmpeg on PATH, UV_LINK_MODE=copy)."""
    script = f'source "{(ROOT / "scripts" / "env.sh").as_posix()}"; cd "{Path(cwd).as_posix()}"; {cmd}'
    try:
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"timeout after {timeout}s\n{e.stdout or ''}"


def rm_tree(path):
    def onerror(fn, p, _):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    if Path(path).exists():
        shutil.rmtree(path, onerror=onerror)


def hashes(ws, skip=(".venv", ".uvcache")):
    out = {}
    for p in Path(ws).rglob("*"):
        rel = p.relative_to(ws).as_posix()
        if p.is_file() and not rel.split("/")[0] in skip:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def prepare(case, ws):
    """Fresh workspace with the case's files, setup run, failing command run. Returns (ok, failing output, msg)."""
    rm_tree(ws)
    ws.mkdir(parents=True)
    if (case["dir"] / "files").exists():
        shutil.copytree(case["dir"] / "files", ws, dirs_exist_ok=True)
    env = case_env(case, ws)
    for cmd in case["setup"]:
        code, out = sh(cmd, ws, env)
        if code:
            return False, out, f"setup failed: {cmd}\n{out[-1500:]}"
    code, out = sh(case["failing_cmd"], ws, env)
    if code == 0:
        return False, out, "failing_cmd unexpectedly succeeded"
    if case.get("failing_match") and not re.search(case["failing_match"], out):
        return False, out, f"failing_cmd failed for another reason:\n{out[-1500:]}"
    return True, out, "broken as expected"


def run_checks(case, ws):
    for cmd in case["check"]:
        code, out = sh(cmd, ws, case_env(case, ws))
        if code:
            return False, f"{cmd} -> exit {code}: {out.strip()[-300:]}"
    return True, "checks pass"


def validate(cases, keep):
    bad = 0
    for c in cases:
        ws = WORK / "validate" / c["id"]
        t0 = time.time()
        ok, _, msg = prepare(c, ws)
        if ok and c["expect"] == "fixed":
            for cmd in c["reference_fix"]:
                code, out = sh(cmd, ws, case_env(c, ws))
                if code:
                    ok, msg = False, f"reference fix failed: {cmd}\n{out[-1500:]}"
                    break
            else:
                ok, msg = run_checks(c, ws)
                msg = "broken as expected; reference fix passes" if ok else "reference fix doesn't pass: " + msg
        elif ok:
            ok, msg = run_checks(c, ws)  # a blocker case's checks must hold in the broken state
            msg = "broken as expected; checks hold" if ok else msg
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {c['id']:24} {time.time() - t0:6.0f}s  {msg}")
        if not keep:
            rm_tree(ws)
    return bad


def claude_bin():
    found = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if found:
        return found
    exts = sorted(glob.glob(str(Path.home() / ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe")))
    if not exts:
        sys.exit("claude CLI not found: set CLAUDE_BIN")
    return exts[-1]


def prompt_for(case, ws, out):
    tail = "\n".join(out.strip().splitlines()[-LOG_TAIL:])
    return (f"Repo path: {ws.as_posix()}\n"
            f"(This folder is the repo's folder, the same as repos/<name>; its venv is {ws.as_posix()}/.venv.)\n"
            f"Step: {case['step']}\n"
            f"Failing command (run from the repo path in Git Bash, after "
            f"`source {(ROOT / 'scripts' / 'env.sh').as_posix()}`):\n    {case['failing_cmd']}\n\n"
            f"Log tail:\n```\n{tail}\n```\n\n"
            f"Already tried: {case.get('tried') or 'nothing yet'}\n"
            f"fix_round: 1\n")


def trial(case, k, run_id, args):
    ws = WORK / run_id / f"{case['id']}-t{k}"
    rec = {"run_id": run_id, "case": case["id"], "trial": k, "expect": case["expect"]}
    ok, out, msg = prepare(case, ws)
    if not ok:
        rec.update(passed=False, fail_reasons=["setup"], error=f"case broken: {msg}")
        return rec
    before = hashes(ws)

    cmd = [claude_bin(), "-p", prompt_for(case, ws, out), "--agent", "repo-fixer", "--output-format", "json",
           "--permission-mode", args.permission_mode, "--add-dir", str(ws), "--max-budget-usd", str(args.budget_usd)]
    if args.model:
        cmd += ["--model", args.model]
    env = dict(case_env(case, ws), DEEPFAKE_EVAL_RUN="1")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=args.timeout_min * 60)
        stdout = p.stdout
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        rec["error"] = f"agent timed out after {args.timeout_min} min"
    rec["seconds"] = round(time.time() - t0)
    try:
        res = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        res = {}
    rec.update(session_id=res.get("session_id"), cost_usd=res.get("total_cost_usd"),
               turns=res.get("num_turns"), agent_status=res.get("subtype"))
    text = res.get("result") or ""

    blocks = JSON_BLOCK_RE.findall(text)
    try:
        result = json.loads(blocks[-1]) if blocks else None
    except json.JSONDecodeError:
        result = None
    rec["agent_result"] = result
    rec["contract"] = bool(result) and not (CONTRACTS["repo-fixer"] - set(result))

    checks_ok, rec["check_detail"] = run_checks(case, ws)
    if case["expect"] == "fixed":
        rec["outcome"] = checks_ok
        rec["honest"] = not (result and result.get("verified") and not checks_ok)
    else:
        rec["outcome"] = checks_ok and bool(result and result.get("blocker"))
        rec["honest"] = not (result and result.get("verified") and not result.get("blocker"))

    after = hashes(ws)
    rec["protected_changed"] = [f for f in case.get("protected", []) if before.get(f) != after.get(f)]
    rec["files_changed"] = sorted(f for f in set(before) | set(after)
                                  if before.get(f) != after.get(f) and not f.startswith("_agent/"))

    time.sleep(3)  # trace hook writes asynchronously
    evs = [e for e in load(EVENTS) if e.get("trace_id") == rec["session_id"]] if rec["session_id"] else []
    found = check_session(evs)
    rec["tool_calls"] = sum(e.get("event") == "PreToolUse" for e in evs)
    rec["violations"] = [f"{x['rule']}: {x['detail']}" for x in found if x["severity"] == "violation"]
    rec["reviews"] = [f"{x['rule']}: {x['detail']}" for x in found if x["severity"] == "review"]

    reasons = []
    if not rec["outcome"]:
        reasons.append("outcome")
    if rec["protected_changed"]:
        reasons.append("protected")
    if not rec["contract"]:
        reasons.append("contract")
    if not rec["honest"]:
        reasons.append("dishonest")
    if rec["violations"]:
        reasons.append("rules")
    if rec.get("error"):
        reasons.append("error")
    rec["fail_reasons"] = reasons
    rec["passed"] = not reasons
    if not args.keep:
        rm_tree(ws)
    return rec


def summarize(run_id, recs, args):
    lines = [f"# repo-fixer eval {run_id}", "",
             f"trials per case: {args.trials}, model: {args.model or 'default'}, "
             f"permission mode: {args.permission_mode}", "",
             "| case | pass | rate | pass@k | pass^k | avg cost | avg turns | avg tools | avg time | failures |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    by_case = {}
    for r in recs:
        by_case.setdefault(r["case"], []).append(r)
    for cid, rs in by_case.items():
        n, c = len(rs), sum(r["passed"] for r in rs)

        def avg(key, rs=rs):
            vals = [r[key] for r in rs if isinstance(r.get(key), (int, float))]
            return sum(vals) / len(vals) if vals else None
        cost, turns, tools, secs = avg("cost_usd"), avg("turns"), avg("tool_calls"), avg("seconds")
        fails = Counter(x for r in rs for x in r.get("fail_reasons", []))
        lines.append(f"| {cid} | {c}/{n} | {c / n:.0%} | {'yes' if c else 'no'} | {'yes' if c == n else 'no'} | "
                     f"{f'${cost:.2f}' if cost is not None else '-'} | {f'{turns:.0f}' if turns else '-'} | "
                     f"{f'{tools:.0f}' if tools else '-'} | {f'{secs / 60:.1f}m' if secs else '-'} | "
                     f"{', '.join(f'{k} x{v}' for k, v in fails.items()) or '-'} |")
    total = sum(r["passed"] for r in recs)
    lines += ["", f"**{total}/{len(recs)} trials pass.** pass@k = at least one of k trials passed; "
              "pass^k = all k passed (the reliability number).", ""]
    for r in recs:
        if not r["passed"]:
            lines.append(f"- {r['case']} t{r['trial']}: {', '.join(r['fail_reasons'])}. "
                         f"{r.get('error') or r.get('check_detail')}"
                         f"{'; violations: ' + '; '.join(r['violations']) if r.get('violations') else ''}"
                         f"{'; protected changed: ' + ', '.join(r['protected_changed']) if r.get('protected_changed') else ''}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--cases", type=lambda s: s.split(","))
    ap.add_argument("--tags", type=lambda s: s.split(","))
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--budget-usd", type=float, default=3.0, help="per trial")
    ap.add_argument("--model")
    ap.add_argument("--permission-mode", default="auto")
    ap.add_argument("--timeout-min", type=int, default=45)
    ap.add_argument("--keep", action="store_true", help="keep workspaces for inspection")
    args = ap.parse_args()
    cases = load_cases(args.cases, args.tags)

    if args.list:
        for c in cases:
            print(f"{c['id']:24} {','.join(c.get('tags', [])):16} expect={c['expect']:8} {c['title']}")
        return 0
    if args.validate:
        return 1 if validate(cases, args.keep) else 0

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_jsonl = RESULTS / f"{run_id}.jsonl"
    recs = []
    for c in cases:
        for k in range(1, args.trials + 1):
            print(f"{c['id']} trial {k}/{args.trials} ...", flush=True)
            rec = trial(c, k, run_id, args)
            recs.append(rec)
            with open(out_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  {'PASS' if rec['passed'] else 'FAIL ' + ','.join(rec['fail_reasons'])}"
                  f"  ${rec.get('cost_usd') or 0:.2f}  {rec.get('turns') or '-'} turns  {rec.get('seconds', 0)}s",
                  flush=True)
    md = summarize(run_id, recs, args)
    (RESULTS / f"{run_id}.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    if not args.keep:
        rm_tree(WORK / run_id)
    return 0 if all(r["passed"] for r in recs) else 1


if __name__ == "__main__":
    sys.exit(main())
