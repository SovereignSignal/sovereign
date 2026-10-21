# Gated Session Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A quiet Claude Code session yields zero to three short captures in its own raw lane, through the curator's provider and gate. Transcripts never enter the archive; secrets are redacted before any model or file sees them. Off until the owner turns it on after the Preview.

**Architecture:** `lib/session_ingest/` reads `~/.claude/projects/*/*.jsonl` on the tool's Mac, filters without a model, refuses sessions that ran inside an archive, builds a bounded redacted excerpt in memory, and makes one call per session through `lib/curator_inference.py` (the curator's provider path and guard, moved out of `bin/curator-run`). Survivors go through `bin/sov-capture` into `raw/tools/claude-code-<host>/sessions/`, published by `mirror-common.sh`'s strict redaction pass like every write wire.

A second manifest entry, `claude-code-sessions`, runs `sessions.sh` on the shared tick; state lives under `$SOV_STATE_DIR`. `sov ingest sessions` is the Preview and switch. `curator-run` always screens `raw/tools/*/sessions/` and withholds every gear from it. The app gains a Settings section, a Sources count and a Review line.

**Tech Stack:** Python 3.9 stdlib, bash, `unittest` with loopback `ThreadingHTTPServer` model stubs, `node` view tests, Swift bridge cases.

**Spec:** `docs/specs/2026-10-21-gated-session-ingestion-design.md` (binding). Owner rulings: ship off; session captures start ask-first with their own record outside existing grants; on a client Mac of a hub archive, capture stays off and the UI says why.

## Global Constraints

- `bin/` and `lib/` run on Python 3.9 (no `match`, `X | Y` types, `removeprefix`). Check new `.py` files with `/usr/bin/python3 -m py_compile`.
- No owner name, host, path or domain in a shipped file (`tests/test_template_is_general.py`).
- Transcripts never enter the archive. Fixtures are synthetic JSONL the test writes, never real session text; key-shaped values are concatenated (`'gh'+'p_'+'A'*36`).
- Redaction at the write boundary: `brain_redact.redact_text` plus `sovereign_intake.selection.secret_hits` on the excerpt, `sov-capture` on the card, `sov_redact --strict` before publish.
- Model calls only via `curator_inference.chat` after `violations` is empty; no `urllib` in `session_ingest`.
- Config, watermark and counters under `$SOV_STATE_DIR` (default `~/.local/state/sovereign`). Tests set it, `HOME`, `BRAIN_ROOT` and `BRAIN_HOST=testhost` to temp values, with a synthetic `~/.claude/projects/` tree.
- One commit per task on `feat/session-ingestion`, ending with a `Co-Authored-By:` trailer naming the writing model.
- UI strings and docs: no em or en dashes, no "not X but Y", none of foster, crucial, significantly, comprehensive.

Test commands, from the worktree:

```sh
export PYTHONPATH=$PWD/lib SOV_PYTHON_RUNTIME=$SOV_RUNTIME_COPY
PY=$SOV_TEST_PYTHON
$PY -m unittest -v tests.<module>
node apps/console/tests/<suite>.cjs
```

---

### Task 1: Shared inference module

**Files:** Create `lib/curator_inference.py`. Modify `bin/curator-run`, `bin/sov-curator`. Test `tests/test_curator_inference.py`.

**Interfaces (consumed by Task 4, Task 8):**
- `PROVIDERS`, moved verbatim from `bin/curator-run:89`.
- `inference_violations(endpoint, model, screen_model, allow_remote, local_hosts=("localhost","127.0.0.1","::1","0.0.0.0"), backend="openai", local_only=False, provider="") -> list`, moved verbatim from `bin/curator-run:799`.
- `config_from_env(env) -> dict` with keys `provider, backend, endpoint, model, screen_model, local_only, allow_remote, keychain_service, keyfile, reasoning_effort, anthropic_effort`, same precedence as `bin/curator-run:104-149` today.
- `violations(cfg) -> list` (wraps the above).
- `load_key(cfg, env) -> str`: keyfile, then `CURATOR_KEY`, then `/usr/bin/security find-generic-password -s <keychain_service> -w` when a provider is set.
- `chat(cfg, key, model, temperature, messages, timeout) -> str`: `_post_json`, `_chat_body`, `_anthropic_body`, `_chat` moved from `bin/curator-run:2097-2172`; `local_only` read from `cfg`, never `os.environ`.
- `chosen_provider(state_dir) -> str`: reads `curator-provider.json`, default `anthropic`.

