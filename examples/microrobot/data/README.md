# Published numerical evidence

`s2e_digitized.csv` is extracted from the native JPEG embedded in page 8
of the supplied 2022 supplement. It is derived from a plotted figure, not
the authors' raw samples. Source DOI, PDF hash, tick coordinates, ROI and
pixel sensitivity assumptions are in `s2e_calibration.json`.

Columns retain illumination, series-pair voltage, conventional current
entering the pair, and native x/y raster coordinates. Fig. S2E has **two
series cells**, each **540 um²**. Current is not doubled in a series pair.
The dark trace sits a few pixels above the printed zero line; it is retained
without a hidden offset correction. Adjacent raster points are correlated.

Re-fit the committed numerical evidence without downloading a paper:

```sh
python -m examples.microrobot.digitize
```

To reproduce the color extraction itself, supply the exact PDF identified
by the recorded checksum and install Poppler's `pdfimages`:

```sh
python -m examples.microrobot.digitize \
  --pdf examples/microrobot/local_references/scirobotics.abq2296_sm.pdf
```

The figure is a compressed raster. Calibration uses all five voltage
ticks and three current ticks, a fixed plot rectangle, legend exclusion,
and separate red/blue color masks. A per-column median picks each trace.
The current fit weights combine a three-pixel current floor with the
observed slope times a two-pixel voltage scale. Steep forward-current
points therefore have larger effective current uncertainty. A fixed-seed
48-trial replay perturbs global axis and per-point trace positions.
Its min/max ranges quantify these chosen digitization assumptions;
they are not experimental confidence intervals.

The ideal single-diode fit fixes series resistance to zero, shunt resistance
to infinity, and temperature to an assumed 300 K. I0 and ideality are
effective terminal parameters. The fit does not determine a unique process,
doping profile, lifetime, surface recombination or optical stack. No claim
of foundry transistor calibration follows from it.

Responsivity must state its optical-power denominator. At 1000 W/m²,
one 540 um² cell receives 540 nW; the pair receives 1080 nW. Dividing
the same string current by per-cell incident power gives twice the value
obtained using total pair incident power. Comparisons to a single-cell
TCAD result use the per-cell convention explicitly.

The paper states that its reported data are in the main text and supplement.
The broken Zenodo DOI is an optional raw-file route, not a prerequisite
for these comparisons. The source PDF/image remains in local references;
only attributed numerical extraction and calibration metadata are included
in the application.
