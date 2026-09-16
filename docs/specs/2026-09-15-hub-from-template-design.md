# Hub from the template: design

Date: 2026-09-15. Status: proposed, awaiting the owner's review. Implements move 5 of the Sovereign Workplan.

## The problem

The hub is the one piece of Sovereign nobody can rebuild. On the hub it is twenty launchd jobs, twelve of them wrapped by a hand-copied fail-loud script, running about fifteen scripts that live only in `~/brain-bin` and `~/.hermes/scripts`, beside thirty `.pre-*` copies. Instance settings (vault path, model tag, endpoint, excludes, pending limits, remotes) are `export` lines inside those scripts. Secrets and SSH keys have no durable copy. The template's managed-hub code (`lib/sovereign_hub`) already renders launchd jobs from a dictionary, but only for the app-installed hub, with three jobs and a bundled runtime, and nothing on the hub uses it. Template fixes therefore never reach what actually runs, and a dead hub means rebuilding by hand from memory.

## What this builds

One manifest of hub jobs in the template, one renderer that turns it into scheduler items, one instance file that holds everything that is Owner's rather than Sovereign's, one fail-loud runner that replaces the wrapper, and one nightly job that packages what a rebuild needs and pushes it off-site. The hub is cut over to run from the manifest, and the runbook is followed once on a throwaway machine.

Not in scope: generalizing the Hermes-stack monitors (daily health check, Proxmox and Pi monitors, Hermes self-health); rewriting any job's logic; the app's managed-hub install flow, which keeps working and gains the same renderer underneath.

## Components

### 1. The manifest: `lib/sovereign_hub/manifest.py`

A Python module holding `JOBS`, one entry per template-shipped hub job. Each entry: `id`, `description`, `program` (a path relative to the template's `bin/`), `args`, `schedule` (a calendar dict with `hour`, `minute`, optional `weekday`, or `interval_s`), `deliver` (bool: a clean run's non-empty stdout is a message), `needs` (the instance fields it reads). The jobs:

| id | program | schedule | deliver |
|---|---|---|---|
| nightly | `hub/nightly` | daily 06:00 | yes (the digest) |
| burndown | `hub/burndown` | daily 06:27 | no |
| weekly-audit | `hub/weekly-audit` | Fri 10:00 | yes |
| weekly-landed | `hub/weekly-landed` | Sun 17:00 | no |
| verdict-poll | `hub/verdict-poll` | every 60 s | no |
| autocommit | `hub/autocommit` | daily 04:30 | no |
| snapshot | `hub/snapshot` | daily 03:00 | no |
| exchange-sync | `hub/exchange-sync` | every 1800 s | no |
| fleet-watch | `sov-fleet-watch` | every 300 s | yes |
| kit | `hub/kit` | daily 03:30 | no |

The existing `core.JOBS` (nightly, audit, snapshot for the app-installed hub) becomes a view over this manifest, so both hub flavors render from one source.

### 2. The instance file: `~/.local/state/sovereign/hub.json`

Everything Owner-specific, nothing else. Written once by `sov hub init` from the values found on the machine (the current scripts' `export` lines, read by the migration step below), edited by hand after. Fields: `vault`, `lane`, `model`, `audit_model`, `endpoint`, `exclude` (list), `pending_limit`, `burndown` (since_days, max, pending_limit, keep_floor_pct), `remotes` (push targets, in order), `snapshot` (folder, keep), `notify` (telegram env file per channel: archive, alerts), `kit` (include paths, key file, targets), `offsite` (bare-repo targets for the vault and the template), `instance_jobs` (extra jobs with absolute programs and their own schedules: today the daily health check, Proxmox and Pi monitors, Hermes self-health, the node-17 macro sync, the Notion pass). The file is never copied into the template and is the first thing the kit packages.

`sov hub env` prints the instance file as shell exports (`SOVS_VAULT`, `CURATOR_LANE`, `CURATOR_MODEL`, `CURATOR_ENDPOINT`, `CURATOR_EXCLUDE`, ...), which is how the moved scripts read their settings without a rewrite.

### 3. The runner: `lib/sovereign_hub/runner.py`, invoked as `sov hub run <job>`

The fail-loud wrapper in Python, semantics copied exactly from `cron-run-hub.sh`: run the program with the instance env, capture combined output to `<state>/hub/<job>.last-output`, write `<job>.last-run` always and `<job>.last-ok` on exit 0, append one line to the hub log, on non-zero exit send an alert with the last fifteen lines through the notify channel, on `deliver` jobs send non-empty stdout as the message. Every rendered job's program is `<interpreter> -B <template>/bin/sov-hub run <job>`, where the interpreter comes from `bin/_sov-python.sh`'s resolver, never the Xcode shim. Instance jobs run through the same runner, so they get the same receipts and alerts.

### 4. Install and status: `sov hub install|status|uninstall`

`sov hub install` renders every manifest job and instance job to a launchd plist (systemd units on Linux, same shape as the connector runner), diffs against what is installed, and prints the plan: create, replace, unchanged, retire. `--apply` writes only what changed, bootstraps changed labels, and records a receipt. Labels are `com.sovereign.hub.<id>`; the old `com.sov.cron.*` labels are listed as retirable and parked to `~/Library/LaunchAgents/sovereign-retired/` only when `--retire-legacy` is passed, the way the connector migration retired per-tool jobs. `sov hub status` lists each job with its schedule, last run, last ok and last exit, from the runner's receipts, and `brain-status` reads the same receipts so the console and the health check see hub jobs without change.

### 5. The scripts move, unchanged in logic

The hub scripts that carry no Owner specifics move into `bin/hub/` as they are: the nightly digest composer, burndown, weekly audit, weekly landed review, verdict poll, autocommit, secret scan, snapshot, exchange sync. Their `export` lines are replaced by `eval "$(sov hub env)"`, and their hardcoded remotes and folders become reads of the same fields. `sov-fleet-watch` and the two notify scripts are already identical to the template's copies and simply stop being copied. The Hermes-stack monitors stay where they are and are declared as instance jobs. `.pre-*` files are not carried anywhere; git is the undo.

### 6. The kit: `sov hub kit` and the nightly `kit` job

The rebuild tarball. Inventory from the instance file: `hub.json` itself, the pointer files (`~/.brain-*`), the notify env files, the recovery key's *location* (never the key), and every path listed under `kit.include` (Owner's list will name `~/.hermes/.env` and the SSH private keys the hub uses). Encrypted with the existing capsule machinery in `recovery.py` (AES-256-GCM through `hub-crypto`, which the hub has from the installed app), written to `snapshot.folder/hub-kit/<date>.capsule`, then copied by `scp` to every `kit.targets` entry (node-12 and the Amsterdam droplet), keeping the last seven. The same job then does the off-site push from move 2: `git push --mirror` of the vault and the template to bare repos on the droplet, and writes a receipt with each remote's head and age. The daily health check gains a remote-age check on those receipts (red past 36 hours). The recovery key never leaves owner-controlled storage; the proposed default is the client at `~/.config/sovereign/hub-recovery.key` plus one offline copy, and the owner decides.

