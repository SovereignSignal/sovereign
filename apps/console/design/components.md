# Components

Measurements are in CSS px at 1x. Every colour and size is a token from `tokens.css`. States keep their meaning; only their dress changes.

## Header (36)
Crown glyph 16 px in `--ink`, instance name `--t-title` semibold `--ink`, then meta in mono `--t-caption` `--faint` (host, revision, sync line, clock). Right: hub pill (mono caption, 1 px `--rule`, radius `--radius-tag`, dot 6 px), Refresh as a text button, settings glyph. Bottom rule 1 px `--rule-soft`.

## Verdict bar (44)
Left padding `--s3`. Dot 10 px in the state colour with a 1 px lighter ring of the same hue at 30% alpha. Sentence `--t-verdict` medium `--ink`, single line, ellipsis. Right: last refresh in mono caption `--faint`. When the state is `down`, a 3 px left rule in `--down` spans the bar. Background `--panel`; no wash.

## Column (three, equal)
Container `--panel`, radius `--radius`, 1 px `--rule`, `--shadow` only in light. Header 28 px: title mono caption uppercase `--muted`, letter-spacing .04em, count mono caption `--ink-2` right. Body scrolls independently when a column exceeds the frame; the frame itself never scrolls. Empty state: one line `--t-body` `--muted`, padded `--s3`.

## Row (30)
Grid: dot 8 px | name | detail (flex 1, ellipsis) | age | chevron 12 px. Gaps `--s2`. Name mono `--t-name` medium `--ink`; detail sans `--t-body` `--ink-2`; age mono caption `--faint`, tabular. Hover `--sel`. Selected: `--sel` plus a 2 px `--brass` rule on the left edge, name `--ink`. Focus ring 2 px `--brass` at 60% alpha, offset 1 px, keyboard only. Dot colour is the state; `idle` rows use the idle dot and `--muted` text.

## Tag
Mono caption `--faint`, 1 px `--rule`, radius `--radius-tag`, padding 0 5px, height 16. State tags colour the text only (`--live`, `--warn`, `--down`), never the fill.

## Wire strip
Unchanged semantics: read and write bars 3 px tall, `--rule-soft` track, filled in `--live` (fresh), `--warn` (late), `--down` (failed), `--idle` (never). Labels mono caption `--faint`. Width shares the row's detail slot.

## Footer switch (32)
Segmented control, mono 11.5, gap `--s3`, each label padded `--s2`. Active: `--ink` with a 2 px `--brass` underline sitting on the bottom rule; others `--muted`. History arrows on the left in `--faint`; keys 1 to 6 as today. Top rule 1 px `--rule-soft`.

## Drawer (400) and inspector
Slide from the right in `--dur` `--ease`, `--panel` with `--shadow`. Title `--t-title` semibold, subtitle mono caption `--faint`, close and Pin as text buttons. Sections: heading mono caption uppercase `--muted`, then key-value pairs (key mono caption `--faint` 96 px column, value `--t-body` `--ink`) or prose `--t-body`. Actions: text buttons; the primary one in `--brass` with `--brass-wash` fill on hover. Pinning turns the drawer into a right column at the same width.

## Glance panel (menu bar, 420 wide)
Same data shape. First row is the verdict sentence (`--t-body` medium with the state dot) instead of a gate row; then the five figures as today (label mono caption `--faint`, value `--t-title` mono); footer with the clock and Open console as the brass text button. The status item is a 6 px state dot beside the crown template glyph.

## Figures
Only two `--t-figure` numbers may appear on the glance screen at once, and never in column headers. The Archive view keeps its card total and gate count at that size.

## Empty and error states
Empty: one `--t-body` `--muted` line. Error (bridge failed, sov not found): the verdict bar in `down` with the message, columns hidden, one action.
