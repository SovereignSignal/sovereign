# Console design: the glance

The console is a glance first. You open it for ten seconds and one screen answers three questions: what needs me, what is fresh, what is stale. Everything else is a drill-down. This folder is the design system the console implements; `ui/index.html` owns behaviour, the bridge, and the QA hooks, and takes these files as its contract.

Nothing here changes what a state means. `live`, `warn`, `down`, `idle` on dots and tags, the drawer and inspector mechanics (`data-open`, `data-act`, the `sovView` hook, `body.qa`), the Glance panel's data shape, and the Archive picture's marks and validated series colours all stay as they are. This folder restyles them and rearranges the screen around them.

## The frame

One window, default 900 by 600 pt, no scrolling at that size. Top to bottom:

1. **Header**, 36 pt: the crown mark (16 px glyph), the instance name (data, never a constant), the hub pill, refresh, settings. Unchanged content, quieter weight.
2. **Verdict bar**, 44 pt: a 10 px state dot and one sentence in SF Pro 18/24 medium, ink. The sentence is written from the data by the rules below. Its colour is the worst state on screen. On the right, in mono 10.5 faint: the last refresh time. This bar replaces the gate banner and the pulse strip as separate elements; the pulse tiles' numbers move into the column headers.
3. **Three columns**, equal width, 16 pt gutter, each a list in the row language: **Needs you**, **Fresh**, **Stale**. A column header is mono 11 uppercase muted with its count on the right. An empty column shows one sans 12.5 muted line ("nothing waiting", "nothing new since your last look", "nothing stale"). Rows are 30 pt: 8 px dot, name in mono 12 medium, one-line detail in sans 12.5 ink-2 with ellipsis, age in mono 11 faint right-aligned, a 12 px chevron. Hover paints `--sel`; the selected row adds a 2 px brass rule on its left edge. Every row opens the drawer it opens today.
4. **Footer**, 32 pt: the six views as a segmented control (Hosts, Archive, Lanes, Tools, Hub, Backups) in mono 11.5, the active one with a 2 px brass underline, history arrows on the left, keys 1 to 6 unchanged. The views themselves keep their information design; they move from the top to the bottom so the glance owns the top.

## The verdict sentence

Written by the app, never a constant. Pick the first rule that applies; state is the colour of the dot.

| Rule | State | Sentence pattern |
|---|---|---|
| a job failed, a host is unreachable, or a lane is past twice its cadence | down | `Attention: <what> <detail>.` (one item; add `and N more` when several) |
| anything in Needs you | warn | `<N> thing(s) need you: <first item>.` |
| a lane or backup is past its cadence but under twice | warn | `Stale: <what> <age>.` |
| nothing above | live | `All good. <one fresh fact>.` such as `All good. 12 cards landed today.` |

Names in the sentence are data (`<host>`, `<lane>`). No exclamation marks, no colour words.

## What feeds each column

The console already has every field in `sov status --json`. The mapping is by category; the implementer picks the exact keys.

- **Needs you**: every `needs_you` entry (gate items, harness manual steps, job error logs); jobs whose last exit is non-zero; the Backups view's actionable items. Sorted worst state first, then oldest first.
- **Fresh**: lanes and hosts whose newest file or heartbeat is inside their cadence, newest first; cards that landed since the last nightly (the contribution figures); the last nightly's one-line result. This column is about reassurance, so it is allowed to be short.
- **Stale**: lanes, hosts, harnesses, and backups older than their cadence, oldest first, each with its age. A row here is one that will become Needs you if nothing happens.

Cadence per kind comes from what the console already knows (a 15 minute mirror, a daily job, a weekly walk); a row's age compares against that, never against a global threshold.

## Type

SF Pro for sentences, SF Mono only for identifiers and numbers, so the screen reads as sentences with numbers rather than as a terminal. Five sizes and their line heights, as tokens in `tokens.css`:

| Token | Size / line | Use |
|---|---|---|
| `--t-caption` | 11 / 14 | column headers, tags, ages, mono meta |
| `--t-body` | 12.5 / 18 | row details, empty states, drawer prose |
| `--t-name` | 12 / 16 mono medium | identifiers in rows |
| `--t-title` | 14 / 20 semibold | drawer and inspector titles |
| `--t-verdict` | 18 / 24 medium | the verdict sentence |
| `--t-figure` | 28 / 32 mono | the two big figures allowed on screen (column-header counts never; the Archive view's card total and the gate count may use it) |

Letter-spacing: mono at -0.01em, sans at 0. Tabular figures on for every number.

## Space

Four steps, everything on an 8 px grid: `--s1` 4, `--s2` 8, `--s3` 16, `--s4` 24. Row height 30, header 36, verdict 44, footer 32, drawer width 400, corner radius 6 for panels and 4 for tags, 1 px rules.

## Colour

Light: paper ground, white panels, graphite ink, brass as the single accent. Dark: a warmer graphite than today, same roles. State colours are unchanged. Chart series stay the validated set and are exposed as `--series-1` to `--series-3`. The amber wash behind the old gate banner goes away; the verdict bar carries the state in its dot and, when `down`, in a 3 px left rule of the state colour.

## The mark

The crown is the product mark and the instance name is data. `icon/AppIcon-1024.png` is the app icon on Apple's grid (the rounded square at 824 px, transparent outside); `build.sh` builds the `.icns` from it. `glyphs/` holds the crown at 12 and 16 px for the header and rows, and the menu-bar template image (black with alpha, 18 and 36 px) for the status item, which becomes a state dot beside the crown. Other row glyphs stay text and dots; no icon font.

## Motion

Drawer and inspector slide in 120 ms ease-out. Freshness bars animate on refresh over 240 ms. The verdict dot does not pulse. Nothing decorative.

## Process

The console owner integrates in slices with the snapshot harness (`SOV_SNAPSHOT`, `SOV_APPEARANCE`, `SOV_SNAPSHOT_ANCHOR=view:<name>+open:<id>`) and posts shots; design critique happens against those shots, in both appearances, at the default window size and at the smallest sensible size.
