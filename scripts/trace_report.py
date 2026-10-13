"""Summarise logs/agent_events.jsonl (written by scripts/agent_trace_hook.py).

Usage:
  python scripts/trace_report.py                     # list recent sessions
  python scripts/trace_report.py --session latest    # one session: skills, subagent spans, per-repo rollup
  python scripts/trace_report.py --session 3dd95f6e  # (id prefix)
  python scripts/trace_report.py --errors            # recurring error signatures across all sessions
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "logs" / "agent_events.jsonl"
END_EVENTS = ("PostToolUse", "PostToolUseFailure")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a line torn by a crash shouldn't hide the rest
    rows.sort(key=lambda r: r["ts"])
    return rows


def ts(r):
    return datetime.fromisoformat(r["ts"])


def fmt_s(sec):
    return f"{sec / 60:.1f}m" if sec >= 90 else f"{sec:.1f}s"


def by_session(rows):
    out = defaultdict(list)
    for r in rows:
        out[r.get("trace_id", "?")].append(r)
    return out


def spans(evs):
    """Pair Pre/Post events by span_id -> list of {start, end, seconds, pre, post}."""
    pres = {e["span_id"]: e for e in evs if e["event"] == "PreToolUse" and e.get("span_id")}
    out = []
    for e in evs:
        if e["event"] in END_EVENTS and e.get("span_id") in pres:
            pre = pres[e["span_id"]]
            out.append({"pre": pre, "post": e, "seconds": (ts(e) - ts(pre)).total_seconds()})
    return out


def list_sessions(rows):
    print(f"{'session':10} {'start (UTC)':17} {'dur':>7} {'tools':>6} {'fail':>5} {'agents':>6}  commands/skills")
    for sid, evs in sorted(by_session(rows).items(), key=lambda kv: kv[1][0]["ts"])[-15:]:
        tools = [e for e in evs if e["event"] == "PreToolUse"]
        fails = sum(e["event"] == "PostToolUseFailure" for e in evs)
        agents = sum(e.get("tool") in ("Agent", "Task") for e in tools)
        cmds = [e["command"] for e in evs if e.get("command")] + [e["skill"] for e in tools if e.get("skill")]
        dur = (ts(evs[-1]) - ts(evs[0])).total_seconds()
        print(f"{sid[:8]:10} {evs[0]['ts'][:16]:17} {fmt_s(dur):>7} {len(tools):>6} {fails:>5} {agents:>6}  "
              f"{', '.join(dict.fromkeys(cmds)) or '-'}")


def show_session(rows, key):
    sessions = by_session(rows)
    if key == "latest":
        sid = max(sessions, key=lambda s: sessions[s][-1]["ts"])
    else:
        matches = [s for s in sessions if s.startswith(key)]
        if len(matches) != 1:
            sys.exit(f"session prefix '{key}' matched {len(matches)} sessions")
        sid = matches[0]
    evs = sessions[sid]
    sp = spans(evs)
    print(f"session {sid}  {evs[0]['ts'][:19]} -> {evs[-1]['ts'][11:19]}  "
          f"({fmt_s((ts(evs[-1]) - ts(evs[0])).total_seconds())}, {len(sp)} tool calls)\n")

    skills = [e for e in evs if e["event"] == "PreToolUse" and e.get("skill")]
    if skills:
        print("skills:", ", ".join(f"{e['skill']} @{e['ts'][11:19]}" for e in skills), "\n")

    agent_spans = [s for s in sp if s["pre"].get("tool") in ("Agent", "Task")]
    if agent_spans:
        print("subagents:")
        for s in agent_spans:
            m = s["post"].get("metrics") or {}
            res = s["post"].get("agent_result") or {}
            secs = m.get("totalDurationMs", s["seconds"] * 1000) / 1000
            verdict = res.get("verdict") or ("verified" if res.get("verified") else None) \
                or res.get("blocker") or s["post"].get("agent_result_error") or s["post"].get("outcome")
            rnd = f" round {res['fix_round']}" if res.get("fix_round") else ""
            print(f"  {s['pre']['ts'][11:19]} {s['pre'].get('subagent', '?'):16} {fmt_s(secs):>7} "
                  f"{m.get('totalTokens', '-'):>7} tok  {res.get('repo', '')}{rnd}: {verdict}"
                  f"  ({s['pre'].get('desc', '')})")
            if res.get("root_cause"):
                print(f"{'':28}cause: {res['root_cause']}")
        print()

    repos = defaultdict(lambda: {"calls": 0, "secs": 0.0, "fail": 0, "sigs": Counter()})
    for s in sp:
        repo = s["pre"].get("repo") or s["post"].get("repo")
        if not repo:
            continue
        r = repos[repo]
        r["calls"] += 1
        r["secs"] += s["seconds"]
        r["fail"] += s["post"]["event"] == "PostToolUseFailure"
        if s["post"].get("error_sig"):
            r["sigs"][s["post"]["error_sig"]] += 1
    for s in agent_spans:  # subagent results also name their repo
        res = s["post"].get("agent_result") or {}
        if res.get("repo"):
            repos[res["repo"]].setdefault("agents", []).append(res.get("agent", "?"))
    if repos:
        print(f"{'repo':28} {'calls':>5} {'time':>7} {'fail':>5}  subagents / top error")
        for name, r in sorted(repos.items(), key=lambda kv: -kv[1]["secs"]):
            agents = Counter(r.get("agents", []))
            top = r["sigs"].most_common(1)
            print(f"{name:28} {r['calls']:>5} {fmt_s(r['secs']):>7} {r['fail']:>5}  "
                  f"{', '.join(f'{a} x{n}' for a, n in agents.items()) or '-'}"
                  f"{'  | ' + top[0][0][:70] if top else ''}")
        print()

    print("slowest tool calls:")
    for s in sorted(sp, key=lambda s: -s["seconds"])[:5]:
        what = s["pre"].get("cmd") or s["pre"].get("desc") or s["pre"].get("path") or ""
        print(f"  {fmt_s(s['seconds']):>7} {s['pre']['tool']:10} {what[:90]}")


def show_errors(rows):
    sigs = defaultdict(lambda: {"n": 0, "repos": set(), "failed": 0})
    for r in rows:
        if r.get("error_sig"):
            s = sigs[r["error_sig"]]
            s["n"] += 1
            s["failed"] += r["event"] == "PostToolUseFailure"
            if r.get("repo"):
                s["repos"].add(r["repo"])
    print(f"{'seen':>5} {'fail':>5}  {'repos':30} error signature")
    for sig, s in sorted(sigs.items(), key=lambda kv: -kv[1]["n"])[:30]:
        print(f"{s['n']:>5} {s['failed']:>5}  {','.join(sorted(s['repos']))[:30]:30} {sig[:100]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--file", type=Path, default=EVENTS)
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no trace yet: {args.file}")
    rows = load(args.file)
    if args.errors:
        show_errors(rows)
    elif args.session:
        show_session(rows, args.session)
    else:
        list_sessions(rows)


if __name__ == "__main__":
    main()