- [ ] **Step 1: failing tests.** `test_violation_table` repeats the `--self-test` guard rows (loopback clean; hosted endpoint, `:cloud` model or screen model, anthropic under `local_only`, wrong host refused; `allow_remote` clean). `test_config_precedence`: bare `CURATOR_BACKEND=anthropic` gives provider `anthropic`; `CURATOR_PROVIDER=openai` pins its host. `test_chat_openai_shape`: the stub sees `response_format.type == "json_object"`. `test_local_only_refuses_redirect`: a 302 raises. `test_chosen_provider`: missing file or unknown value gives `anthropic`, `{"provider":"grok"}` gives `grok`.
- [ ] **Step 2:** run, expect `ModuleNotFoundError`.
- [ ] **Step 3:** create the module. `bin/curator-run` keeps `PROVIDERS`, `_inference_violations`, `_chat`, `ENDPOINT`, `MODEL`, `KEY` as aliases so the self-test and call sites stay unchanged (`def _chat(model, t, msgs, timeout): return curator_inference.chat(_CFG, KEY, model, t, msgs, timeout)`). `bin/sov-curator`'s `provider()` uses `chosen_provider(STATE)`.
- [ ] **Step 4:** `$PY -m unittest -v tests.test_curator_inference`, `$PY bin/curator-run --self-test` (pass count unchanged), `$PY -m unittest discover -s tests -p 'test_curator_*.py'`.
- [ ] **Step 5:** commit.

**Done when** the self-test count is unchanged and curator tests pass.

### Task 2: Transcript reader and excerpt builder

**Files:** Create `lib/session_ingest/{__init__,claude_code,excerpt}.py`, `tests/session_fixtures.py`. Test `tests/test_session_excerpt.py`.

**Interfaces:**
- `session_ingest.READERS = {"claude-code": claude_code}`. Codex seam: any module with `TOOL`, `LANE_PREFIX`, `list_transcripts(home)`, `scan(path, cwd_check=None)`; a later `codex.py` plugs in with prefix `codex-memory`.
- `claude_code.list_transcripts(home) -> list[str]`: `glob(home/.claude/projects/*/*.jsonl)`, symlinks skipped; one level deep, so `subagents/`, `tool-results/`, `workflows/` are never reached.
- `claude_code.scan(path, cwd_check=None) -> dict`: streaming, malformed lines skipped. Keys: `id` (`sessionId`, else file stem), `path, size, mtime`, `cwds` (distinct `os.path.realpath` values in order), `entrypoint` (first non-null), `sidechain` (any `isSidechain` true), `title` (last `ai-title.aiTitle`), `first_ts, last_ts`, `turns: [{"n", "prompt", "assistant": [str], "tools": [str]}]`, `stopped`. `cwd_check(realpath)` runs per new cwd; non-None sets `stopped`, empties `turns`, ends the read.
- Typed prompt: `type == "user"`, `isMeta` falsy, no `toolUseResult` key, content a string or a list of only `text` blocks; text starting `<system-reminder>`, `<command-` or `<local-command-` is dropped. It opens a turn; assistant `text` and `tool_use` names append to it. Dropped: `thinking`, tool inputs and results, `api-request*`, `system`, `file-history-*`, `queue-operation`, every `attachment` (including `hook_success`).
- `excerpt.build(turns, hit_turns=frozenset(), cap=24000) -> (text, turn_ids)`: lines `T4 user: …` (cut at 1,500 characters, `…` appended), `T4 assistant: …` (each block cut at 600), `[tool: Edit]` (consecutive repeats become `[tool: Edit] x3`). Over the cap: T1 to T3, every hit turn, then the latest that fit; each gap is one line `[T5..T11 omitted]`. `turn_ids` = turns kept.
- `excerpt.clean(text) -> (text, dropped)`: `redact_text`, then every line where `secret_hits` is non-empty becomes `[line dropped]`.
- `tests/session_fixtures.py`: `make_home(tmp) -> (home, vault, state)` (vault via `brain_local.create`), `transcript(home, key, sid, cwd, prompts, entrypoint="cli", sidechain=False, age_s=3600, assistant="Done.", extra_cwds=())` writing every line kind above, one marker each (`MARK-HOOK` in `hook_success`, `MARK-CONTEXT` in `hook_additional_context`, `MARK-THINK`, `MARK-TOOLIN` in a tool input, `MARK-RESULT` in a tool result, `MARK-SYSTEM`, `MARK-BLOB`, `MARK-SNAP`, `MARK-QUEUE`), plus `MARKERS`, `KEYS` and `ModelStub(reply_fn)` (loopback server exposing `.url`, `.requests`, `.calls`).