### 7. The runbook and the drill: `docs/hub-rebuild.md`

One screen: clone the template, restore the kit with the key, clone the vault from any remote, `sov hub init --from-kit`, `sov hub install --apply`, `sov hub status`. Followed once on a throwaway machine (a Parallels VM or a disposable user on the client) and timed; that run is the R rehearsal's acceptance.

### 8. Part 1 drift: `sov check --law`

`sov check` gains a comparison of the vault's `CLAUDE.md` Part 1 against the template's, section by section, and warns on any difference. The template's Part 1 is updated to the vault's in this change so the check starts clean.

## Data flow

Manifest and instance file → renderer → scheduler items → runner → receipts → status, brain-status, health check. Kit job → capsule → off-site targets → receipts → health check. Nothing in the template reads Owner's paths; nothing in `hub.json` is required to be general.

## Error handling

The runner never retries and never repairs: it records and alerts, as the wrapper does today. `sov hub install --apply` refuses to replace a plist whose label it does not own, refuses when the instance file fails validation, and rolls back created items if a bootstrap fails, as `core.activate` does. The kit job fails loudly if any target is unreachable and still keeps the local capsule. `sov hub init` refuses to overwrite an existing `hub.json`.

## Testing

Same fixture style as `tests/test_hub.py` and `tests/test_connectors_install.py`: a throwaway HOME, a stub `launchctl` on PATH, a real vault skeleton. Tests cover: manifest rendering (every job renders, labels and schedules match, program is never `/usr/bin/python3`); runner receipts and alert behaviour with a stub notify command (exit 0 with and without deliver, exit 1 alerts with the tail); install dry-run is zero-write and its plan names create/replace/unchanged/retire correctly; apply writes only changed plists and rolls back on a failed bootstrap; instance jobs render through the runner; `sov hub env` round-trips the instance file; the kit inventory includes exactly the declared paths and refuses the key file; the kit capsule restores byte for byte; the Part 1 check passes on the template and fails on a mutated copy. The full suite runs on system Python and the 3.12 venv before the packet, as today.

## Cutover on the hub, owner-approved moment

1. `sov hub init` writes `hub.json` from the current scripts' values; Owner reviews it.
2. `sov hub install` dry run: the plan shows ten new labels and twelve retirable old ones.
3. Between jobs (after the 06:27 burndown, before the 09:00 health check), `sov hub install --apply --retire-legacy`. Old plists parked, restorable with one `launchctl bootstrap` each.
4. The next scheduled runs are watched from receipts; the 09:00 health check and the console show the new labels.
5. Rollback is bootstrapping the parked plists back and `sov hub uninstall`.

## Decisions the owner holds

- The recovery key's two locations (default proposed above).
- The `kit.include` list: which of the eight SSH keys and which env files are worth carrying.
- The cutover moment.

## Effort

Manifest, instance file, runner and install: one day. Moving the scripts and the hub dry run: half a day. Kit, off-site push and the health-check line: half a day. Runbook and the drill: half a day, run cold. Two to three days in all, as the Workplan estimated.
