---
type: capture
source: raw/workspaces/pipelines/SKILL.md
created: 2026-06-01
---

# SKILL.md — ring-telemetry-digest

Job that assembles the weekly telemetry digest for the Meridian eastern ring.
Runs on the pipeline box. This file is what the job reads; edit it there, not here.

## Schedule

    cadence: weekly
    day: monday
    time: 06:15 America/Chicago
    retry: 2, backoff 900s
    lock: /var/run/ring-digest.lock

## Sources

    source_ids:
      - ring-east-hx40-a       # 41 probes, 5 min interval
      - ring-east-hx40-b       # 41 probes, 5 min interval, drift partners
      - ring-east-hx30-legacy  # 12 probes, 15 min interval
      - meridian-scada-export  # nightly csv drop, sftp
    query_id: q_8841_ring_east_rollup
    window_days: 7
    warmup_days: 2

## Transform steps

1. `pull_raw --source {source_id} --since {window_start}`
2. `align --interval 15m --method mean --min-coverage 0.8`
3. `pair_diff --pairs ring-east-pairs.yaml --window 90d`
4. `flag --rule chlorine_low --threshold 0.2 --units mg/L`
5. `flag --rule differential_break --z 4.0`
6. `render --template digest-weekly.j2 --out digest/{iso_week}.md`
7. `notify --channel pilot-coord --only-if flags>0`

## Render template variables

    {{ ring_name }} {{ iso_week }} {{ coverage_pct }} {{ flag_table }}
    {{ drift_plot_png }} {{ worst_offenders | top(5) }}

## Notes for whoever maintains this

Do not change `--min-coverage` without telling Ines; the coverage number goes in
the monthly report to the regulator and a step change looks like a fault. The
`warmup_days: 2` is there because the SCADA export lags by a day and a half.
