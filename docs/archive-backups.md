# Archive backups

The Backups tab protects the selected archive, its decisions and source-host operating settings. One computer can create and restore a backup without a separate Git server, VM, inference service or cloud account.

## First backup

1. Open an archive and choose **Backups**.
2. Choose an existing backup folder on another disk or a mounted NAS. For a connected archive, choose a folder reachable by its authoritative host; the app names that host above the controls.
3. Choose where to keep the recovery key. An existing 32-byte owner-only key can be reused, or the app creates one at the chosen path. Keep an independent secure copy outside the archive and backup destination. Losing the key makes the encrypted backup unreadable.
4. Preview and save the destination, then preview and run **Back up now**.
5. Use **Restore to a new folder** to demonstrate recovery. Existing files are never overwritten.

This first version manages one destination per archive and runs on demand. Changing the destination preserves previous backup files and archives their receipts locally. Additional destinations, schedules, retention and direct cloud-storage adapters are later work. No schedule is created by saving a destination.

## Hosts and connections

An archive has one active authority. A read-and-contribute client sends backup requests to its declared authority using the existing SSH connection. It does not back up its mirror when the authority is unavailable. Paths and storage availability are evaluated on the executing host.

Both ends must support backup protocol 1. An older or unavailable host produces an explicit error without changing existing contribution or context-loading behavior. Previously observed receipts remain visible during the current app session with their observation time when a refresh fails. A fresh session without a successful observation cannot claim prior status.

Backup operations do not change roles, producer definitions, lane identities, permissions, remotes or schedules on the running installation. They create backup configuration, a destination identity marker, a key if requested, encrypted files and operation receipts. A missing destination identity fails instead of treating an absent disk mount as a new local folder.

People, archives, devices and connections remain separate concepts. Backup identity is a persistent archive UUID, independent of its current path. A restored archive retains that UUID when configured again. This feature adds no team membership, shared access or automatic authority transfer.

## Recovery scope

Included:

- Archive files and empty directories, Git history, trusted knowledge, proposals, decisions and archive-owned checkpoints.
- Available authoritative-host settings: the Hub instance, connector configuration, client records and intake checkpoints. Source pointers are retained as recovery evidence.
- Compatible engine files, the native encryption helper and the bundled Python runtime. Recovery does not require downloading them again.

Excluded:

- Repository working trees under `repos/`.
- External credentials, machine SSH keys, model weights and disposable caches outside the selected archive and bundled engine.
- Unsent producer work, other computers and VM images.
- The recovery key and backup destination itself.

Archive content is encrypted as provided. Files already stored inside the archive remain included, even if they contain sensitive material. The backup is not a secret-redaction process. External credentials must be reconnected separately after recovery.

A completed backup proves what was present on the authoritative host. It does not prove every producer was current. Use existing delivery and acceptance receipts to check those routes separately. Device and VM backups remain separate protections.

## What the status means

**Completed** means the encrypted saved bytes were opened again and the file inventory and hashes verified before publication. **Last attempt** can show a newer failure while the previous completed backup remains available. **Restore** records successful extraction into a separate folder; it does not claim a replacement host has been activated or live producers have resumed.

Source changes detected during collection or the second content check discard the incomplete attempt and retry once from a fresh inventory. Continued changes stop with a retry message. Storage and key errors are not retried. No producer is paused automatically. A busy archive may need a quiet period before a backup completes.

## Restore and authority transfer

On a new computer, create or open a local archive to reach Backups, then choose **Restore to a new folder**, the backup file and its key. No destination configuration is required first. Open the recovered `archive` folder to inspect notes and load context. `RECOVERY.md` describes the recovered layout.

Restored settings and pointers are evidence until deliberately installed. Jobs remain inactive. Restored Git hooks and push URLs are disabled. Managed Hub paths and launch definitions are rebased for the chosen directory without loading the jobs. Recovery does not touch the original archive or its live configuration.

Before activating a replacement authority, stop the previous authority, reconnect credentials and reconcile each producer checkpoint against its last accepted contribution. Explicitly review producer routes, permissions and schedules. Automatic takeover and producer reconciliation are outside this release.

## Format and limits

Version 2 uses the existing native CryptoKit AES-GCM primitive with 4 MiB authenticated frames. Each frame binds a random stream identity and its sequence number. An authenticated terminal frame is mandatory. Changed, reordered, substituted, truncated and trailing frames fail authentication. The encrypted manifest contains file hashes, sizes, modes, directories, archive identity and recovery scope.

Encryption uses bounded memory. Creation stages plaintext in private local temporary storage and writes only ciphertext to the selected backup destination. Publication uses exclusive atomic rename where supported. On SMB filesystems that reject this operation, it creates the destination exclusively, streams the encrypted bytes, flushes them and verifies their hash against the authenticated source before recording success. Neither path overwrites an existing file. An interrupted SMB copy can leave an incomplete file without a success receipt; recovery authenticates the complete stream before extracting any files. Actual NAS compatibility must be verified in a restore pilot.

The implementation bounds payload to 1 TiB, files, directories and internal links to 500,000 each, and the manifest to 64 MiB. It requires additional local staging space, approximately twice the source size plus overhead, and destination space for the encrypted copy. These are safety ceilings, not a tested maximum-size claim. Acceptance includes a 512 MiB file, exceeding the earlier per-file capsule limit.

Archive links are recorded without following them during collection. Their resolved targets must stay inside the archive, including broken historical references. Recovery converts them into portable relative links only after all regular files have been validated and written. Links cannot escape the archive, be used as extraction parents or traverse other restored links. Internal file aliases in the bundled engine/runtime may be materialized only within their source tree. Engine directory links, unsafe restore paths and duplicate entries are rejected. The previous capsule format remains readable through `sov hub restore`; the new tab uses version 2.

## Validation and rollout

Run the release checks plus `tests/test_archive_backups.py` and `apps/console/test-archive-backups.py` against the packaged candidate. The native fixture driver supports `--app` and `--evidence`; its local, remote and narrow scenes use temporary homes, archives and a simulated SSH transport. No live producer is needed.

Before a live rollout, record source versions, roles, pointers, producer IDs, permissions, schedules and delivery/acceptance checkpoints on the affected hosts. Install the compatible authoritative backend first, verify read-only capability, then enable the client UI. Compare the same inventory afterward and demonstrate direct destination backup and separate-folder recovery. Retain the previous package and configuration for rollback. Retiring older backup jobs is a separate reviewed action after the restore pilot succeeds.

## Reconnecting a disk or NAS

Connect the storage on the computer named above the backup controls, then refresh. If the mount returns at a different path, choose **Reconnect folder** and select the original backup folder. Preview checks the destination identity before saving the new path. The archive identity, key, backup files and receipts remain unchanged. Another folder or disk with no matching destination marker is refused. The remote folder picker offers **Connected drives** and **Home folder** shortcuts.

Sovereign does not store NAS passwords or silently mount a share. Reconnection after an actual logout or reboot still depends on the computer's storage login. The interface explicitly shows that this release runs on demand; no new recurring job or retention deletion is installed.

The saved-copy check confirms the latest file is present with its recorded size; it is not a new cryptographic integrity check. Use **Check saved backup** for that. **Latest backup recovery** reports a restore test only when the restore receipt matches that backup. A newer backup needs its own restore test; an older successful test remains visible as history.
