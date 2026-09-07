# Checked producer delivery

A recent source commit is not proof that the hub accepted it. Status now reports the latest observed source head, whether that exact commit is an ancestor of the hub's main branch, and when the observation was made. Missing evidence is unknown; an unmerged head is waiting. The source commit timestamp is not described as a measured push or acceptance time.

## Inspect and accept

```sh
bin/brain-merge-lane --root "$BRAIN_ROOT" --ref exchange/lane/example --lane example
```

The default is a dry run. It checks the owner-written git-branch contract, every introduced commit, credential patterns, unsupported content, and Git's actual merge result. Multiple merge bases are handled by `git merge-tree`, rather than choosing a convenient ancestor. Temporary merge objects are discarded after inspection. Git 2.38 or newer is required.

```sh
bin/brain-merge-lane --root "$BRAIN_ROOT" --ref exchange/lane/example --lane example --apply
```

Apply requires a clean checkout on the target branch, a configured Git identity, and the unchanged target head from preview. It merges the inspected source commit, checks the exact resulting tree, commits, and records a receipt under `.git/sovereign-delivery.json`. It never pushes. Run it while other writers are idle; it does not coordinate with unrelated legacy writers. A conflict, dirty checkout, changed target, or failed check leaves acceptance refused. Review histories beyond 2,000 introduced commits or blobs beyond 2 MiB separately.

## Connector publication

Harness mirrors collect in a private temporary directory, retain earlier provenance, sanitize before publication, then transfer only inspected files to the watched destination. Failed collection or inspection preserves the previous published capture. Files are renamed into place during transfer; this is not an atomic switch of the whole directory. A partial transfer can contain files from two clean generations.

Collection, inspection, commit and push errors return failure. A retry attempts the push even when no new diff exists. Shared redaction code comes from the same template version as the connector. `brain-redact --strict` refuses unreadable, linked, binary or oversized content instead of silently skipping it.

Producer contracts require an explicit inline list of permitted mirror prefixes:

```yaml
mirror_harnesses: [claude-code, codex-memory]
```

This grants the named harness's documented collection scope. It does not make unrestricted memory safe for a client-restricted producer. Leave the list absent on such producers until its source filtering and output are reviewed against the owner contract. The manual capture command also sanitizes before writing and rejects lane traversal, linked destinations and overwrite collisions.

## Rollout

Deploy the helper, redactor and mirror scripts together. Rehearse acceptance on an isolated clone first. Pilot one producer with an approved scope and verify collection, publication, hub acceptance and visible status independently. Preserve current installed binaries until the pilot succeeds. The merge helper is delivered as a command; an instance's exchange scheduler must be wired to call it before it changes live behavior.
