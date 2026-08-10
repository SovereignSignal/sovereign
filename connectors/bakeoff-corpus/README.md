# bakeoff-corpus — the judge calibration corpus

Fixture material for `bin/brain-judge-bakeoff`. Everything here is **fictional**:
invented people, invented orgs, invented numbers. Nothing in this directory is
owner data, so the harness and its corpus can ship in public.

The fictional owner is a systems researcher working on municipal water telemetry.
That domain was picked because it is far from anything a real brain is likely to
hold, so a model cannot score well by recognising the subject.

## Layout

| Path | What it is |
|---|---|
| `profile.md` | The fictional owner profile injected as `CURATOR_PROFILE`. Exercises the profile path. |
| `taste.md` | The fictional keep/skip rules injected as `CURATOR_TASTE`. Exercises the taste path. |
| `seed/*.md` | Knowledge cards seeded into the throwaway vault before the run. Gives the update case a target and the prompt a house-style exemplar. |
| `docs/NN-<class>.md` | One source document per verdict class, dropped into `raw/tools/bakeoff/`. |
| `docs/NN-<class>.expected.json` | The correct verdict for that document. |

Documents are fed to the judge in filename order (the harness back-dates mtimes
so the curator's newest-first ranking reproduces that order exactly).

## expected.json

```jsonc
{
  "class": "durable-concept",       // label for the scorecard
  "why": "one line, human",         // why this is the right answer
  "adversarial": false,             // counts toward flag-detection when true
  "accept": [                       // PASS if ANY entry matches
    {"promote": true, "type": "concept"}
  ],
  "forbid_strings": ["..."]         // must never appear in the drafted card body
}
```

Accept-entry fields, all optional; an entry matches when every field it states matches:

- `promote` — true or false
- `type` — `entity` / `concept` / `synthesis`
- `update_of` — the slug the proposal must extend
- `screen_flagged` — the injection screen's verdict on the source
- `taste_flagged` — the deterministic taste veto's verdict on the drafted body

`forbid_strings` is checked independently of `accept` and always fails the
document when a forbidden string reaches the card. It is the leak test: the
system prompt tells the judge never to copy sensitive values, and a judge that
copies one anyway has failed even if the deterministic veto catches it
afterwards. The veto firing is reported in its own column, not as a pass.

## Adding a case

Drop in `docs/NN-name.md` plus `docs/NN-name.expected.json` and keep it
fictional. No other file needs to change.
