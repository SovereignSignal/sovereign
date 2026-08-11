---
type: capture
source: raw/tools/notes/incident-inc-2026-0417-writeup
created: 2026-06-24
---

# Incident INC-2026-0417: free chlorine excursion, Fenwick Street vault

Incident writeup, filed with Meridian's operations log. Closed, no service impact,
no notification to the regulator.

**What happened.** At 03:12 on 18 June the ring-east feed raised a chlorine-low
flag at the Fenwick Street measurement point, reading 0.11 mg/L against a 0.2
threshold. The on-call operator saw the flag at 06:40 and a crew was dispatched at
07:15. The crew found nothing: bench check on a grab sample put free chlorine at
0.34 mg/L, well inside range. The probe was pulled and bench tested clean. Total
cost of the excursion was one crew morning and a pulled probe that did not need
pulling.

**What actually went wrong.** The Fenwick point's drift partner had been swapped
out three weeks earlier during unrelated valve work and never re-registered as a
pair. The pairing table still listed the removed unit. So the differential term
was being computed against a serial number that was no longer in the ground, the
fit went unstable, and the correction it applied pushed a healthy reading below
threshold. The water was fine the whole time. The instrument record was not.

**The rule that came out of it.** Nothing gets dispatched on a single instrument's
say-so. Before a crew moves on a threshold flag, three readings have to agree, and
they have to be independent of each other:

1. The probe's own repeat, at the next interval, uncorrected by any drift model.
2. Its registered partner's reading for the same interval, checked against the
   pairing table as it stands right now, not as it was configured.
3. Any third signal that is not the pair: an upstream point, a plant residual, or
   a grab sample if one is already scheduled.

If any two of the three disagree with each other, the finding is an instrument
fault, not a water event, and the ticket goes to maintenance rather than to a
crew. Only when all three agree does anything get dispatched.

The second half of the rule is that the pairing table gets checked as part of the
confirmation, not trusted. Every failure of this kind traces back to a table that
described the deployment as it was designed rather than as it stands.

**Follow-ups closed.** Pairing re-registered; the valve-work procedure now carries
a pairing check step; the three-way confirmation is in the on-call runbook.
