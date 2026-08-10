---
type: capture
source: raw/tools/notes/halcyon-vendor-brief
created: 2026-05-22
---

# Vendor brief: Halcyon Sensors

Notes from the vendor qualification call, plus what I already knew.

Halcyon Sensors is the hardware vendor we contracted for the Meridian eastern
ring pilot. Private company, based in Duluth, founded 2016 by two ex-process
control engineers. Roughly 90 staff. They make one product line and nothing else:
submersible multiparameter probes for potable distribution networks.

Product line is the HX series. HX-40 is the current unit, HX-30 is still in the
field at a lot of utilities and is supported through 2029. The HX-40 carries
conductivity, temperature, turbidity, and free chlorine on one stem, which is the
reason we picked them: four parameters, one tap, one calibration visit.

Things worth remembering about them:

- They publish their drift curves. Almost nobody does. The HX-40 datasheet gives
  chlorine drift as a distribution, not a single worst-case number, which is what
  made drift-pair modelling possible for us at all.
- Their firmware is signed but the telemetry format is open and documented. They
  were an early TTC member and their output is conformant to TTC-3 out of the box.
- They are small enough to answer engineering questions directly. Our contact is
  Priya Raman, who runs field applications. She has twice sent us pre-release
  firmware to test a fix.
- Single point of failure risk: one product line, one factory, and their probe
  bodies come from a single machining subcontractor. A supply shock hits them
  harder than it would hit a diversified vendor.
- They do not do integration services. They ship hardware and a protocol
  document and expect the utility or its consultant to do the rest. That is
  precisely the gap our practice fills, which is why the relationship works.

Commercially they are the mid-tier option: more expensive than the commodity
Chinese probes, materially cheaper than the incumbent instrument houses, and the
only one of the three that will talk to a one-person consultancy.
