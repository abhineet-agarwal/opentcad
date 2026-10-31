# PV structure evidence before further TCAD

Audit date: 2026-10-31. Target: Reynolds et al. (2022), DOI
[10.1126/scirobotics.abq2296](https://doi.org/10.1126/scirobotics.abq2296).
**The supplied literature does not yet define an executable, process-faithful
Reynolds PV cross-section.** It establishes isolated SOI PVs and measured pair
behavior, but not the junction, doping profile, silicon thickness or contact
geometry needed to replace the conceptual DD structure. Do not adopt a new
physical parameter set by combining different papers' fabrication recipes.

This is a source audit, not a new fit or simulation. Existing solver/model files,
observations and calibration results were left unchanged. The prior
[fixed-structure feasibility result](../results/pv_calibration_feasibility/README.md)
still applies: even zero reflectance missed its low-bias photocurrent target by
30.393%; it does not identify which physical assumption is wrong.

## Sources and locators

Page numbers below are one-based PDF pages unless a printed journal page is
specified. The 2022 main PDF has 12 pages, with article pages 1-11 followed by an
additional information page. The supplement has 13 pages, including its cover.
The [provenance record](pv_structure_provenance.json) gives exact local hashes,
access limits and visual-inspection pages. Copyrighted PDFs and rendered source
images remain outside tracked evidence/export artifacts.

| ID | Primary source inspected | Relevant locator |
|---|---|---|
| R22 | Reynolds et al., [author-hosted main paper](https://mceuengroup.lassp.cornell.edu/sites/mceuen/files/publications/scirobotics.abq2296.pdf) | pp. 1-3, Fig. 1; p. 6, Circuit design; pp. 7-8, Circuit testing; p. 8, Robot manipulation and operation; p. 10, ref. 41 |
| R22-SM | [2022 supplement](https://www.science.org/doi/suppl/10.1126/scirobotics.abq2296/suppl_file/scirobotics.abq2296_sm.pdf), supplied local PDF | pp. 2-6, Materials and Methods: Fabrication Process; p. 7, Fig. S1; p. 8, Fig. S2; p. 9, Fig. S3 |
| M20 | Miskin et al., Nature 584, 557-561, [DOI](https://doi.org/10.1038/s41586-020-2626-9), supplied local PDF matching [author copy](https://cohengroup.ccmr.cornell.edu/userfiles/pubs/Miskin_Nature_2020.pdf) | PDF p. 3, Fig. 3; p. 6, Methods / Microrobot fabrication protocol; p. 14, Extended Data Fig. 6 |
| C20 | Cortese et al., PNAS 117, 9173-9179, [primary article on PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7196798/), DOI 10.1073/pnas.1919677117 | Results and Discussion, Fig. 2 and paragraphs on junction formation; Materials and Methods. This is R22 ref. 41 |
| X22 | Xu et al., ISSCC 2022 paper 12.1, supplied `a-210x340-1.pdf` | printed p. 194, text; printed p. 195 / PDF p. 2, Figs. 12.1.2-12.1.3; continuation references |
| CSV | Supplied Reynolds-2022-data directory | Existing [six-file audit](reynolds2022_AUDIT.md) and [inventory](reynolds2022_inventory.json); no new measurement metadata files found |

## Reynolds 2022: supported constraints and exact gaps

“Not disclosed” means not found in these inspected sources, not a claim that
the authors/foundry never measured or documented it elsewhere.

| Modeling input | Source-backed fact | Remaining gap / consequence |
|---|---|---|
| SOI versus bulk | R22 p. 1 identifies X-FAB 180 nm CMOS SOI; p. 6 names XT018. R22-SM p. 2 says SOI permits device silicon to be patterned into electrically isolated PVs/circuits; BOX protects the underside during release. Steps 6-7 on p. 3 etch to device silicon and then through it to BOX. | A bulk substrate with a full bottom ohmic terminal is not a reconstruction of the disclosed isolated SOI platform. A process-faithful model needs the actual isolated island and BOX boundaries. |
| Junction polarity/topology | R22 p. 8 describes silicon p-n PVs. Figs. 1D/E and S1A show PV positions and interconnect layout. | Neither the main paper nor R22-SM labels the actual PV well/diffusion junction, vertical versus lateral collection geometry, polarity profile, junction depth or implant species/dose/energy. A circuit diode symbol is not a semiconductor cross-section. |
| Device Si and BOX thickness | R22-SM distinguishes device Si, BOX and handle Si; Fig. S3 schematically shows these layers. | No numerical device-Si or BOX thickness found. The approximately 15 µm circuit height/step (R22 p. 9; R22-SM pp. 5-6) includes circuit topography and must not become absorber thickness. Fig. S3 caption explicitly warns that new film thicknesses are drawn enlarged. |
| Foundry contacts | R22-SM pp. 2-3, steps 2-4 open top-metal pads, expand them with about 10 nm Ti / 60 nm Pt, and encapsulate top contacts with 300 nm PECVD TEOS. Step 11 on p. 3 adds about 10 nm Ti / 60 nm Pt interconnects. | These are post-foundry pad/interconnect operations, not measurements of the metal/Si PV interface. Semiconductor contact material, silicide, window dimensions, selectivity, contact resistance and recombination remain unknown. Do not assign Ti/Pt directly as the foundry PV contact from this recipe. |
| Active area and metal shading | R22-SM p. 8, S2E caption gives each large actuator PV area as 540 µm². R22 Fig. 1 and SM Fig. S1 show two large and two small cells. | Caption does not define whether 540 µm² is junction, exposed aperture, or another layout area. Contact widths, optical aperture, shading fraction, perimeter and individual cell shape are not tabulated. Do not infer precise dimensions from micrographs. |
| Logic versus actuator scaling | R22 p. 2 identifies the large pair for legs and small pair for the circuit; Fig. S1B shows separate series pairs sharing the lower rail. S2E characterizes the large pair. | No 150 µm² logic-cell area or measured small-cell IV was found. `system.py` chooses 150 µm²; `published.py` scales a cell by 150/540 and explicitly labels equal current density as assumed. Area-only scaling does not establish equal perimeter loss, shading, contact geometry, dark current or voltage. |
| Series connection | R22 p. 8 and R22-SM p. 8, S2E: two large PVs in series; caption reports about 1.24 V open circuit, 0.62 V/cell and 150 nA short circuit at 1 kW/m². Fig. S1B visually identifies the actuator midpoint and common lower logic/actuator rail. | For equal cells, Vpair=2Vcell and Ipair=Icell; no factor of two in current. Uniform per-cell area conversion is Ipair=540 Iper_um². Pair IV does not independently measure either cell or their mismatch. The midpoint electrode is not a measured ideal electrolyte potential. |
| Optical wavelength and intensity | R22 p. 8 and R22-SM p. 8 explicitly attach 660 nm to S2A. S2E explicitly attaches 1 kW/m² to its illuminated pair curve. R22 p. 8 specifies 660 nm laser for robots in Figs. 3/5 and 600 nm LED for Fig. 4; illumination/imaging are from above. | S2E itself does not separately repeat a wavelength, beam spectrum, calibration uncertainty, angle or spatial uniformity. A 660 nm S2E comparison is context-compatible but not independently tagged in the supplied CSV/caption. Do not transfer antbot's 600 nm or a broadband one-sun spectrum to S2E. |
| Reflection, absorption, optical stack | R22-SM pp. 3-4 specifies encapsulation and shield steps: approximately 300 nm TEOS at steps 4, 9 and 12; approximately 200 nm Cr circuit shield at step 13; approximately 200 nm TEOS plus 500 cycles Al2O3 at step 14. Fig. S3 shows patterned coverage. | No measured R/T/EQE, absorption coefficient, optical constants, Al2O3 thickness-per-cycle or final PV-window stack is specified. These patterned films cannot simply be added into a uniform PV optical stack. Circuit shielding is not a quantified PV shading fraction. |
| Passivation and recombination | BOX underside protection and TEOS/Al2O3 encapsulation are explicit (R22-SM pp. 2-4). R22 p. 8 says circuit light shielding is essential and backside illumination causes malfunction. | Encapsulation establishes materials, not zero surface recombination, lifetime, fixed oxide charge or interface-trap density. No PV bulk lifetime, surface-recombination velocity, contact recombination or sidewall loss is measured. |
| Measurement state, temperature and dark offset | R22 pp. 7-8 describes laboratory circuit testing with metal shielding, probes, Ithaco 1211 and Picoscope; circuit output voltage uses a 100 MΩ resistor. The CSV audit records separate S2E dark/light acquisitions. | No S2E device temperature, irradiance uncertainty, sweep time/direction, device ID, electrical offset correction or full PV-IV instrument protocol is supplied. Circuit-output loading details do not fully specify S2E acquisition. Do not call assumed 300 K a measured condition, or equate pre-release circuit testing and released-robot optical stacks. |

The paper's approximately 0.3 A/W is a coarse measurement anchor. Its power
denominator must stay explicit: at 1000 W/m² one 540 µm² cell receives 540 nW,
while two illuminated cells receive 1080 nW. The same 150 nA string current is
approximately 0.278 A/W on a per-cell incident-power basis and 0.139 A/W on a
total-pair-power basis. This arithmetic is not a new measurement. Likewise,
150/540 current scaling would predict about 41.7 nA for a 150 µm² cell only under
the unverified equal-current-density assumption.

## The 2020 devices constrain a separate process, not XT018

M20 Methods, PDF p. 6, supplies unusually useful fabrication information:
Ultrasil boron-doped p-type SOI, 2 µm device Si, 0.1 ohm-cm resistivity, 500 nm
BOX and 500 µm handle. A 550 nm phosphosilicate-glass source containing 5 wt%
phosphorus is deposited at 350 °C; diffusion uses 1000 °C for 3 minutes in argon,
with a 75 °C/s ramp, followed by glass removal. **550 nm is source-glass
thickness, not n-emitter thickness.** This is diffusion, not a disclosed implant
dose. Resistivity alone is not an exact activated acceptor profile.

M20 Extended Data Fig. 6A/B, PDF p. 14, was checked visually. It shows an n-type
region above p-type Si, a locally exposed p-type ledge, separate Ti/Pt contacts
accessed from the top, and ALD SiOx surrounding the mesa. Neither contact is a
full-area transparent back contact. The caption identifies a 10 by 20 µm device,
785 nm illumination at 100 nW/µm² (=100,000 W/m²), and Voc around 700 mV.
That is a different area and roughly 100 times R22 S2E's stated irradiance, with
a different wavelength. The figure supplies no calibrated diffusion profile,
emitter thickness, measured reflectance, lifetime, surface recombination or
PV measurement temperature. Fig. 3 and Methods also describe SU-8 packaging,
distinct from the R22 post-foundry process.

The full M20 protocol is cited as ref. 41:
[10.21203/rs.3.pex-1012/v1](https://doi.org/10.21203/rs.3.pex-1012/v1).
Its DOI and official Protocol Exchange URL could not be fetched by the web tool
in this audit; its additional recipe details were not inspected or invented.
The supplied M20 article includes Methods and Extended Data, but no separate
2020 SI/protocol PDF was located in the targeted source inventory.

R22's own PV-comparison citation, ref. 41, is **C20**, not the M20 protocol.
C20 Materials and Methods also specifies Ultrasil boron-doped 2 µm SOI with
500 nm BOX; Results/Fig. 2 describes a diffused uniform p-n junction and etched
contacts. Its optical measurements use 532 nm. This corroborates a separate
custom SOI research process, not a numerical XT018 stack. The C20 SI Appendix
is linked by the primary article, but both its publisher link and PMC attachment
returned fetch failures in this audit; it was not reviewed. No conclusion here
depends on its uninspected contents.

## Xu ISSCC 2022 is a distinct bulk triple-well branch

X22 p. 194 and Fig. 12.1.3 on p. 195 explicitly describe a 55 nm United
Semiconductor Japan DDC triple-well process, using N+/P-well,
P-well/deep-N-well and deep-N-well/P-sub junctions. A negative cell ties
P-well to P-sub and N+ to deep-N-well; the positive cell shorts P-sub to
deep-N-well. The substrate floats, and opposite-polarity cells provide a supply
span exceeding 0.6 V. The semiconductor and interconnection cross-sections
were checked visually. These are useful topology evidence for that design.

They do not identify Reynolds' SOI junction. The 50 µm thinned die is not a
photovoltaic junction depth. No calibrated well/diffusion depths, doping
profiles, solar-cell areas or loaded IV are supplied. The plotted rail voltage
is no-load. Illumination is reported in lux, including 60 klux operation; no
source spectrum is supplied for conversion into the 660 nm W/m² input. Do not
merge this well stack, its floating substrate or its optical conditions with
R22 or use it to certify arbitrary series cells in another PDK.

The [current X-FAB XT018 platform description](https://www.xfab.com/xt018)
corroborates BCD-on-SOI/DTI isolation and BOX utility, but is not the historical
robot process card. It does not provide the R22 PV profile/contact geometry in
the inspected public description. Current platform options are not evidence
that a particular option was used in the 2022 robot.

## Decision and narrowly specified next evidence

No new DD run is justified as a **physical Reynolds calibration** from these
sources alone. The present `pv.py` values remain declared choices: 3 µm Si,
0.3 µm abrupt n emitter at 1e18 cm^-3, p base at 1e16 cm^-3, ideal transparent
full-width top/back contacts, insulating sides, 300 K, 10 µs bulk lifetimes,
660 nm, alpha=3000 cm^-1 and a scalar reflectance. The audit supports none of
those numerical structure/collection values as XT018 measurements. It also
does not support replacing them wholesale with M20's recipe.

The next requested evidence, in priority order, is:

1. **R22 PV cell definition/process cross-section:** selected XT018 PV device
   or drawn layers, well/diffusion polarity, device-Si and BOX thickness, active
   dopant profiles/junction depths, island isolation and any buried layers.
   Obtain an author-provided cross-section or the applicable permitted PDK
   device/process documentation. A dose alone still needs activation/profile.
2. **Cell layout and boundary conditions:** actual 540 µm² area definition,
   exposed optical aperture, contact windows/materials, metal coverage,
   perimeter, top/side/BOX interface properties and final patterned optical
   stack. Establish whether the S2E device was on handle Si or released.
3. **Matched measurement metadata:** S2E wavelength/spectrum, power calibration
   and illuminated area, temperature, terminal wiring and instrument offsets,
   acquisition timing/sweep directions. R/T or EQE would separate absorption
   from carrier collection; dark IV over temperatures and multiple areas would
   help separate bulk, perimeter and contact losses.
4. **Logic-cell evidence:** actual small-cell area/layout and at least a matched
   small-cell IV. Until then, 150 µm² and area scaling remain scenario inputs.

A reviewable future numerical definition would represent one finite, isolated
SOI cell with the documented junction and localized contacts, dielectric BOX
bottom and explicit surface/interface conditions, then compare two equal cells
in series against S2E. It must first resolve items 1-2; the source does not yet
supply their numeric values. Optical absorption, collection and area must not
be adjusted together to absorb one low-bias current discrepancy. Any separate
M20 reproduction should use M20's wavelength/irradiance and its own evidence
label rather than claim progress on XT018 identification.

## Executed checks and limits

Read `AGENTS.md`, the PDF skill, current `pv.py`, the feasibility README,
`references.md`, data README and existing CSV audit. Used Poppler `pdftotext
-layout` on all four local main/supplement/ISSCC sources, checked complete
relevant rendered pages visually (recorded in JSON), and recomputed SHA256.
Fetched the public R22 author PDF into `/tmp/pv-structure-audit/`; hash matches
the prior reference inventory. The sandbox download first failed DNS; the
approved escalated retry completed. The supplied Downloads/local supplement
copies have identical hashes. No files beyond the existing six CSVs were found
in the data directory. No raw data was copied or re-fit.

The optional `pypdf` availability check failed because it is absent from the
existing `.venv`; Poppler completed extraction/rendering without installation.
Some renders reported Fontconfig cache-directory warnings but completed and
were visually legible. Network source limitations above are access outcomes,
not proof that a supplement or protocol is unavailable to other readers. No
solver, circuit/full suite, fabrication, export, push or publication was run.
