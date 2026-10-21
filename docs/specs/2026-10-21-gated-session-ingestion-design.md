# Gated session ingestion (v0.9.0 "Capture", issue #6)

Status: draft for owner review. Scope: Claude Code first, Codex behind the same contract.

## 1. Problem and goal

The Claude Code lane receives only the tool's memory folders (`connectors/harness/claude-code/mirror.sh:4-7`), so a decision that never reached a memory file is lost. claude-mem shows people expect sessions to be remembered automatically, and it also shows the cost: it stored planted keys verbatim (`ROADMAP.md:29-31`). The goal is the same automatic capture with the trust story intact: a quiet session yields zero or more short candidate captures in the tool's own raw lane, and nothing else. Transcripts never enter the archive, secrets are redacted before any model or file sees them, and the curator's gate decides what becomes trusted (`CLAUDE.md:70-73`, `:93`). Most sessions yield nothing, and that is the system working (`CLAUDE.md:77`).

## 2. Pipeline

1. **Tick.** The connector runner (`bin/sov-connectors-run`) runs a new manifest entry `claude-code-sessions`, separate from the memory mirror so a slow model call cannot stall it; cadence 900 s, `timeout_s` 300, under the tick (`bin/sov-connectors-run:246`). New: `connectors/harness/claude-code/sessions.sh`.
2. **List.** Walk `~/.claude/projects/*/*.jsonl` only; `subagents/`, `tool-results/` and `workflows/` are never read. New: `lib/session_ingest/claude_code.py`.
3. **Pre-filter** (section 4): metadata and typed prompts only, no model, checked against the watermark. New.
4. **Privacy gate.** Resolve every distinct `cwd` field in the file with `realpath`. Refuse if any lies inside this archive, inside anything that looks like an archive (`CLAUDE.md` beside `knowledge/` and `raw/`), or on the deny list. The `projects/` folder name is a lossy path encoding and is never used for this. New.
5. **Excerpt.** Build a bounded excerpt (section 3), then run `redact_text` (`lib/brain_redact.py:88`) and drop any line that still trips `secret_hits` (`lib/sovereign_intake/selection.py:57-58`). The excerpt lives only in memory.
6. **Inference guard.** Before any call, apply the curator's guard `_inference_violations` (`bin/curator-run:799`) to the archive's one provider; a local-only archive refuses every hosted one (`:833-834`). The guard and `_chat` (`:2153`) move into a shared `lib/curator_inference.py` so both callers obey one law.
7. **Distill.** One call per session (section 3). New: `lib/session_ingest/prompt.py`, versioned.
8. **Write.** Each surviving candidate goes through `sov-capture` (`bin/sov-capture:123-144`: frontmatter, redaction, path fence, never-overwrite) into `raw/tools/claude-code-<host>/sessions/`. `sov-capture` gains staging-root resolution matching `sov_dest` (`connectors/harness/_lib/mirror-common.sh:32-39`) and an allow-listed `--meta key=value`. The strict `sov-redact` pass and publish follow (`mirror-common.sh:65-75`).
9. **Heartbeat.** `sessions/MANIFEST.md` (`mirror-common.sh:161`) records this week's counts. The watermark marks the session.
10. **Curate.** `curator-run` already walks `raw/` (`bin/curator-run:1653`); session captures are judged, screened (section 5), and land only through the gate.

Capture frontmatter:

```yaml
type: capture
source: claude-code-<host>
created: 2026-10-21
title: Tests run against the staging copy
origin: claude-code-session:<session-id>
session_title: <the session's ai-title line>
project: <basename of cwd>
span: 2026-10-21T14:02Z..2026-10-21T15:40Z
distiller: <provider>/<model>
prompt: session-distill/v1
kind: decision
confidence: med
evidence: [T4, T9]
```

## 3. Distillation prompt contract

**Input.** The excerpt keeps typed prompts (`user` lines with string or text content, `isMeta` false, no `tool_result`), each cut at 1,500 characters. Assistant `text` blocks are cut at 600 characters, and a tool call becomes one line, `[tool: Edit]`. Dropped: `thinking`, tool inputs and results, `api-request-*`, `system`, `file-history-*`, and attachments, including `hook_success`, which carries the archive's own session-start pack (keeping it would capture the archive's cards back). Turns are numbered T1..Tn. Cap 24,000 characters; above it keep T1 to T3, every turn with a pre-filter hit, and the latest turns that fit. The system prompt frames the excerpt as untrusted data, the same stance as `SCREEN_SYS` (`bin/curator-run:626`).

**Output.** JSON only:

