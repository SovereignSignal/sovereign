---
type: capture
source: https://telemetry-notes.example.com/drift-pair-calibration
created: 2026-05-18
---

# Drift-pair calibration: cancelling sensor drift without a reference lab

Field-deployed water sensors drift. Everyone knows this. The standard remedy is
an annual pull-and-recalibrate against a laboratory reference, which costs a
truck roll per sensor and leaves eleven months of quietly degrading data behind
it.

Drift-pair calibration is a different approach, and it does not need a reference
lab at all. The method is simple enough to state in a paragraph:

1. Deploy sensors in **pairs** at every measurement point, but deliberately pair
   two units from **different manufacturing lots**, ideally different vendors.
2. Log both readings continuously. Because the two units share the same physical
   input, any *common-mode* movement in the pair is the real signal.
3. Any *differential* movement between the pair is, by construction, drift in one
   of the two units. It cannot be the water.
4. Fit the differential term over a rolling ninety-day window. The fit gives you
   each unit's drift trajectory relative to its partner.
5. Anchor the pair to absolute truth **once**, at commissioning. From then on the
   pair self-corrects, and you only need a lab visit when the differential term
   stops being smooth, which is the signature of a fault rather than drift.

The counter-intuitive part is step 1. Operators instinctively want matched pairs
from the same lot, because matched units agree with each other. That agreement is
exactly what destroys the method: units from the same lot drift the same way, so
their differential stays near zero while both wander off together. Correlated
drift is invisible to a matched pair. You want partners that fail differently.

What this buys, in the deployments where it has been tried: truck rolls drop by
roughly four fifths, and the data record gains a continuous drift estimate rather
than twelve step corrections a year. What it costs: twice the sensors at each
point, which is only worth it where the sensor is cheap relative to the visit.
For municipal distribution rings, where a truck roll dwarfs the hardware, the
arithmetic is not close.

The technique generalises past water. Anything with a cheap sensor, an expensive
site visit, and a physical input two units can share is a candidate: air quality
networks, structural strain monitoring, cold chain logging. The requirement is
not the domain, it is the availability of an uncorrelated partner.