- [ ] **Step 1: failing tests.** `test_lists_top_level_only` (nothing under `subagents/`, `tool-results/`). `test_no_marker_survives` (no `MARK-*` in `build` output). `test_keys_redacted` (no `KEYS` value after `clean`). `test_cuts` (2,000-character prompt gives 1,500 plus `…`; 900-character text gives 600). `test_numbering_and_tools`. `test_cap` (40 turns of 900 characters, hits `{20}`: at most 24,000, holds T1 to T3, T20, T40 and an omitted line). `test_metadata`. `test_cwd_check_stops`. `test_malformed_line_skipped`.
- [ ] **Step 2-5:** run (fail), implement, `$PY -m unittest -v tests.test_session_excerpt`, commit.

**Done when** the marker half of the spec's boundary test passes here.

### Task 3: Config, watermark, privacy gate, pre-filter

**Files:** Create `lib/session_ingest/{state,privacy,prefilter}.py`. Test `tests/test_session_prefilter.py`, `tests/test_session_state.py`.

**Interfaces:**
- Config `$SOV_STATE_DIR/session-capture.json`, defaults:
  `{"version":1,"tools":{"claude-code":{"enabled":false,"enabled_at":null}},"allow":[],"deny":[],"quiet_min":45,"min_prompts":3,"min_score":2,"entrypoints":["cli"],"budget":{"calls_per_tick":3,"chars_per_tick":60000,"calls_per_day":30},"phrases":{"memory":[],"decision":[],"correction":[]}}`. Instance phrases extend the defaults. `load_config(sd)`, `save_config(sd, cfg)` (atomic, mode 600).
