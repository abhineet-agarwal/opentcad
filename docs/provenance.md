# Sources and provenance

Every run records where each number it used came from. The record lists:
- each value the run read from a data file or from the code, with the source
  that file or code cites;
- the models it used and the papers their equations come from;
- the files it read, with their SHA-256;
- the code version.

Nothing is filled in by guessing. A value without a source is listed as having
none, and a value OpenTCAD chose itself is labelled as OpenTCAD's own.

## What a run records

- **Values from data files.** These are the material parameters the solver
  actually read (not every value in the file), the implant moments at each
  energy used, and the diffusion coefficients of each dopant that was annealed.
- **Values in the code:**
  - physical constants (CODATA 2018);
  - Deal–Grove oxidation coefficients;
  - model constants such as Slotboom's E_ref and N_ref and the Fermi–Dirac ξ;
  - the implant's lateral-straggle ratio;
  - the n_i(T) used by Fair diffusion.
- **Models.** Each chosen model with its settings (for example Canali's driving
  force), and the papers it cites.
- **Files.** Every data file read, with its SHA-256.
- **Inputs.** A hash of the simulation's content. When run from the command
  line, also the file's path and SHA-256.
- **Code.** The OpenTCAD version, the git commit and whether the package has
  uncommitted changes, and the Python and package versions.

Some things are not itemized:
- the values in your simulation file (the hash identifies them, and the file
  holds them);
- numerical settings such as mesh size and solver tolerances;
- deposition and etch steps, which take only your inputs.

## Where to see it

On the command line, `opentcad run` writes the record into the results file and
prints a summary:

```bash
opentcad run examples/decks/pn_diode.yaml
# results → examples/decks/pn_diode.results.json
# sources: 38 value(s) from data files and code, citing 7 source(s); 2 are OpenTCAD's own values, not from a publication. ...
opentcad sources examples/decks/pn_diode.results.json             # every value
opentcad sources examples/decks/pn_diode.results.json --missing   # only those with no published source
```

`opentcad sources` prints each value under its material or table, the source
IDs it cites, and then the sources with DOI links:

```text
Models
  mobility: "Klaassen"  [S1]
  recombination: ["SRH"]  [S2, S3]
...
Values
  Silicon  (opentcad/materials/params/Si.yaml)
    mobility_klaassen.mu_max_e = 1417  [S1]
    ...
    ni_cm3_300K = 9.65e+09  [S5]
    permittivity_relative = 11.7  [S6]
    recombination.tau_n_s = 1e-05  [S7]
...
Sources
  S1: D. B. M. Klaassen, A unified mobility model for device simulation - I. ...,
      Solid-State Electron. 35, 953 (1992)  https://doi.org/10.1016/0038-1101(92)90325-7
  ...
  S5: P. P. Altermatt, A. Schenk, F. Geelhaar, G. Heiser, Reassessment of the intrinsic
      carrier density in crystalline silicon ..., J. Appl. Phys. 93, 1598 (2003)
      https://doi.org/10.1063/1.1529297
  ...
  S7 (default): OpenTCAD's nominal value, not from a publication — Real lifetimes
      depend on the wafer and process ...
```

A value with no source at all shows `[NO SOURCE]`.

Elsewhere:
- **Sweeps:** each point's JSON in `points/` has its own record.
- **Design searches:** each candidate's JSON does.
- **GUI:**
  - The assistant page has a **Sources** tab after a run, and its reply in the
    conversation says how many values have no source.
  - The main page shows a **Sources** expander under the result.
  - Both can download the record as JSON.

From Python, `run_deck` returns it as `result.provenance`. To record your own
script, wrap it in `recording()`:

```python
from opentcad.io import load_deck, run_deck
from opentcad.provenance import recording

result = run_deck(load_deck("examples/decks/pn_diode.yaml"))
print(result.provenance.summary())
for v in result.provenance.without_source():
    print(v.group, v.name, v.value)

with recording() as rec:          # anything that reads data inside the block
    ...
record = rec.to_dict()            # the same JSON form as in the results file
```

## Citing values in a data file

Material files and dopant tables give their sources in two top-level sections:

```yaml
sources:
  green1990:
    cite: M. A. Green, Intrinsic concentration, effective densities of states,
      and effective mass in silicon, J. Appl. Phys. 67, 2944 (1990)
    doi: 10.1063/1.345414
  klaassen1992:
    cite: D. B. M. Klaassen, A unified mobility model ..., Solid-State Electron. 35, 953 (1992)
    doi: 10.1016/0038-1101(92)90325-7
cite:
  bandgap.Eg_eV_300K: green1990        # one value
  mobility_klaassen: klaassen1992      # every value in the block
  recombination.Cn_cm6_per_s: [dziewior1977, other_source]   # a list is fine
```