```json
{"captures": [{"title": "<= 12 words", "body": "<= 120 words, self-contained",
  "kind": "decision|preference|correction|fact|entity|howto",
  "confidence": "high|med|low", "evidence": ["T4", "T9"]}]}
```

**Rules.** `{"captures": []}` is the normal result, and the prompt says so first. At most 3 captures per session. Code changes, task status and anything true only inside this session are out of scope. Validation is strict: a body over 120 words, missing or unknown evidence turns, or an unknown kind drops that candidate. Unparseable output yields zero captures and counts as a failed attempt.

## 4. Pre-filter, budget, watermark

**Pre-filter, in order, all without a model:**
- Quiet: mtime at least 45 minutes old and size unchanged since the last tick.
- `entrypoint` is `cli`. SDK and scripted sessions (`sdk-py`, `sdk-cli`) are skipped by default.
- No `isSidechain` lines.
- At least 3 typed prompts.
- A signal score of 2 or more, or any explicit memory phrase. Points come from memory phrasing ("remember", "from now on", "always", "never again", "note that"), decisions ("let's go with", "decided", "switch to"), corrections ("that's wrong", "actually", "not what I asked") and new names (capitalised terms with no matching card filename under `knowledge/`).
- Activity after ingestion was enabled (forward-only, `CLAUDE.md:116-118`). Phrase lists are generic English defaults, extendable in instance state.

**Budget.** 3 calls and 60,000 excerpt characters per tick, 30 calls a day; oldest-quiet first, overflow waits.

**Watermark.** `~/.local/state/sovereign/sessions/claude-code.json`, one row per session: size and mtime seen, verdict (`distilled`, `skipped:<reason>`, `denied`, `refused-archive`, `failed:<n>`), captures, distiller, prompt version. `distilled` is final even if the file grows; `failed` retries twice; `skipped` is re-checked only when the size changes.

**Config.** `~/.local/state/sovereign/session-capture.json` holds `enabled` per tool, `allow` and `deny` path lists, the thresholds and the budget. Nothing owner-specific lives in code.

## 5. Where the model call runs

**Option A, connector tick on the tool's machine.** The transcript is read where it already lives. Only the redacted excerpt leaves the process, and it goes only to the archive's chosen provider, checked by the same guard the curator uses. On a hubless archive, `sov-curator` already runs on this Mac with that provider and its Keychain key (`bin/sov-curator:101-111`, `:145-150`), so nothing new is trusted.

**Option B, the curator's pass on the hub.** The hub cannot read another Mac's `~/.claude`, so excerpts would have to travel: through `raw/` they are transcript bytes in the archive, and any other route is a pipe outside the lane rule. On a hubless Mac, B would also widen the curator beyond "works only from the vault and the owner" (`CLAUDE.md:79`).

**Recommendation: A.** The deciding factor is the owner-controlled-inference rule. A sends session text to exactly one model the owner chose and copies it nowhere else. B needs a copy before any model sees it. One gap remains: on a hub archive the tool Mac is often a mirror with no owned model, and the guard refuses non-loopback endpoints (`bin/curator-run:847-849`). There, session capture stays off and says why (open question 3).

**Injection screen.** The curator screen is off by default on a hub (`bin/curator-run:148`) and on for hubless archives (`bin/sov-curator:106`). Session captures are always screened: `curator-run` treats a source under `raw/tools/*/sessions/` as screen-required whatever `CURATOR_SCREEN` says. An unreachable screener flags the source (`bin/curator-run:646-662`).

## 6. Settings, Sources and CLI

**Settings.** A new "Session capture" section between Curator and Import (`apps/console/ui/settings-view.js:139`, `:162`):
- One switch per connector ("Claude Code: distill quiet sessions into its lane"); Codex shown as next.
- The distiller, named, with no separate picker: "Uses your curator's provider".
- Projects: every folder seen in 30 days, a checkbox each (on by default) and a session count. "Inside an archive: never" is a fixed row; temporary folders start off.
- The budget line and a Preview button that runs the dry run.

**Sources.** The Claude Code lane row gains: "3 sessions distilled this week, 2 captures · 41 skipped · 1 waiting", read from `sessions/MANIFEST.md`.

**Review.** A session capture shows "From a Claude Code session: <session_title>, <project>, <span>, turns T4, T9". On the machine that holds the transcript, "Open session" runs `claude --resume <id>` in Terminal. The archive itself never holds the transcript.

**CLI.** `sov ingest sessions` is a new adapter beside `folder` (`bin/sov-ingest:181`). Like `folder`, its default is a dry plan (`bin/sov-ingest:32`).
- `sov ingest sessions [--tool claude-code] [--since 30d]` prints one row per candidate (session id, project, quiet age, typed prompts, score, verdict, excerpt size, estimated tokens) and the budget left. It makes no model call and writes nothing.
- `sov ingest sessions --show <id>` prints the redacted excerpt the model would receive.
- `--apply` runs one pass now, within budget. `--since` is also the opt-in backfill.
- `sov ingest sessions status [--json]`, `--on|--off`, `--allow <path>`, `--deny <path>`.

