# Local Reynolds (2022) data comparison

This directory contains derived summaries and rendered figures from six
user-supplied CSV files. Source CSVs remain external and were only read. Their
SHA256 hashes, encodings, column mappings, counts and native ranges are recorded
in `comparison.json`. The user attributes the files to Zenodo; repository identity
and redistribution rights were not independently verified. No raw arrays are
included here.

The report generator leaves `results/published/pv_fit.json` and all default model
parameters unchanged. It performs no fitting or simulation. Reproduce from the
repository root, supplying the local source path explicitly:

```sh
MPLCONFIGDIR=/tmp/opentcad-reynolds-mpl-cache .venv/bin/python \
  -m examples.microrobot.reynolds_data \
  --source-dir /path/to/Reynolds-2022-data \
  --output examples/microrobot/local_runs/reynolds2022_review
```

Choose a fresh or empty output directory. The CLI rejects nonempty destinations
and existing files before reading data or writing results. This preservation
guard was added after the accepted analysis; `comparison.json` retains the SHA
of the code that actually generated it. The later workflow-code SHA and full
test checkpoint are recorded separately in `validation.txt`. Accepted plots and
numeric summaries were not regenerated for this guard-only change.

The accepted local execution used
`/Users/abhineet/Downloads/Reynolds-2022-data` on 2026-10-30. All six files passed
strict grouped-row validation. The independent series lengths are:

| File | Groups and point counts |
| --- | --- |
| Fig3_PurcellBot | Motion 230; inset 9 |
| Fig4_PurcellBot | Motion/speed 745; feet 60 |
| Fig5_Dogbot | Motion 201 |
| FigS2_CircuitTesting | Current at 2.5 sun 100004; at 7 sun 100004; phase voltages 100004; irradiance/voltage 22; irradiance/current 27; irradiance/frequency 32; dark IV 15003; 1 sun IV 15003 |
| FigS4_LEGO_purcell | Motion 6; inset 5 |
| FigS6_DogbotCircuit | Current/time 318448 |

The source name `Fig4_PurcellBot.csv` is retained literally; the paper's Fig. 4
is Antbot. The S2C current header literally reads `Current (µm)`; the published
figure's right axis confirms µA. This explicit override is recorded in JSON;
native numbers and literal headers remain intact. S2C current and voltage are
circuit output amplitudes. S2D frequency is a separate group. A sun here means
1 kW/m² of the stated illumination, not a standard solar spectrum.

`pv_comparison.png` compares every S2E sample against the frozen raster fit.
Native measured µA are multiplied by 1e-6, retaining conventional entering
current; the reusable model's delivering current is negated. S2E concerns two
540 µm² actuator PVs in series. The historical 300 K is an assumption, not a
measured temperature. This evidence does not calibrate small logic PVs or a
physical TCAD structure.

| Derived quantity | Dark | 1 sun |
| --- | ---: | ---: |
| All-sample RMS model error (nA) | 13.5564 | 11.6578 |
| Equal occupied 25 mV bin RMS error (nA) | 14.2162 | 13.0053 |
| Median entering current for \|V\| < 10 mV (nA) | 1.86163 | -148.106 |
| Acquisition-adjacent zero crossings | 0 | 4 |

The illuminated crossings span 1.234967–1.247900 V; their median is 1.242843 V.
These are local interpolations between adjacent acquisitions, not an inferred
unique Voc. Repeated voltages have different currents, so the loader preserves
order and does not sort, average, interpolate globally or subtract offsets.
The JSON also reports current-sign branches and voltage intervals separately.
Sample metrics weight each acquisition equally. The second RMS averages the
mean squared residuals of occupied 25 mV voltage bins equally; neither assumes
experimental uncertainty.

The highest observed generating sample is 161.78247236 nW at 1.12934 V and
143.254 nA delivered, versus the historical smooth model's 147.38597112 nW.
The observed/model ratio is 1.097679; the finite-window median delivered
current/model Isc ratio is 1.019576. These ratios compare different extraction
methods. The sample maximum is sensitive to noise and extreme-value selection;
it is not a smoothed MPP, validation tolerance or recalibration factor.

`dataset_overview.png` shows the remaining source groups using native axes and
units, including motion insets, speed, current traces, phase outputs and
irradiance scatter. Nonmonotone irradiance observations are not joined into an
invented continuous curve.

Executed checks:

```sh
.venv/bin/ruff check examples/microrobot/reynolds_data.py tests/integration/test_reynolds_data.py
.venv/bin/ruff format --check examples/microrobot/reynolds_data.py tests/integration/test_reynolds_data.py
.venv/bin/python -m pytest tests/integration/test_reynolds_data.py tests/device/test_compact_pv.py -q
```

Ruff checks passed and 22 tests passed: 18 new synthetic contract tests and four
existing compact-PV tests. The latter include a small ngspice DC export
round-trip test in a temporary directory; no microrobot/transient simulation was
rerun. Initial testing found an incorrect expected crossing in the synthetic
test (the correct local interpolation is 1.5 V); the assertion was corrected
before the passing run. Source SHA256 hashes were independently re-read and
matched the report; a separate audit also matched all six hashes, sizes, row
counts and all 16 grouped point counts/source-line ranges. The report's code
hash matched the executed module.
Both output figures were visually inspected. An initial Matplotlib/Fontconfig
cache warning was resolved for the final run using the temporary MPLCONFIGDIR.