- A value's source is its own `cite` entry if it has one, otherwise its
  block's entry.
- A source needs `cite`. It may also give `doi`, `url` and `note` (the table or
  equation, or a caveat).
- `kind` defaults to `literature`. The other kinds are:

  | Kind | Meaning |
  |---|---|
  | `fit` | fitted to data (written by `write_material_variant`) |
  | `override` | set in code with `apply_overrides`, replacing the file's value |
  | `placeholder` | not used by the solver; kept for the file format |
  | `default` | OpenTCAD's own value, not from a publication: a built-in value for a field the file doesn't give, or a nominal value the file or code sets |
  | `constant` | a physical constant |
  | `input` | your simulation file |

- These are errors, and the file doesn't load:
  - a `cite` entry for a value the file doesn't have;
  - a `cite` entry naming a key missing from `sources`;
  - a source without `cite`, or with an unknown field.
- A value with no `cite` entry loads. Runs report it as having no source, and
  `load_material("Si").uncited()` lists such values.

Calibration keeps this straight:
- `write_material_variant` gives the fitted values a `fit` source naming what
  they were fitted to. Every other value keeps the base file's source.
- `apply_overrides` marks the values it sets as `override`.

## What a citation does and doesn't establish

A citation says where a value is published. Most shipped citations were moved
from the comments the files already had, as written. Their DOIs, authors and
titles were checked against Crossref, but the values themselves were not
checked against the papers.

These were checked: the source's note says where the value appears.

| Value | Source | Where it appears |
|---|---|---|
| Silicon n_i, 9.65e9 cm⁻³ | Altermatt et al. (2003) | abstract. The file used to cite Green (1990), whose abstract gives 1.08e10 |
| Silicon Nv, 3.1e19 cm⁻³ | Green (1990) | abstract |
| Silicon Nc, 2.86e19 cm⁻³ | Palankovski (TU Wien thesis, 2000) | Table 3.20, a fit to Green's data (−0.14 + 1.56 + 1.44 at 300 K) |
| Varshni α = 4.73e-4 eV/K, β = 636 K | Klaassen (SISDEP 1991); Palankovski (2000) | eq. (20), which credits Thurmond (1975); Table 3.8 |
| Constant mobilities, 1350 and 480 cm²/Vs | Ludwig & Watters (1956) | abstract: 1350 ± 100 and 480 ± 15 at 300 K |
| High-field exponents β = 2 (electrons), 1 (holes) | Palankovski (2000) | Table 3.27 |
| SiO₂ electron affinity, 0.95 eV | Williams (1965) | abstract: the SiO₂ conduction band is about 0.9 eV below vacuum |
| Slotboom N_ref, 1e17 cm⁻³ | Slotboom & de Graaff (1976) | as Klaassen (1991, eq. 22) quotes it |
| Si consumed per unit oxide, 0.44 | Radi (TU Wien thesis, 1998) | sec. 2.2 |

## OpenTCAD's own values

These have no publication. They are marked `default`, every run counts them,
and `opentcad sources --missing` lists them:
- **Silicon SRH lifetimes,** 10 µs for electrons and holes. Real lifetimes depend
  on the wafer and process; measure or fit them.
- **SRH trap level,** mid-gap.
- **Implant lateral straggle,** σ_lat / ΔRp = 0.7.

## Values without a recorded source

Phase 3 of the
[roadmap](https://github.com/abhineet-agarwal/opentcad/blob/main/PHASES.md)
asks for this list to be empty; `tests/provenance` stops it from growing.

| Where | Value | Why it is still uncited |
|---|---|---|
| `Si.yaml` | `recombination.B_rad_cm3_per_s`, 9.5e-15 cm³/s | not found in a source; the Ioffe database gives 1.1e-14 (Gerlach et al., 1972) and Trupke et al. (2003) report a lower value |
| `Si.yaml` | `velocity_saturation.vsat_h_cm_s`, 0.72e7 cm/s | not found in a source; Palankovski (2000, Table 3.31) gives 0.704e7 |
| Slotboom model code | `E_ref_eV`, 6.92 meV | Slotboom & de Graaff's fit uses 9 mV with N_ref = 1e17 cm⁻³ (Klaassen 1991, eq. 22); no paper is recorded for 6.92 meV with that N_ref |

These carried-over citations are doubtful and need checking against the papers:
- **Silicon vsat_e, 1.02e7 cm/s, cited to Canali et al. (1975):** Palankovski
  (2000, Table 3.31) gives 1.0e7, and Canali's own fit could not be checked.
- **The implant tables' "Sze & Ng, Table 14.4":** not checked; the table
  number may be wrong.
- **SiO₂ band gap, cited to "DiMaria (1995)":** the file gives no fuller
  reference.
