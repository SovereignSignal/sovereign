# Archive Evidence Productionization Implementation Plan

> **For Hermes:** Execute this plan task by task with strict RED → GREEN → REFACTOR. Use only deterministic local scripts and loopback Ollama for review. Do not expose trusted text or identifiers.

**Goal:** Ship the reviewed archive-evidence core as a separate opt-in command, enroll a small private prospective sidecar, observe report-only freshness for 30 days, and preserve default retrieval and trusted content unchanged.

**Architecture:** Product code lives in `lib/archive_evidence/` with a symlink-safe Python entry point at `bin/sov-evidence`. Detailed outputs and the enrollment sidecar live in a private state directory outside the archive. Observation and finalization are deployment scripts outside the repository; they emit sanitized receipts only.

**Tech Stack:** Python 3.9, PyYAML, unittest, Ruff, Git, local Ollama, Hermes cron, Notion API.

---

### Task 1: Freeze the production contract

**Objective:** Define the separate-command, private-output, and no-default-change boundaries.

**Files:**
- Create: `docs/plans/2026-07-30-archive-evidence-productionization.md`
- Modify: `README.md`

**Steps:**
1. Record exact scope, rollback, observation, and owner-gated exclusions.
2. Publish the one-page execution packet under the owner's Archivist page after a parent snapshot.
3. Fetch and verify the exact packet title, parent, content sequence, links, and approval phrase.

### Task 2: Add safe trusted-card binding

**Objective:** Bind one opaque sidecar row to an exact regular trusted file and raw-byte SHA-256.

**Files:**
- Create: `lib/archive_evidence/__init__.py`
- Create: `lib/archive_evidence/cards.py`
- Create: `tests/test_archive_evidence_cards.py`

**Steps:**
1. Write one failing test for unique binding, then run it and require the expected RED result.
2. Implement the smallest fd-based no-follow loader that passes.
3. Repeat RED → GREEN for stale hashes, traversal, slug/path disagreement, duplicate slugs, invalid UTF-8, and symlinked components.
4. Run the focused module and full suite after each slice.

### Task 3: Add private I/O and evidence extraction

**Objective:** Write detailed evidence only to new private files and preserve exact source identity.

**Files:**
- Create: `lib/archive_evidence/safeio.py`
- Create: `lib/archive_evidence/evidence.py`
- Create: `tests/test_archive_evidence_safeio.py`
- Create: `tests/test_archive_evidence_extraction.py`

**Steps:**
1. RED → GREEN for private-parent enforcement, exclusive no-overwrite output, and bounded private input.
2. RED → GREEN for overview text, stable anchors, source/hash propagation, overlay projection, truncation disclosure, and zero-record rejection.
3. Keep source bodies and identifiers in private artifacts only.

### Task 4: Add report-only freshness and sanitized CLI

**Objective:** Evaluate only enrolled rows and expose no trusted identifiers on stdout or stderr.

**Files:**
- Create: `lib/archive_evidence/freshness.py`
- Create: `lib/archive_evidence/cli.py`
- Create: `bin/sov-evidence`
- Create: `tests/test_archive_evidence_freshness.py`
- Create: `tests/test_archive_evidence_cli.py`

**Steps:**
1. RED → GREEN for missing fields, impossible dates, allowed classes/status, missing supersession targets, and overdue report-only findings.
2. RED → GREEN for opaque evidence mode, aggregate audit mode, stable errors, private output, and symlink-resolving entry-point behavior.
3. Require nonzero exit on blocking metadata and zero exit for report-only findings.

### Task 5: Freeze and independently review

**Objective:** Bind all gates and a local independent review to one clean commit.

**Steps:**
1. Run all unit tests, compileall, Ruff, shell syntax, secret scan, and dangerous-API scan.
2. Commit the exact product revision and compute a canonical tracked-file manifest.
3. Review code and synthetic tests through loopback Ollama only.
4. Verify active network scope is loopback-only and require strict JSON PASS with zero findings.
5. If a finding is confirmed, add a failing regression test, fix, recommit, and repeat one fresh review.

### Task 6: Install, rollback, and reinstall

**Objective:** Prove deployment is reversible and does not alter default retrieval or protected content.

**Steps:**
1. Capture private pre-install manifests for protected content, Git state, production retrieval, controls, and target state.
2. Install `sov-evidence` as a symlink into the existing command lane.
3. Run synthetic smoke tests.
4. Remove it and prove the command lane matches the pre-install snapshot.
5. Reinstall the exact reviewed target and rerun smoke tests.
6. Recompute manifests independently and require no protected, default-retrieval, control, or Git drift.

### Task 7: Create prospective enrollment and observation

**Objective:** Enroll six opaque references without editing trusted content and observe report-only behavior for 30 days.

**Steps:**
1. Create a private state root and select two local rows per prospective class.
2. Keep unsupported `as_of` and `status` values null; set only the observation date as `verified_at`; label classes pilot-inferred and non-authoritative.
3. Bind every row to exact path and raw-byte hash. Keep all identifiers private.
4. Install a local daily observer that writes detailed private outputs and remains silent on success.
5. Schedule 30 daily local observations and a one-shot finalizer after the full window.
6. The finalizer must fail closed if fewer than 30 distinct observation dates exist, any blocking finding occurs, or protected/default/control state drifts.

### Task 8: Publish readiness and observation receipts

**Objective:** Close the immediate deployment loop now and the 30-day loop automatically.

**Steps:**
1. Snapshot the owner's Archivist page before each publication.
2. Publish the immediate production-readiness receipt only after independent install and non-mutation verification.
3. Fetch and verify the exact page parent, title, full block sequence, source links, hashes, scope exclusions, and rollback result.
4. After 30 complete days, the local finalizer publishes and read-backs a separate observation receipt or a blocked receipt.
5. No receipt authorizes default retrieval changes, trusted edits, temporal backfill, enforcement, or recovery changes.