## 7. Failure modes

| Case | Behaviour | What the person sees |
|---|---|---|
| Model unreachable or key missing | Session stays pending; memory mirror unaffected | Sources row amber: "waiting: model unreachable since 14:05" |
| Guard refuses (local-only, hosted provider) | No call | Settings: "needs a local model on this archive" |
| Budget exhausted | Queue carries to the next tick or day | "4 waiting for budget, resumes next tick" |
| Still being written | Skipped as `active`, unmarked | Nothing until quiet |
| Project denied | Read stops at the `cwd` field; marked `denied` | Count beside the project in Settings |
| cwd inside an archive | Refused; the allow list cannot override it | "Refused: 2 sessions ran inside an archive" |
| Redaction fails | Publish refused, prior lane kept (`mirror-common.sh:66-69`) | Lane error log; red row |
| Unparseable output | Zero captures, two retries | "failed" count in the manifest |

## 8. Tests

- `tests/test_session_boundary.py`: synthetic transcripts in a temp HOME, with markers planted in tool results, thinking, hook context and attachments. After a stubbed run no vault file ends `.jsonl`, and no marker or planted `ghp_`/`sk-ant-` key appears in any capture or in the stub's recorded request. A cwd inside the vault, inside a second synthetic archive, or behind a symlink into one, is refused.
- `tests/test_session_prefilter.py`: a one-prompt session, an `sdk-py` session, a sidechain file, a fresh-mtime file and a denied project are all skipped with named reasons. A "remember" session and a correction-plus-decision session pass.
- `tests/test_session_e2e.py`: the stub returns one valid candidate and one 150-word body; exactly one capture lands with every label, and `curator-run --dry` lists it. An empty result writes nothing and marks the session `distilled`.
- `tests/test_session_watermark.py`: a second pass makes zero calls; a grown file is not redistilled; a failed call retries; budget 1 with 3 eligible drains over 3 ticks.
- Dry run and guard: a stub that raises if called stays silent for `--dry-run` and for a local-only archive with a hosted provider, and the vault tree is unchanged.

## 9. Open questions (recommended default first)

1. **Default state.** Recommend off until the owner switches it on once after seeing the Preview, over on at connect: session text is broader than memory files.
2. **Gears.** Recommend session captures start at ask-first, withheld from existing grants until they earn their own record as a new input class.
3. **Mirror machines on a hub archive.** Recommend off in v0.9.0, over widening the guard to accept the hub's owned endpoint on the private network; scope that as its own issue.
4. **Backfill.** Recommend forward-only, `--since` as explicit opt-in.
5. **Resumed sessions.** Recommend strictly once, over distilling a grown tail as a second part.
6. **Project label.** Recommend the folder basename, which carries no username, over a home-relative path.

## 10. Task breakdown

1. **Shared inference module.** Move `_inference_violations` and `_chat` from `bin/curator-run` into `lib/curator_inference.py`; curator-run imports it. Done when the curator-run self-test passes unchanged.
2. **Reader, pre-filter, excerpt.** `lib/session_ingest/{claude_code,prefilter,excerpt}.py`. Done when `test_session_prefilter.py` and the marker half of the boundary test pass.
3. **Prompt, validation, watermark, config.** `lib/session_ingest/{prompt,distill,state}.py`. Done when `test_session_watermark.py` and the e2e test pass against a stub.
4. **Write path.** `bin/sov-capture` (staging root, `--meta`), `connectors/harness/claude-code/{sessions.sh,install.sh,LANE.md.tmpl}`. Done when the boundary test and existing capture tests pass.
5. **CLI.** The `sessions` adapter in `bin/sov-ingest`, plus status counts in `bin/sov-status`. Done when the dry-run test proves zero calls and zero writes.
6. **Curator and app.** `bin/curator-run` (forced screen, withheld gears for `sessions/`), `apps/console/ui/settings-view.js`, the Sources row, the Review line, `apps/console/test-*.py`. Done when the `docs/release-checks.md` suite is green.
7. **Codex.** What differs: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` is date-partitioned; a first-line `session_meta` record carries `id`, `cwd`, `originator`, `source` and `base_instructions` (dropped); turns are `response_item` messages plus reasoning and function-call pairs; injected context arrives as user-role messages and is stripped like hook output. Lane `codex-memory-<host>/sessions/`. Done when the four test files pass on Codex fixtures.
