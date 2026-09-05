# Notion harness: the official API, daily, into one lane

Mirrors every Notion page and database your integration can see into `raw/tools/Notion/`, in the same folder layout Notion's own export produces, so anything that names Notion subtrees by path (curator excludes, graph filters) keeps working. One-way, read-only, no model in the path. The script is `bin/brain-mirror-notion`; this folder is the connector the app and `sov connect` use.

## From the app

Tools, Notion, Connect. The dry run shows what will happen; Install asks for the integration token, writes it to `~/.notion-mirror/mirror.env` on this machine only, checks what the token can see, and schedules the daily job. The one manual step is in Notion itself: create an internal integration and connect each top-level page to it (children inherit).

## From the command line

    sov connect notion --vault "~/My Brain" --host <short-name>                     # dry run
    sov connect notion --vault "~/My Brain" --host <short-name> --secret ntn_xxx --apply

Options: `--at HH:MM` (default 03:45), `--lane raw/tools/Notion`, `--no-launchd` (write the plist, load it yourself later, for machines reached over SSH where launchd has no GUI session). The token can also come from `NOTION_API_KEY` in the environment or an existing `~/.notion-mirror/mirror.env`.

## After connecting

    brain-mirror-notion --check              # roots the token can see, against roots.json
    brain-mirror-notion --full --dry-run     # what the first run would write, move, delete; oracle match rate on an existing lane
    nohup brain-mirror-notion --full > ~/.notion-mirror/first-full.log 2>&1 &   # the first run, hours on a large workspace
    brain-mirror-notion --coverage ~/Downloads/Export-xxxx   # what is in Notion that the backup cannot see, grouped by top folder; share those pages with the integration to close the gap

`roots.json` is written on install with every reachable root required under `Private & Shared`; edit it to map a teamspace root to its folder. A run that would delete more than the shrink floor allows refuses, which is what a disconnected root looks like.

A page you connect to the integration later appears on the next full walk, not in a delta: a delta only asks for pages edited since the cursor, and connecting one does not edit it. Run `brain-mirror-notion --full` to pick it up the same day.

When a run errors, re-run it with `brain-mirror-notion --full`: the errored items had their stamps cleared, so the walk retries only what failed. A `crashed:` status leaves the previous manifest in place; files written or moved before the crash stay on disk and the next `--full` reconciles them. To start over from nothing, `rm -r ~/.notion-mirror/state/` and then `--full`, which rebuilds the manifest, the cursor and the last-full stamp from one complete walk.

## How it runs

- Daily: a delta. One search sorted by last edit, back to the cursor with a ten minute overlap, then only changed pages are re-rendered. Writes are atomic and only when bytes differ.
- Weekly: a full walk. Renamed and moved pages move on disk, gone or trashed pages are deleted, every database CSV is regenerated.
- The mirror never commits. Your vault's own autocommit picks up the lane.
- `~/.notion-mirror/last-status` is one line: `OK <ts> <summary>` or `FAILED <ts> <reason>`. `last-success` holds the last clean run's timestamp. `watchdog.sh` alerts when that is older than 36 hours; schedule it the same way at a later hour if you want it.

## Layout on disk (matches Notion's export)

    <root folder>/<Page> <32hex>.md            a page
    <root folder>/<Page>/                       its children
    <root folder>/<Page>/<DB> <32hex>_all.csv   a database, every row and property
    <root folder>/<Page>/<DB>/<Row> <32hex>.md  a row page
    Untitled <4hex>-<4hex>                      an untitled page or database

Attachments are downloaded beside the page (`NOTION_FILES=skip` in `mirror.env` leaves them in Notion and keeps the links). Comments and database views are not mirrored.
