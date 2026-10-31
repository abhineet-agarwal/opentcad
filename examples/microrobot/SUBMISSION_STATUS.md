# Scope, evidence and limitations

SPDX-License-Identifier: Apache-2.0

Team: Abhineet Agarwal, IIT Bombay. IEEE member: No. SSCS member: No.

The deliverable is an executable end-to-end mixed-abstraction model with
separately validated transistor blocks. Its purpose is to make the electrical,
electrochemical and mechanical assumptions inspectable and executable.

| Stage | What the front notebook uses | What it establishes |
|---|---|---|
| PV | Actual OpenTCAD/DEVSIM drift-diffusion dark/light IV tables, scaled by assumed cell area and series count | Conceptual numerical device behavior; no measured-device/process calibration |
| Clock / first DFF | Archived SKY130 schematic supply-dependent characterization | Bounded lookup; no transistor transient in the coupled system |
| Divider / reset | Behavioral state/phase model | Assumed digital policy, not synthesized transistor implementation |
| Driver | Finite resistance and explicit current/energy accounting | Behavioral switch model, not coupled transistor level shifting |
| Electrode / return | Nonlinear adsorption, double layer, faradaic branch and finite Pt return | Assumed reduced electrochemistry; absolute electrode offset is unknown |
| Mechanics | Relaxation and curvature-to-hinge bending mapping | Predicted bending under assumed parameters; no contact mechanics or walking |

**Full transistor-coupled startup failed and is unresolved.** The full controller
has not been demonstrated to start, survive darkness and restart with the PV,
reset, divider, transistor drivers and nonlinear actuator coupled together.
The mixed-abstraction run must not be presented as closing that failure.
The nominal, dark/recovery, half-timestep and all-dark checks are numerical
checks of the reduced system. Passing them does not validate a physical robot.

The separate compact clock evidence is under
`results/clock_compact_placement/`, `results/clock_compact_convergence/` and
`results/clock_compact_hot85/`. Native and GDS-roundtrip DRC/LVS and extracted
RC concern the clock macro. Nominal timestep consistency uses 25 and 12.5 ns.
The hot case changes electronics to 85 °C while fitted PV remains at 26.85 °C;
it is not whole-device thermal qualification. The earlier pre/post-layout
comparison is under `results/clock_layout_review/`; its README retains its
historical review status. The compact macro remains separate from the
schematic lookup used by the end-to-end demonstration.

No complete controller placement/routing, PVT/mismatch signoff, footprint
closure, optical command reception, measured actuator calibration or locomotion
is claimed. Storage capacitance, cell isolation, power margins and practical
level shifting remain design assumptions or unresolved implementation costs.

Source PDFs and raw SPICE transients are excluded. Supplied measurement CSVs
whose source license was not verified are also excluded and are not needed
for the front notebook. Optional historical measurement comparisons require
manual acquisition and independent rights/provenance checks; see ATTRIBUTION.md.
Pinned Python packages still require their native dependencies. Colab and
Linux execution are untested unless a fresh execution record explicitly says
otherwise. The package does not install a PDK or external simulation tools.

The official award page specifies an October 31, 2026, 11:59 AM Pacific
deadline. That instant has passed on November 1 in India. This local package
makes no eligibility or late-submission promise. No submission, push,
publication, organizer message or fabrication was initiated.

Official rules: https://sscs.ieee.org/membership/awards/ieee-sscs-code-a-chip-travel-grant-awards/
