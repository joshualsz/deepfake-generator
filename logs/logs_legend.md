# logs/ legend

`agent_events.jsonl` is the activity log of Claude Code in this project. A hook
([scripts/agent_trace_hook.py](../scripts/agent_trace_hook.py), wired up in
[.claude/settings.json](../.claude/settings.json)) appends one line per event: every tool call made by the
main agent or a subagent, plus session and subagent start/stop.

- **Format:** JSON Lines. Each line is one complete JSON object, and new events are appended at the end.
  Lines are never rewritten.
- **Fields are omitted when empty.** A line only carries the fields that apply to it.
- **Readable summary:** `python scripts/trace_report.py` (sessions), `--session latest` (one session in
  detail), `--errors` (recurring errors).
- `agent_trace_errors.log` appears only if the hook itself fails. If it's absent, logging is healthy.

## Example

A tool call produces two lines, one when it starts and one when it ends, linked by `span_id`:

```json
{"ts": "2026-10-08T05:08:21.789+00:00", "event": "PreToolUse", "trace_id": "3dd95f6e-...", "tool": "Bash", "span_id": "toolu_01EU...", "cmd": "uv pip install ...", "repo": "ghost"}
{"ts": "2026-10-08T05:08:40.120+00:00", "event": "PostToolUse", "trace_id": "3dd95f6e-...", "tool": "Bash", "span_id": "toolu_01EU...", "outcome": "ok", "error_sig": "OSError: [WinError 126] ...", "repo": "ghost"}
```

## Event types (`event`)

| Event | Meaning |
|---|---|
| `SessionStart` | A Claude Code session started (`source`: startup / resume / clear / compact) |
| `SessionEnd` | The session ended (`reason`) |
| `UserPromptSubmit` | The user sent a message. Only its length and any `/command` are logged, never the text |
| `PreToolUse` | A tool call is about to run |
| `PostToolUse` | The tool call finished |
| `PostToolUseFailure` | The tool call failed (e.g. non-zero exit code) |
| `SubagentStart` / `SubagentStop` | A subagent (repo-fixer, launch-verifier, ...) started / stopped |
| `Stop` | The main agent finished its reply |

## Fields on every line

| Field | Meaning |
|---|---|
| `ts` | Time the hook recorded the event, UTC, ISO 8601 with milliseconds |
| `event` | Event type (see above) |
| `trace_id` | Claude Code session id. Groups everything from one conversation |
| `agent_id`, `agent_type` | Set when the event comes from inside a subagent (when the harness provides them) |

## Tool-call fields

| Field | Meaning |
|---|---|
| `tool` | Tool name: `Bash`, `PowerShell`, `Read`, `Edit`, `Write`, `Agent`, `Skill`, `WebFetch`, ... |
| `span_id` | Tool call id. Pairs a `PreToolUse` line with its `PostToolUse`/`PostToolUseFailure` line; the time between them is the call's duration (it includes time spent waiting for permission prompts) |
| `repo` | Repo under `repos/` that the call touched, found from the command or path |

What was called, depending on the tool:

| Field | Tool | Meaning |
|---|---|---|
| `cmd` | Bash, PowerShell | The command, secrets masked, cut to 500 characters |
| `desc` | Bash, PowerShell, Agent | The short description given with the call |
| `background` | Bash, PowerShell | `true` if run in the background |
| `path` | Read, Edit, Write, NotebookEdit | File path |
| `subagent` | Agent | Subagent type, e.g. `repo-fixer` |
| `prompt_chars` | Agent, UserPromptSubmit | Length of the prompt (the text itself isn't logged) |
| `skill`, `args` | Skill | Skill name and its arguments |
| `command` | UserPromptSubmit | Slash command the message started with, e.g. `run-repo` |
| `url` | WebFetch | URL fetched |
| `query` | WebSearch | Search query |
| `pattern` | Grep, Glob | Search pattern (and `path` if given) |
| `input_keys` | other tools | Names of the input parameters only |

How it ended (on `PostToolUse` / `PostToolUseFailure`):

| Field | Meaning |
|---|---|
| `outcome` | `ok`, `error` or `interrupted` |
| `exit_code` | Exit code of a failed command |
| `error_sig` | The key error line pulled out of the output, e.g. `ModuleNotFoundError: No module named insightface`. It can also appear on a successful call whose output merely contains an error-looking line (e.g. `cat` of a log) |
| `metrics` | Numbers the harness reports for the call, e.g. `totalDurationMs`, `totalTokens` for a subagent |
| `agent_result` | Subagents only: the JSON summary the subagent ends its reply with (see below) |
| `agent_result_error` | `no json block` / `unparseable json block`: the subagent didn't return a valid summary |

## Subagent results (`agent_result`)

**repo-fixer**

| Key | Meaning |
|---|---|
| `repo`, `step` | Which repo and step failed (`install`, `models`, `launch`, `generate`) |
| `fix_round` | Which of the (max 3) fix rounds this was |
| `root_cause` | One-sentence diagnosis |
| `error_sig` / `new_error_sig` | Decisive error before the fix / after it (`null` = now succeeds) |
| `category` | `dependency`, `cuda`, `build`, `path`, `model`, `repo-bug`, `other` |
| `actions` | Commands or edits applied |
| `verified` | Whether the failing command was re-run and got further |
| `blocker` | Something that needs the user, or `null` |

**launch-verifier**

| Key | Meaning |
|---|---|
| `repo`, `verdict` | Repo and `PASS` / `FAIL` |
| `provider` | Execution provider used: `cuda`, `cpu`, `unknown` |
| `port_open` | Whether the expected port was open (`null` if no port) |
| `decisive_lines`, `warnings` | Key log lines and non-fatal warnings |

**repo-triage**

| Key | Meaning |
|---|---|
| `recommended` | Recommended repos, in order to try |
| `maybe`, `out_of_scope`, `excluded`, `unverified` | Counts for each list |
| `github_queries` | Number of GitHub searches made |

## Debug field

| Field | Meaning |
|---|---|
| `payload_keys` | Only when `AGENT_TRACE_DEBUG=1` is set: the raw hook payload's field names, for discovering new ones |

## Redaction

Before anything is written, Hugging Face (`hf_...`), GitHub (`ghp_...`) and `sk-...` keys, bearer tokens,
and `token=` / `api_key=` / `password=` / `secret=` values are replaced with `***`.
