---
name: eod-report
description: Write up file changes in eod_report/ as before / problem / solution / result entries so the project's progression can be tracked. Use when the user says "/eod-report", when the Stop hook says edits are pending in the EOD report, or after editing files in a way the hook can't see (Bash/sed, manual user edits).
---

# eod-report: log and explain changes

Every file edit is written up in a daily Markdown report, so the user can trace how the project
evolved, what was wrong and why each fix was made.

Project root: the current working directory. Reports live in `eod_report/`.

## How capture works

- `scripts/eod_capture_hook.py` runs on **PostToolUse** for Edit/Write/MultiEdit/NotebookEdit and appends
  one JSON line per edit to `eod_report/.pending.jsonl`. Each line holds the time, tool, file, and either
  a `diff` (unified hunks) or `before`/`after` snippets, plus `new_file: true` for newly created files.
- On **Stop**, the same script blocks once if `.pending.jsonl` has entries, which prompts this skill.
- Edits made through Bash (sed, heredocs, scripts that write files), by subagents in other sessions, or
  by the user by hand are **not** captured. If you know of any such edits, add them yourself (see step 2).

## Steps

1. **Read the pending captures:** `eod_report/.pending.jsonl`. If it's missing or empty and there are no
   uncaptured edits to log, tell the user there is nothing to report and stop.

2. **Group the captures into changes.** One *change* = one problem solved. Several edits across several
   files for the same fix become one entry. Edits for unrelated reasons become separate entries. Add
   any uncaptured edits you made this session (via Bash, etc.) to the right group.

3. **Write each entry** using what you know from this conversation: why the edit was made, what
   failed, and what the logs showed. Don't invent motives. If the reason for a capture isn't in your
   context (for example, it came from an earlier session), say so in **Problem** and describe only what
   the diff shows.

4. **Append to `eod_report/YYYY-MM-DD.md`** (today's local date). If the file doesn't exist yet, create it
   with the header below. Then add one row per new entry to the day's **Index** table and append the
   entries at the end.

5. **Clear the pending file:** delete `eod_report/.pending.jsonl` only after the report is written.

6. Tell the user in one or two lines which entries were added and give the file link.

## Report format

New day file header:

```markdown
# EOD Report: YYYY-MM-DD

| # | Time | Change | Files | Status |
|---|------|--------|-------|--------|
```

Status is one of `✅ Verified`, `⚠️ Unverified`, `❌ Did not fix` or `↩️ Reverted`.

Each entry:

````markdown
---

## N. <Short title of the change> (HH:MM)

**Files:** `path/one.py`, `path/two.md`
**Context:** <which repo / task this was part of, e.g. "run-repo CosyVoice, install step">

### Before
What the code/config looked like and how it behaved. Quote the relevant lines (short), or for a new
file say "did not exist" and what was missing because of that.

### Problem
What was wrong with that state: the error message, symptom or limitation, and the root cause if known.
Quote the key log line(s) verbatim.

### Solution
What was changed and *why this approach* was chosen. Mention alternatives you rejected, if any.

### Result
The final state and how it was verified (the command run and the output seen). If it wasn't verified,
say so plainly and mark the status ⚠️. If it didn't fix the problem, say what happened next.

<details><summary>Diff</summary>

```diff
<the relevant hunks from the captures, trimmed to what matters>
```

</details>
````

## Rules

- Write for the user reading this weeks later: plain language, specific, no filler. Each section is
  usually 1–4 sentences.
- Number entries consecutively within a day file (continue from the last number already there).
- Never edit or reword earlier entries, except to add a short `**Update (HH:MM):**` line under an
  entry's Result when a later change reverts or supersedes it.
- Keep diffs short. For large new files, summarise what they contain instead of pasting them.
- Never put secrets (tokens, API keys, cookies) in the report. Redact them as `<redacted>`.