- Watermark `$SOV_STATE_DIR/sessions/<tool>.json`: `{"sessions":{id:{"size","mtime","cwd","project","verdict","attempts","captures","distiller","prompt","at","policy"}},"waiting":{"reason","since"}|null}`. `state.Watermark(sd, tool)` with `.rows`, `.stage(id, row)` (writes `<tool>.json.pending`), `.commit()`, `.discard()`. Calls in `sessions/<tool>.calls.json` `{date: n}`, written per call, 7 days kept: `.calls_today(date)`, `.record_call(date)`.
- `state.needs_look(row, size, policy) -> bool`: no row yes; `distilled` never (final when the file grows); `failed:<n>` while n < 3; `skipped:*` on size change; `denied`/`refused-archive` on size change or `row.policy != policy`.
- `privacy.archive_like(path) -> bool`: walk the path and its ancestors with `os.stat`/`os.listdir`. True where `CLAUDE.md` sits beside `knowledge/` and `raw/`. A `PermissionError` counts as True (fail closed, the TCC case).
- `privacy.make_cwd_check(vault, cfg) -> fn(realpath) -> "refused-archive" | "denied" | None`: inside `realpath(vault)` or `archive_like` gives refused, and the allow list never overrides it. Then deny prefixes; temporary roots (`/tmp`, `/private/tmp`, `/var/folders`, `/private/var/folders`, `$TMPDIR`) are off unless allowed. Prefix test `p == x or p.startswith(x + "/")`. `policy_hash(cfg)`: sha1 of sorted allow and deny.
- `prefilter.quiet(size, mtime, row, now, quiet_min) -> bool`: mtime at least 45 minutes old and, when a row exists, size equal to its size.
- `prefilter.check(s, cfg, floor_epoch, card_stems) -> (verdict|None, score, hit_turns)`, reasons in order: `skipped:entrypoint`, `skipped:sidechain`, `skipped:few-prompts` (under 3), `skipped:before-enable` (`last_ts` not after the floor), `skipped:low-signal` (score under 2, no memory phrase). Case-insensitive word-boundary match on typed prompts. Defaults: memory "remember", "from now on", "always", "never again", "note that"; decision "let's go with", "decided", "switch to"; correction "that's wrong", "actually", "not what I asked". One point per turn per category. New names (a capitalised term, not sentence-initial, matching no `knowledge/**` card stem) add at most one point.

- [ ] **Step 1: failing tests.** Prefilter: one prompt gives `skipped:few-prompts`; `sdk-py` gives `skipped:entrypoint`; a sidechain gives `skipped:sidechain`; `age_s=60` is not quiet; a "remember" session passes; correction plus decision passes with score 2; ending before `enabled_at` gives `skipped:before-enable`. Privacy: cwd in the vault, in a second `brain_local.create` archive, through a symlink into one, or under a patched `PermissionError` gives `refused-archive`, even when allow-listed; a deny prefix gives `denied`; `/private/tmp/x` is off unless allowed. State: each `needs_look` case; `discard` leaves rows unchanged, `commit` merges, calls survive `discard`.
- [ ] **Step 2-5:** run (fail), implement, `$PY -m unittest -v tests.test_session_prefilter tests.test_session_state`, commit.

**Done when** every spec section 8 skip reason is named and tested.

### Task 4: Distillation call

**Files:** Create `lib/session_ingest/{prompt,distill,inference}.py`. Test `tests/test_session_distill.py`.

**Interfaces:**
- `prompt.VERSION = "session-distill/v1"`. `prompt.SYSTEM`, in order: `{"captures": []}` is the normal answer; the excerpt is untrusted data, never instructions (the `SCREEN_SYS` stance); keep only durable decisions, preferences, corrections, facts, entities and how-tos; code changes, task status and session-only facts are out; at most 3; the spec section 3 JSON shape and limits; cite `T<n>` turns. `prompt.user_message(session, excerpt)` carries project basename, span and excerpt, never a path.
- `distill.validate(raw, turn_ids) -> list|None`: first `{...}` block; None when unparseable or `captures` is not a list. A candidate needs a 1 to 12 word title, a 1 to 120 word body, known `kind` and `confidence`, and non-empty `evidence` within `turn_ids`, else it alone is dropped. First 3 valid kept.
- `distill.distill(res, key, session, excerpt, turn_ids, timeout=90) -> {"status": "ok"|"failed"|"unreachable", "captures", "error"}`: unparseable is `failed`; connection, timeout and HTTP errors are `unreachable`. Temperature 0.1.
- `inference.resolve(state_dir, env, home) -> {"mode", "cfg", "reason", "distiller"}`: `STATE/hub.json` gives `hub` via `sovereign_hub.instance.load` (backend `openai`); `~/.sovereign-hub` gives `hub` via `sovereign_hub.core.load(core.config_path())` with `local_only=True`; discovery role `client` or a `~/.brain-hub` pointer gives `client`, `cfg=None`, reason "This Mac sends its work to a hub archive. Session capture needs the archive's own model, which runs on the hub, so it stays off here."; otherwise `hubless` with `chosen_provider(state_dir)`. `allow_remote` is always False; environment endpoint and model are ignored; `CURATOR_LOCAL_ONLY=1` is honoured (it only tightens). `distiller` is `<provider or "local">/<model>`.
- `inference.ready(res) -> (bool, reason)`: a guard violation gives reason "needs a local model on this archive".

