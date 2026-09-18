# Checked producer delivery

A recent source commit is not proof that the hub accepted it. Status now reports the latest observed source head, whether that exact commit is an ancestor of the hub's main branch, and when the observation was made. Missing evidence is unknown; an unmerged head is waiting. The source commit timestamp is not described as a measured push or acceptance time.

## Inspect and accept

```sh
bin/sov-merge-lane --root "$BRAIN_ROOT" --ref exchange/lane/example --lane example
```

The default is a dry run. It checks the owner-written git-branch contract, every introduced commit, credential patterns, unsupported content, and Git's actual merge result. Multiple merge bases are handled by `git merge-tree`, rather than choosing a convenient ancestor. Temporary merge objects are discarded after inspection. Git 2.38 or newer is required.

```sh
bin/sov-merge-lane --root "$BRAIN_ROOT" --ref exchange/lane/example --lane example --apply
```

Apply requires a clean checkout on the target branch, a configured Git identity, and the unchanged target head from preview. It merges the inspected source commit, checks the exact resulting tree, commits, and records a receipt under `.git/sovereign-delivery.json`. It never pushes. Run it while other writers are idle; it does not coordinate with unrelated legacy writers. A conflict, dirty checkout, changed target, or failed check leaves acceptance refused. Review histories beyond 2,000 introduced commits or blobs beyond 2 MiB separately.

## Accept while unrelated drafts remain open

```sh
bin/sov-merge-lane --root "$BRAIN_ROOT" --ref exchange/lane/example --lane example --apply-isolated
```

This opt-in path uses the same history, contract, credential and exact-tree checks. It builds the merge commit in a private detached Git worktree with its own index. The live vault's files are never staged to prepare this commit. The original `--apply` retains its whole-checkout clean gate.

Before promotion, the live checkout must still be on the inspected target commit, its index must be clean, and no Git operation can be in progress. Local modifications or untracked files anywhere inside the producer's lane are refused. Unrelated unstaged drafts, additions and deletions can remain in the vault. The helper verifies the candidate's two parents, complete tree and path scope again, then performs only a fast-forward to that exact commit.

Promotion explicitly disables autostash and refuses overwriting ignored files. It never resets or aborts the live checkout. These controls use [Git's documented merge safeguards](https://git-scm.com/docs/git-merge); merge creation is isolated using a [detached worktree](https://git-scm.com/docs/git-worktree). They protect ordinary unrelated editing, but do not grant permission to write simultaneously to the producer's own destination folder. Coordinate or pause writers of that folder and legacy Git writers during promotion. The shared integration lock coordinates copies of this helper only.

A prepared receipt is saved before promotion. If main advances, an overlap appears or the fast-forward fails, the candidate remains reachable under `refs/sovereign/prepared/` for inspection. Resolve the live conflict or wait for the writer, then rerun the command to revalidate current heads. No automatic stash, reset, overwrite, or retry loop is used. The private worktree is removed after preparation; the candidate ref is removed only after the accepted receipt is saved. The accepted commit remains on main.

Acceptance and receipt writing are separate events. If recording the receipt fails after main advances, the command exits nonzero while reporting `state: accepted` and the accepted commit. Inspect and repair the receipt before proceeding. After a hard process termination, inspect a leftover integration lock or temporary worktree before cleanup. A receipt alone is not proof of backup delivery: the caller must still push the accepted main commit and verify both remote heads and source ancestry.

## Connector publication

Harness mirrors collect in a private temporary directory, retain earlier provenance, sanitize before publication, then transfer only inspected files to the watched destination. Failed collection or inspection preserves the previous published capture. Files are renamed into place during transfer; this is not an atomic switch of the whole directory. A partial transfer can contain files from two clean generations.

Collection, inspection, commit and push errors return failure. A retry attempts the push even when no new diff exists. Shared redaction code comes from the same template version as the connector. `sov-redact --strict` refuses unreadable, linked, binary or oversized content instead of silently skipping it.

Producer contracts require an explicit inline list of permitted mirror prefixes:

```yaml
mirror_harnesses: [claude-code, codex-memory]
```

This grants the named harness's documented collection scope. It does not make unrestricted memory safe for a client-restricted producer. Leave the list absent on such producers until its source filtering and output are reviewed against the owner contract. The manual capture command also sanitizes before writing and rejects lane traversal, linked destinations and overwrite collisions.

## Rollout

Deploy the helper, redactor and mirror scripts together. Rehearse acceptance on an isolated clone first. Pilot one producer with an approved scope and verify collection, publication, hub acceptance and visible status independently. Preserve current installed binaries until the pilot succeeds. The merge helper is delivered as a command; an instance's exchange scheduler must be wired to call it before it changes live behavior.
