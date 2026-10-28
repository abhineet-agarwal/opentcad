# Evidence and attribution

Access checked 2026-10-26. The user-provided 2022 DOI contains a typo;
the correct DOI is **10.1126/scirobotics.abq2296**.

## Primary evidence retrieved

Reynolds et al., *Microscopic robots with onboard digital control*,
Science Robotics 7, eabq2296 (2022).
[DOI](https://doi.org/10.1126/scirobotics.abq2296),
[Cornell author PDF](https://mceuengroup.lassp.cornell.edu/sites/mceuen/files/publications/scirobotics.abq2296.pdf).
The PDF was downloaded and its Fig. 1 inspected visually. SHA256:
`4e9a538f61d01ddd80d7c45cf117dc9e25f8b49e9e87b07438123e8ad4f6022f`.
The copyrighted paper is not redistributed with this application.

| Published item | Location / extent of disclosure |
|---|---|
| XT018 180 nm CMOS SOI; current reference, relaxation clock, divider, phase shifter and drivers | Fig. 1; Circuit design, pp. 6-7 |
| Two large PVs for actuators and two smaller PVs for IC; large pair tested in series | Fig. 1D/E; Circuit testing, p. 8 |
| Approximately 32 kHz clock; eight phases spaced by 1/8 period | Circuit design, pp. 6-7 |
| Approximately ±0.6 V outputs; about 0.3 A/W responsivity; frequency dependent on illumination | Fig. 1; Circuit testing, p. 8 |
| Exposed Pt ground electrodes in solution | Purcell-bot description, p. 2; Fig. 3 |
| Controller footprint 94 × 55 um; Pt/Ti actuator stack approximately 7/2 nm | pp. 1-2 |
| 660 nm source for Purcell-bot/dogbot, 600 nm for antbot | Operation methods, p. 8 |
| Fabrication sequence described, with full recipe referred to supplement | Fig. 2; Fabrication process section |

These are architectural and approximate measurement anchors, not enough
to reconstruct transistor sizing or calibrate a PV structure.

## Supplement retrieved locally on 2026-10-27

The user supplied the 13-page supplementary PDF after publisher access had
returned HTTP 403. Its source is
[the publisher supplement](https://www.science.org/doi/suppl/10.1126/scirobotics.abq2296/suppl_file/scirobotics.abq2296_sm.pdf).
An unchanged local copy is retained in the git-ignored `local_references/`.
SHA256: `43138926560d636d64845f7f708ba6026e26446f79df2962cc8e1355ed6b9fd4`.
The text and all six supplementary figures were inspected.

Figure S1B confirms that the logic and actuator PV pairs share their lower
rail. The actuator interface is shown between the actuator pair's midpoint
and an output switched to the upper/lower actuator rails. Combine this
electrical diagram with the exposed Pt/electrolyte return described in the
main paper; the midpoint metal is not an ideal fixed electrolyte potential.
The four-cell logic array in the first conceptual experiment was our
adaptation. The published-data experiment now uses three cells to respect
the controller voltage range; neither arrangement is the paper's logic pair.

Figure S2E supplies approximate published anchors: each large PV has area
540 um²; the two in series have Voc about 1.24 V (0.62 V per cell) and Isc
about 150 nA at 1000 W/m². Both dark and illuminated curves are plotted.
These are caption values, not digitized traces or fitted parameters. S2D's
nominal frequency-selection setting and measured frequency must be kept
distinct. The manufacturing recipe is detailed, but the supplement supplies
block diagrams/CAD images rather than transistor-level schematics, W/L or
timing R/C values, and does not give a calibrated PV doping profile.
Apparent dimensions in micrographs are not treated as device dimensions.

## Raw dataset still unavailable: registry audit 2026-10-27

The [data DOI printed in the paper](https://doi.org/10.5281/zenodo.7008281)
returns 404 / DOI Not Found. The
[Zenodo record API](https://zenodo.org/api/records/7008281) returns 404 with
`The persistent identifier is not registered.` The
[DataCite DOI API](https://api.datacite.org/dois/10.5281/zenodo.7008281) also
returns 404. Direct title search in Zenodo and title/related-article-DOI
search in DataCite returned zero records; an Internet Archive availability
lookup found no snapshot for `zenodo.org/record/7008281`.
There is no verified replacement link. These results do not establish
whether the paper cites a typo, an unpublished reservation or another issue.
The authors should be asked for the correct DOI and underlying figure data.
The paper states that its reported data are in the main text and supplement.
The missing archive is not a prerequisite. S2E's plotted dark/illuminated
curves have now been digitized, fitted and compared, with tick coordinates,
PDF checksum, raster coordinates and pixel-sensitivity assumptions recorded
in `data/` and `results/published/`. This is extracted figure evidence,
not the authors' raw files.

## Supporting and future sources

Miskin et al., *Electronically integrated, mass-manufactured, microscopic
robots*, Nature 584, 557-561 (2020).
[DOI](https://doi.org/10.1038/s41586-020-2626-9),
[author PDF](https://cohengroup.ccmr.cornell.edu/userfiles/pubs/Miskin_Nature_2020.pdf).
Downloaded SHA256: `00b896c45a2a60dfa87ab3ea7bd3fba4c191a04b2c514e0e6b69bf9443c8e1db`.
Methods distinguish double-layer and adsorption charging; the adsorption
charge scale is approximately 130 uC/cm² = 1.3 C/m². The reported 50 ms
mechanical response belongs to a particular Pt/graphene cantilever geometry.
Neither is a calibrated parameter set for the 2022 Pt/Ti robot legs.
Potentials against Ag/AgCl in actuator characterization must not be identified
with CMOS terminal voltage against an onboard Pt return electrode.

Lassiter et al., *Microscopic Robots That Sense, Think, Act, and Compute*
(2025), [arXiv:2503.23085](https://arxiv.org/abs/2503.23085),
[journal DOI supplied by user](https://doi.org/10.1126/scirobotics.adu8009).
Only the arXiv abstract/metadata were checked; its processor, memory, sensing
and communication architecture is future work, not the initial design.

## Parameter provenance policy

1. **Published:** values above retain source and approximate precision.
2. **Extracted:** `data/s2e_digitized.csv` contains reconstructed paper traces;
   DD/SPICE metrics are separately labelled simulated results.
3. **Fitted:** the ideal single-diode terminal parameters in
   `results/published/pv_fit.json` use the digitized traces, assumed 300 K,
   zero series resistance and infinite shunt resistance. Pixel-sensitivity
   ranges are not confidence intervals or unique TCAD parameter inference.
4. **Design choice:** all geometry/doping/optics in `pv.py`, all behavioral
   parameters in `system.Parameters`, and all ring W/L/R/C in `spice.py`.
   The new `circuits/starved_clock.spice` dimensions, capacitor geometry,
   three-cell logic allocation, storage capacitors and RTL divider are
   also our choices. The bias is not a reproduction of the paper's PTAT circuit.

PV doping, lifetime, reflection, absorption, sidewall recombination and
contact loss cannot be uniquely inferred from one responsivity and Voc.
Adsorption midpoint, width, rates, leakage, return area and solution resistance
also cannot be uniquely inferred from the reported output waveforms.

Our contributions are the OpenTCAD optical field/units support, conservation
correction, terminal fitting/MPP/SPICE export and numerical regressions;
the attributed PV extraction; and the new functional clock, phase RTL and
separate auditable coupling experiment. Attribution for the original microrobot
concepts belongs to the cited
authors; DD, meshing, numerics and circuit models belong respectively to
DEVSIM, Gmsh, NumPy/SciPy and the SKY130/ngspice projects. Repository code
and the notebook use the root Apache-2.0 license; paper and PDK licenses
remain those of their owners.