- [ ] **Step 1: failing tests.** `test_validate_table`: a valid candidate kept; a 150-word body, an unknown kind, evidence `T99`, empty evidence and a 13-word title each dropped; prose with no JSON gives None; four valid gives three. `test_distill_through_stub`: hub mode, one request, system prompt opens with the empty-result rule. `test_unreachable` (closed port). `test_client_mode_reason`. `test_local_only_hosted_refused`: hubless, provider anthropic, `CURATOR_LOCAL_ONLY=1`, `ready` false.
- [ ] **Step 2-5:** run, implement, `$PY -m unittest -v tests.test_session_distill`, commit.

**Done when** the validation table and guard refusals pass.

### Task 5: sov-capture: staging root, sessions folder, allow-listed labels

**Files:** Modify `bin/sov-capture`. Test `tests/test_capture_meta.py`; rerun `tests/test_capture_boundary.py`, `tests/test_capture_labels.py`.

**Interfaces (consumed by Task 6):**
- Root: when `raw/workspaces/<lane>` exists in the vault, the vault as today. Otherwise `$BRAIN_STAGE` or `$SOVEREIGN_STAGE`, else `~/.vault-staging` when it is a directory, gives `<stage>/raw/tools/<lane>` (the `sov_dest` order, `mirror-common.sh:32-39`). Otherwise the vault as today. The fence checks against the chosen root; the git-branch step runs only for vault lanes.
- `--subdir sessions`: the only accepted value. The destination is `<lane dir>/sessions/`, and a symlink there is refused.
- `--meta key=value`, repeatable, each key once. Allowed keys with checks: `session_title`, `project` (single line, 200 characters or fewer, written through `_label`); `span` (`^\d{4}-\d\d-\d\dT\d\d:\d\dZ\.\.\d{4}-\d\d-\d\dT\d\d:\d\dZ$`); `distiller` (`^[a-z0-9.-]+/[A-Za-z0-9._:-]+$`); `prompt` (`^[a-z0-9-]+/v\d+$`); `kind` (`decision|preference|correction|fact|entity|howto`); `confidence` (`high|med|low`); `evidence` (`^T\d+(,T\d+)*$`, written `[T4, T9]`). Anything else exits 64. Frontmatter order follows spec section 2.

- [ ] **Step 1: failing tests.** `test_meta_written_in_order` (PyYAML when present: `evidence == ["T4","T9"]`); unknown key, bad kind and repeated key refused; `--subdir ../x` refused; `BRAIN_STAGE=<tmp>` lands under `<tmp>/raw/tools/claude-code-testhost/sessions/` with the vault untouched; a workspace lane ignores the stage.
- [ ] **Step 2-5:** run, implement, the three capture suites, commit.

**Done when** the new and existing capture suites pass.

### Task 6: The tick: run module, sessions.sh, install

**Files:** Create `lib/session_ingest/run.py`, `connectors/harness/claude-code/sessions.sh`. Modify `install.sh` and `LANE.md.tmpl` beside it, `connectors/harness/_lib/install-common.sh`. Test `tests/test_session_e2e.py`, `tests/test_session_watermark.py`, `tests/test_session_boundary.py`.

