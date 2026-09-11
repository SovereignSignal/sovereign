# Local Hub setup and recovery

The macOS app can prepare one independent Hub from an existing archive. Open **Operations → Hub → Hub setup and recovery**. Every change starts with a preview. Preparing the Hub copies its tools and Python runtime into the chosen folder, creates a curator lane, and leaves schedules inactive.

This package supports Apple silicon Macs running macOS 13 or later. Install a local model server separately and choose a model it already has. The endpoint must be loopback HTTP; cloud models, credentials, proxies and redirects are refused in managed curation. The model check confirms availability, not judgment quality. Calibrate a real model before relying on its proposals.

## Prepare

Create an archive with the app's **Create archive** action, or open a compatible existing archive. Choose a new Hub folder outside it. The package refuses an existing curator lane and a Mac already configured as a Client. Existing installations need a separately reviewed migration.

Choose **Prepare Hub**, supply the folder and model, preview, then apply. The generated `config.json` holds instance paths and model settings. Code remains in a separate `engine/` folder. All five curator gears start at **ask-first**; managed runs also cap automatic approval and rejection at zero.

The installed app includes the same command interface. Change these example paths and model before running:

```bash
SOV="$HOME/Applications/Sovereign.app/Contents/MacOS/sov"
ARCHIVE="$HOME/Documents/My Archive"
HUB="$HOME/Sovereign Hub"
MODEL="your-installed-local-model"

"$SOV" hub install --archive "$ARCHIVE" --destination "$HUB" --model "$MODEL"
# Review the preview before repeating with --apply.
"$SOV" hub install --archive "$ARCHIVE" --destination "$HUB" --model "$MODEL" --apply
"$SOV" hub doctor --config "$HUB/config.json"
```

No launch agents, home pointers or producer registrations are created by preparation. The initial curation cursor starts at preparation time. Existing material is not silently backfilled.

## Recovery

Create separate folders for the recovery key and capsules. The key must stay outside every archive and outside the Hub folder, with owner-only permissions. Keep an independent secure copy: losing it makes its capsules unrecoverable. Choosing a folder on the same disk does not protect against losing that disk.

Use **Create recovery key**, **Set recovery location**, then **Create recovery capsule** in the app. Each has a separate preview and apply. CLI equivalents:

```bash
KEY="$HOME/Private Recovery/sovereign.key"
CAPSULES="$HOME/Recovery Capsules"
mkdir -p "$HOME/Private Recovery" "$CAPSULES"
chmod 700 "$HOME/Private Recovery" "$CAPSULES"

"$SOV" hub key --output "$KEY"
"$SOV" hub key --output "$KEY" --apply
"$SOV" hub recovery --config "$HUB/config.json" --folder "$CAPSULES" --key-file "$KEY"
"$SOV" hub recovery --config "$HUB/config.json" --folder "$CAPSULES" --key-file "$KEY" --apply
"$SOV" hub snapshot --config "$HUB/config.json" --output "$CAPSULES/first.sovbackup" --key-file "$KEY"
"$SOV" hub snapshot --config "$HUB/config.json" --output "$CAPSULES/first.sovbackup" --key-file "$KEY" --apply
```

Capsules use authenticated AES-256-GCM encryption through macOS CryptoKit. They retain the archive, curator proposals/decisions/cursors, Git history, Hub settings, tools and Python runtime. They omit `repos/` working trees, disposable Hub logs/caches, and files outside the archive and Hub. Machine SSH keys, local model weights, external service credentials and other home files need their own owner-controlled recovery process. The encryption key is never included.

This first package limits a capsule to 480 MiB and 100,000 entries, including its tools and runtime; a single file cannot exceed 128 MiB. Linked files/directories and special files are refused. Managed jobs and owner gate actions share a lock with snapshots. Two scans check for changing file contents; this is not an atomic filesystem snapshot. Quiesce other writers for a recovery drill.

Restore into a **new** directory. Preview authenticates the capsule and verifies every file before an apply can extract it:

```bash
RESTORED="$HOME/Recovered Sovereign"
"$SOV" hub restore --capsule "$CAPSULES/first.sovbackup" --destination "$RESTORED" --key-file "$KEY"
"$SOV" hub restore --capsule "$CAPSULES/first.sovbackup" --destination "$RESTORED" --key-file "$KEY" --apply
"$RESTORED/hub/bin/sov" hub status --config "$RESTORED/hub/config.json"
```

Open `Recovered Sovereign/archive` in the app. Compare trusted notes and decisions, and test a context load and the capture/review loop. Restored paths and job definitions are regenerated. Home pointers and schedules remain unchanged; old activation receipts are cleared. Select the recovery key and capsule folder again for the restored instance. Restore disables Git hooks and remote pushes in the recovered repository; review those settings separately before using them. Existing repository identity is retained, and Git-backed approval requires that archive's own configured identity.

A successful file comparison and synthetic context load prove restoration mechanics. A fresh working session must still demonstrate that the context is received and useful.

## Activate after the drill

Enable schedules only on the Mac that will own this archive's Hub. Stop the previous Hub before a replacement cutover. The single-Hub confirmation is an owner assertion; this package does not provide a distributed lock across machines.

The activation preview lists three per-user launch agents, using the Mac's local time:

| Job | Schedule | Behavior |
|---|---|---|
| Curation | Daily, 06:00 | Up to 40 new items by default; produces proposals for owner review |
| Structural audit | Friday, 10:00 | Reports structural issues without model calls |
| Recovery capsule | Daily, 03:00 | Encrypts a new capsule at the configured location |

Activation checks model availability, authenticates the most recent capsule with the configured key, refuses conflicting machine configuration, then registers these jobs and the Hub pointers. It does not start a job immediately. User launch agents require the owning account's login session and available storage/model service. Existing connector jobs are separate; the package does not migrate legacy schedules, configure offsite storage or prune old capsules.

```bash
"$SOV" hub activate --config "$HUB/config.json"
# Apply only when this is the sole active Hub and its recovery drill has passed.
"$SOV" hub activate --config "$HUB/config.json" --confirm-single-hub --apply
```

Inspect completed-operation receipts with **Inspect Hub**. Receipts describe completed operations; they are not a live scheduler-health check. **Run a Hub job** offers a separate preview/apply for curation and audit. Review proposals through the existing owner gate.

To stop these three schedules for a cutover, use the corresponding macOS launch-agent controls or explicitly unload them. This leaves the archive, configuration and recovery data intact:

```bash
launchctl bootout "gui/$(id -u)/com.sovereign.hub.nightly"
launchctl bootout "gui/$(id -u)/com.sovereign.hub.audit"
launchctl bootout "gui/$(id -u)/com.sovereign.hub.snapshot"
```

Activation refuses existing job definitions on a retry. Inspect any failed activation receipt first; a failed rollback records labels needing cleanup. Existing-Hub migration and reactivation are deliberately separate from this clean-install path.

## Validation

The tests use temporary archives and a fake scheduler. They cover preview/apply boundaries, native archive scoping, the curator-to-owner-to-context roundtrip, encrypted recovery, tampering/wrong keys, linked paths, inference redirects, activation success/rollback and Git history. Native fixtures exercise wide/light and narrow/dark layouts.

```bash
SOV_PYTHON_RUNTIME=/path/to/bundled/runtime python3 -m unittest discover -s tests -p test_hub.py -v
python3 apps/console/test-hub.py --evidence /path/to/private/evidence
```

This is a locally signed pilot package. Clean-machine acceptance, migration of a real running Hub, recovery of its external dependencies and downloaded/notarized distribution remain separate release gates.
