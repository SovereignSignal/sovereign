---
type: capture
source: https://tessellate.example.org/announcements/ttc-4-ratified
created: 2026-06-04
---

# TTC-4 ratified at the spring plenary; calibration group gets a new chair

The Tessellate Telemetry Consortium ratified the TTC-4 interchange specification
at its spring plenary on 2 June, closing a revision cycle that ran nineteen
months. TTC-4 is the first revision to change the wire format since the
consortium was founded in 2017.

The headline changes:

- **Per-reading uncertainty is now mandatory.** Every value carries an
  uncertainty estimate and the method that produced it. Under TTC-3 this was an
  optional extension that roughly a fifth of implementers populated.
- **Drift metadata is a first-class field.** A reading can now declare the drift
  model applied to it and the age of the last anchor, which is what the
  calibration working group has been pushing for since 2024.
- **Conformance gets a test lab.** The consortium has contracted an independent
  laboratory to run conformance testing from January 2027. Self-attestation ends
  with TTC-3.
- **Transport is unchanged.** Deployments can move to TTC-4 payloads over their
  existing transport without touching the network layer.

Membership now stands at 71 utilities and 17 vendors, up from 63 and 14 a year
ago.

The plenary also confirmed a leadership change. Marta Reyes-Hale steps down as
chair of the calibration working group after three years and is succeeded by
Dr. Ines Okonjo of Meridian Water Authority, who ran the uncertainty subgroup
through the TTC-4 cycle. Reyes-Hale remains a member of the group.

Implementers have until the autumn 2027 plenary before TTC-3 moves to maintenance
status. Vendors shipping conformant hardware today, including Halcyon Sensors,
have signalled firmware support for the new fields within two quarters.