**Interfaces:**
- `run.candidates(tool, env, now, since=None) -> list[dict]`, no calls or writes: `id, project, quiet_age_s, prompts, score, verdict, excerpt_chars, est_tokens` (characters / 4); `since` lowers the enable floor (opt-in backfill).
- `run.tick(tool, env, dest_dir, now) -> summary`: refuses when off or `inference.ready` fails. Oldest-quiet first. Budget: 3 calls and 60,000 excerpt characters a tick, 30 calls a day; 90 s per call, no new call after 180 s (inside the runner's 300 s). Calls are recorded at once; rows are staged only. Each candidate becomes `sov-capture <kebab(title)[:50]>-<id[:8]> --lane <lane> --subdir sessions --from - --title … --origin claude-code-session:<id> --meta …` under `sys.executable` with `BRAIN_STAGE=<private stage>`. `unreachable` leaves the session pending and sets `waiting`. Exit 1 only when a capture write fails.
- `run.commit(tool, env)` merges pending rows. `run.write_manifest(dest_dir, lane, wm, now)` writes `sessions/MANIFEST.md` in `sov_manifest`'s shape plus `Sessions this week: distilled 3, captures 2, skipped 41, waiting 1, failed 0, refused 1.` and, when set, `Waiting: model unreachable since 2026-10-21T14:05Z.`
- `sessions.sh`: source `mirror-common.sh`; `LANE=claude-code-$BRAIN_HOST_RESOLVED`; `sov-ingest sessions --gate` (exit 3 means off: exit 0 silently); `sov_prepare "$LANE/sessions" "claude-code/sessions"`; move `$DEST` to `$SOV_PRIVATE/stage/raw/tools/$LANE/sessions`; `sov-ingest sessions --tick --dest "$DEST"` (`failed=1` on exit 1); `sov_finish "Claude Code session capture"`; then `--commit-tick` on success, `--discard-tick` on failure so sessions retry.
- `install-common.sh`: `sov_register_extra_wire <id> <script> <cadence> <timeout>` upserts `claude-code-sessions` with `lane_dir=$LANE_DIR/sessions`, cadence 900, timeout 300, `parent=$HARNESS`; `remove-harness <h>` also removes entries whose `parent == h`. `install.sh` calls it after `sov_register_connector`. `LANE.md.tmpl` gains: "Session capture: `sessions.sh` distils quiet sessions into `sessions/`, off until the owner turns it on. Transcripts never cross."

- [ ] **Step 1: failing tests**, through `sessions.sh`, with a `hub.json` pointing at `ModelStub` and capture on. E2E: one valid candidate plus one 150-word body lands exactly one file with every spec label, and `curator-run --dry` against a judging stub reports `judged 1 new item`; an empty result writes nothing and marks `distilled`. Watermark: a second pass makes zero calls; a grown distilled file makes zero calls; 500 then valid gives `failed:1` then `distilled`; `calls_per_tick: 1` with 3 eligible drains over 3 ticks; a forced `sov-redact` failure discards staged rows. Boundary: no vault `.jsonl`; no `MARK-*` or `KEYS` value in any capture or `stub.requests`; archive cwds (vault, second archive, symlink) are `refused-archive` with zero calls. Off by default: a fresh install calls nothing and writes nothing.
- [ ] **Step 2-5:** run, implement, `$PY -m unittest -v tests.test_session_e2e tests.test_session_watermark tests.test_session_boundary tests.test_connector_claude_code tests.test_connectors_install tests.test_connectors_runner` (update assertions that count one manifest entry per install), commit.

**Done when** e2e, watermark and boundary suites pass.

### Task 7: `sov ingest sessions`

**Files:** Create `lib/session_ingest/cli.py`. Modify `bin/sov-ingest` (when `argv[1] == "sessions"`, hand off to `cli.main(argv[2:])` before argparse), `bin/sov` usage comment. Test `tests/test_session_cli.py`.

**Interfaces:**
- `sov ingest sessions [--tool claude-code] [--since 30d] [--json]`: the dry plan plus budget left; no call, no write. `--show <id>`: the cleaned excerpt.
- `--apply`: runs `sessions.sh` once; refused while off ("Session capture is off. Turn it on with `sov ingest sessions --on` after looking at the preview.").
- `--on`: prints the plan, then sets `enabled` and `enabled_at`; refused in client mode or when `ready` fails, with the reason. `--off`. `--allow`/`--deny <path>` store realpaths and drop them from the other list.
- `status [--json]` → `{"tool","enabled","available","mode","reason","distiller":{"provider","model","name"},"budget":{"calls_per_tick","calls_per_day","chars_per_tick","used_today"},"week":{"distilled","captures","skipped","waiting","failed","refused"},"waiting":null|{"reason","since"},"projects":[{"path","label","sessions","on","kind":"normal|temp|archive","denied"}],"next":[{"tool":"codex","label":"Codex"}]}`. Projects cover cwds seen in 30 days, reading only up to the first cwd of a file without a row.
- `--where <id>`: the watermark row's cwd (Task 10). Internal, for `sessions.sh`: `--gate`, `--tick --dest <dir>`, `--commit-tick`, `--discard-tick`.

- [ ] **Step 1: failing tests.** Dry plan and `--show` against a stub that fails if called: zero calls, vault tree hash unchanged, no watermark. `--apply` while off refused. `--on` writes `enabled_at`. `--on` in client mode exits nonzero with the reason. Hosted provider under local-only, `https_proxy` at the stub: zero requests. `status --json` matches the shape, a `/private/tmp` project `temp` and off. `--deny` then `--allow` leaves the path only in allow.
- [ ] **Step 2-5:** run, implement, `$PY -m unittest -v tests.test_session_cli tests.test_ingest_folder`, commit.

**Done when** the dry run proves zero calls and writes.

### Task 8: Curator: forced screen, ask-first record

**Files:** Modify `bin/curator-run`. Test `tests/test_curator_sessions.py`, new `--self-test` rows.

**Interfaces:**
- `_session_source(rel) -> bool`: matches `^raw/tools/[^/]+/sessions/[^/]+\.md$`.
- Screen call (`bin/curator-run:2306`): `_screen_source(_judge_text(p), SCREEN or _session_source(src), _screen_call)`; an unreachable screener flags the source.
- Session proposals, `.meta.json` and `judgments.jsonl` rows carry `"input_class": "session"`; `_auto_promote` and `_auto_reject` skip them ("session capture: new input class, ask-first until it earns its own record"). The judgments rows are that record.

- [ ] **Step 1: failing tests.** Self-test rows: `raw/tools/claude-code-h/sessions/x.md` true, `.../memory/x.md` false. Integration with stubs (judge promotes a high concept, screen flags, `CURATOR_SCREEN` empty, `gears.json` grants high new concepts, `ARCHIVIST_AUTO_PROMOTE_MAX=12`): the session capture gives a `[SCREENED]` proposal left in `proposals/` with `input_class` in `.meta.json`; a clean screen still leaves it pending, zero auto-promoted; a non-session source under the same grant is unaffected.
- [ ] **Step 2-5:** run, implement, `$PY bin/curator-run --self-test`, `$PY -m unittest -v tests.test_curator_sessions`, the `test_curator_*` suites, commit.

**Done when** session sources never ride a gear.

### Task 9: Settings: Session capture section

**Files:** Modify `apps/console/ui/settings-view.js`, `apps/console/ui/settings-view.css`, `apps/console/ui/index.html`, `apps/console/main.swift`. Test `apps/console/tests/settings-view.cjs`.

**Interfaces:**
- Bridge `{cmd:"sessions", action}`, actions `status|preview|on|off|allow|deny` (`path`: absolute, at most 1,024 characters, no newline) mapped to the Task 7 commands; answers `sessionsResult {action, exit, out, err}`.
- `sessionSection(X)` (ctx key `sessions`) renders between Curator and Import. Unread: "Checking…". `mode === "client"`: lead "Session capture is off on this Mac." plus the reason, no controls. Otherwise unavailable: the reason, no switch. Otherwise: "Claude Code: distill quiet sessions into its lane"; "Codex: next"; "Uses your curator's provider: <name>"; one checkbox per project with its session count (`data-ses-path`, temporary folders unchecked) and the fixed row "Inside an archive: never"; "Up to 3 sessions a tick and 30 a day, oldest first."; Preview. While off, Turn on (`set-ses-on`) appears only after a Preview result rendered in this pane (`ctx.sessionsPreviewed`).

- [ ] **Step 1: failing tests** in `settings-view.cjs`: client mode shows the reason and no `set-ses-on`; off before preview has no Turn on, after preview has it; on shows week counts and Turn off; temp project unchecked, archive row fixed; section order Curator, Session capture, Import; no em or en dash in any string.
- [ ] **Step 2-5:** run, implement, `node apps/console/tests/settings-view.cjs`, commit.

**Done when** `settings-view.cjs` passes.

### Task 10: Sources count, Review line, Open session

**Files:** Modify `bin/sov-status`, `apps/console/ui/status-model.js`, `apps/console/ui/gate-model.js`, `apps/console/ui/index.html`, `apps/console/main.swift`. Test `tests/test_brain_status_sessions.py`, `apps/console/tests/sources.cjs`, `apps/console/tests/gate-model.cjs`.

**Interfaces:**
- `sov-status`: each harness row gains `sessions: {distilled, captures, skipped, waiting, failed, refused, waiting_reason}` from `<lane_dir>/sessions/MANIFEST.md`, or null. A proposal whose `source` matches `raw/tools/*/sessions/` gains `session: {id, title, project, span, evidence, local}` from the capture's frontmatter (realpath inside the vault); `local` when `~/.claude/projects/*/<id>.jsonl` exists.
- `SovStatus.sessionLine(s)`: "3 sessions distilled this week, 2 captures · 41 skipped · 1 waiting" (zero parts after the first omitted), or amber "waiting: model unreachable since 14:05". Rendered as the Sources fact "Sessions".
- `GateModel.sessionLine(p)`: "From a Claude Code session: <title>, <project>, <span>, turns T4, T9".
- Open session, when `local`: bridge `{cmd:"sessions", action:"resume", id}` checks the id is a UUID, reads the cwd from `sov ingest sessions --where <id>`, and runs `NSAppleScript` `do script "cd " & quoted form of <cwd> & " && claude --resume <id>"` in Terminal.

- [ ] **Step 1: failing tests.** Python: synthetic lane and proposal give both fields; no manifest gives null; a `source` outside the vault gives no `session`. JS: `sessionLine` incl. all-zero and waiting; `GateModel.sessionLine` with and without `evidence`.
- [ ] **Step 2-5:** run, implement, the three suites plus `$PY -m unittest discover -s tests -p 'test_brain_status_*.py'`, commit.

**Done when** all three suites pass.

### Task 11: Documentation

**Files:** Modify `connectors/harness/claude-code/README.md` ("Session capture": what is read and dropped, where the call runs, off by default, Preview, client Macs, budget, undo), `CHANGELOG.md` (top entry `## 0.9.0 "Capture" (unreleased)`), `harness.json` description.

- [ ] Write; `$PY -m unittest -v tests.test_template_is_general`; grep for dashes and the banned words; commit.

**Done when** the generality test passes.

## Verification before merge

- [ ] Full suites (`docs/release-checks.md`), plus the Python 3.9 `py_compile` check:

```sh
$PY -m unittest discover -s tests -v
$PY -m unittest discover -s apps/console/tests -p 'test_*.py' -v
for suite in apps/console/tests/*.cjs; do node "$suite" || exit; done
$PY bin/curator-run --self-test
```

- [ ] Manual dry run in a scratch HOME and `SOV_STATE_DIR`: `brain_local.create` an archive, write three transcripts with `session_fixtures.transcript` (passing, one-prompt, cwd inside the archive), run `sov ingest sessions`, `--show <id>`, `status --json`. Expect one candidate, `skipped:few-prompts`, `refused-archive`, no model call, archive unchanged.
- [ ] The final report contains: suite totals with baseline failures kept separate; the self-test count before and after Task 1; the dry-run output; `find <archive> -name '*.jsonl'` printing nothing; a grep of captures and stub request logs showing no `MARK-` and no key shape; the commit list; open seams (Codex reader, hub endpoint for client Macs, a session-class gear grant).
