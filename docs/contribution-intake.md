# Contribution intake pilot

A contribute-only Client collects explicitly selected method notes into an independent Git spool. It publishes that spool to its own intake repository. A Hub validates the received items and materializes them only in an owner-declared raw lane. The curation and owner review path remains responsible for promotion.

This is a manually configured pilot. It does not provision a Hub, declare another operator ready, or install a scheduler.

## Machine roles and discovery

The existing connector manifest can declare `machine.role` as `hub` or `client`. Clients declare `machine.mode` as `read-and-contribute` or `contribute-only`. Missing declarations remain visibly unknown. A contribute-only declaration suppresses shared context hooks, cached Hermes packs and `sov load`; it does not revoke a credential or erase a previously retained archive copy.

`sov about --json` is local and read-only. The app also contains `Sovereign.app/Contents/MacOS/sov about --json`, backed by its bundled Python. About Sovereign uses the same introduction. Updated session-start hooks provide an executable discovery pointer. Receiving that hook output and using the context still require evidence from the actual harness.

## Minimal configuration

Client manifest example, with owner-chosen paths and identity:

```json
{
  "machine": {"role": "client", "mode": "contribute-only"},
  "intake": {
    "client_id": "worker-a",
    "source_root": "~/work",
    "spool": "~/.local/state/sovereign/contribution-spool",
    "remote": "intake-host:worker-a.git",
    "selectors": [{
      "id": "operating-method",
      "path": "method.md",
      "title": "Operating method",
      "topics": ["method"],
      "extractor": "sections",
      "argument": ["Working procedure"]
    }]
  }
}
```

The available extractors are `sections`, `whole`, `open-commitments` and `learnings`. They preserve the existing method-export policy. Sections stop at the next heading. Learnings select Summary and Suggested Action only, within declared areas. Unfinished and cancelled commitments are selected separately from completed work.

Hub manifest additions:

```json
{
  "machine": {"role": "hub"},
  "intakes": {
    "worker-a": {
      "remote": "intake-host:worker-a.git",
      "lane": "worker-a",
      "sources": {"operating-method": "method.md"}
    }
  }
}
```

Merge these fields into the existing manifest. Preserve unrelated connector declarations. The Hub requires an existing owner-written `raw/workspaces/worker-a/LANE.md`. State defaults to `~/.local/state/sovereign`; `SOV_STATE_DIR` changes it. An explicit `--config` uses that file's parent for receipts.

## Commands and access boundary

```sh
sov contribute assess
sov contribute init --name 'Owner Name' --email 'owner@example.invalid' --apply
sov contribute run --apply
sov contribute status
sov contribute import --client worker-a --root "$BRAIN_ROOT"
sov contribute import --client worker-a --root "$BRAIN_ROOT" --receive-only --apply
sov contribute import --client worker-a --root "$BRAIN_ROOT" --apply
```

Assessment reads the declared files and prints selection metadata, without bodies, logging, network or state writes. Commands that initialize, upload or import require `--apply`. Spool identity must be explicit and repository-local. Initialization refuses existing paths.

Initialize a fresh bare repository on the relay with `sov-contribute init-server --repo /srv/intakes/worker-a.git --apply`. Do not derive it from an archive repository, use alternates, or add the archive as another remote. Configure a dedicated producer key with `restrict` and a forced command equivalent to:

```sh
/path/to/sov-contribute serve --repo /srv/intakes/worker-a.git --name worker-a.git
```

The SSH original command can invoke only upload-pack or receive-pack for that exact public repository name. The server rejects other repositories, shell commands, tags, deletion and rewritten history. Uploads are capped at 32 MiB per push. The dedicated key must also pass real SSH denial tests; checking command parsing alone is insufficient. Revoke superseded grants and remove retained archive clones/context caches before declaring migration complete.

## Evidence and recovery

- `contribution.json`: latest collection attempt and separate delivery result. Every run retries the committed HEAD, including unchanged source runs after a failed push.
- `intake-<client>.json`: received HEAD, client-reported capture collection time, per-item import receipts and rejection codes. Receipts are bound to an archive root. A failed fetch retains earlier receipt times with an explicit error state; successful recovery clears the error.
- Received means the Hub fetched and validated the intake. Imported means the capture was materialized in raw. Neither means promoted, approved, delivered as context or used by a model.

Items have stable content IDs, bounded UTF-8 bodies, provenance and topic metadata. Both ends reject credential-shaped content. Source path walking and materialization refuse symlinks and traversal. The Hub reads Git blobs without checking out client paths. Complete captures are published atomically without overwriting existing files. Repeated imports compare existing bytes. Edited captures stop the import rather than being overwritten. Deleted intake entries never delete historical raw captures.

The collector does not scan arbitrary directories. Pattern filters cannot identify every kind of sensitive prose; source selection remains an owner decision. First use of this protocol creates a new versioned baseline, even if older exporter captures already exist. Review that initial diff. Source collection time is client reported; unchanged items retain their original collection time.

The relay and importer need normal disk monitoring. The 32 MiB push cap is not a cumulative storage quota; the importer also caps a received tree at 10,000 items and each item at 32 KiB. Collection, upload and import locks are independent. The Hub importer must run with the Hub's permissions; its output boundary does not sandbox a compromised Hub account.

## Validation

Run the Python intake/discovery tests, Node system model tests and `apps/console/test-client-pilot.py`. Native tests use disposable archives, an isolated preference domain, fixture status commands, both themes and small windows. Authenticated SSH denial and outage recovery require a separate disposable SSH server. No production keys or repositories are needed.
