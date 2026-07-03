# Viewing the brain in Obsidian (optional)

The brain is plain Markdown in folders — that is the whole truth of it. You can read and write it with any editor, and every mechanism in this template works with zero plugins installed. **Obsidian is not a requirement.** It is, however, a very good *interface*: local-first, plain-file-native, and its graph view turns the brain's trust model into something you can see.

## The graph shows the trust model

Color the graph by folder and the architecture becomes visible: a bright, densely linked knowledge core; a working ring of workstreams around it; and the gray loading dock at the edge. Curation quality shows up as shape — orphan dust means cards nobody wove in; a starburst means link noise (see hygiene below).

Recommended setup (Graph view → Filters / Groups):

**Filters**

```
-path:"archive"
```

Add a `-path:` filter for any large tool mirror in `raw/tools/` (a full workspace export will otherwise flood the graph with thousands of gray dots), e.g.:

```
-path:"raw/tools/<your-biggest-mirror>"
```

**Groups** (color by path — pick your own colors, the split is what matters)

```
path:"knowledge/entities"     → color 1 (the real things)
path:"knowledge/concepts"     → color 2 (the ideas and playbooks)
path:"knowledge/syntheses"    → color 3 (the big write-ups)
path:"workstreams"            → color 4 (the desk)
path:"raw"                    → gray   (the loading dock — untrusted)
```

## Graph hygiene (why some rules in the standard exist)

Two things pollute an Obsidian graph, and both are worth rules even if you never open Obsidian:

1. **Generated reports that quote note text.** If an agent writes a report containing `[[wikilinks]]`, every quoted link becomes a phantom node. Reports that land anywhere inside the vault should escape wikilinks (e.g. `⟦⟦slug⟧⟧`).
2. **Imported documents with `[text](uuid)` cross-references** (common in workspace exports). These render as unreadable starburst hubs. Keep such imports filtered out of the graph, or strip the links at import time.

A related style rule that keeps the graph honest: **link only to knowledge.** `[[slug]]` is for cards in `knowledge/`. References to skills, config files, or working documents belong in backtick code spans — they are pointers to operational surfaces, not edges in the knowledge graph (the standard's "config is not knowledge" rule, applied to links).

## The note template

`templates/note.md` works with Obsidian's core **Templates** plugin: point the plugin at the `templates/` folder and new notes get their labels (`type`, `source`) and an auto-filled `created` date. No community plugins needed.

## Sync

Obsidian Sync is one fine way to move the vault between machines — as the standard says, sync is visibility, not durability. The brain's durability lives in its git history, wherever you host it.
