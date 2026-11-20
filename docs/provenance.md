# Sources and provenance

Every run records where each number it used came from. The record lists:
- each value the run read from a data file or from the code, with the source
  that file or code cites;
- the models it used and the papers their equations come from;
- the files it read, with their SHA-256;
- the code version.

Nothing is filled in by guessing. A value without a source is listed as having
none.

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
# sources: 38 value(s) from data files and code, citing 6 source(s); 2 have no recorded source. ...
opentcad sources examples/decks/pn_diode.results.json             # every value
opentcad sources examples/decks/pn_diode.results.json --missing   # only those with no source
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
    recombination.tau_n_s = 1e-05  [NO SOURCE]
...
Sources
  S1: D. B. M. Klaassen, A unified mobility model for device simulation - I. ...,
      Solid-State Electron. 35, 953 (1992)  https://doi.org/10.1016/0038-1101(92)90325-7
  ...
  S5: P. P. Altermatt, A. Schenk, F. Geelhaar, G. Heiser, Reassessment of the intrinsic
      carrier density in crystalline silicon ..., J. Appl. Phys. 93, 1598 (2003)
      https://doi.org/10.1063/1.1529297
```

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
  | `default` | OpenTCAD's built-in value, used because the file doesn't give it |
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

A citation says where a value is published. The shipped citations were moved
from the comments the files already had, as written. Their DOIs, authors and
titles were checked against Crossref, but the values themselves were not checked
against the papers, with two exceptions:
- **Silicon's n_i (9.65e9 cm⁻³):** the value from Altermatt et al. (2003),
  whose abstract gives 9.65e9. The file used to cite Green (1990), whose
  abstract gives 1.08e10.
- **Silicon's Nv (3.1e19 cm⁻³):** now cited to Green (1990), whose abstract
  gives it.

## Values without a recorded source

These are the shipped values with no source yet. Phase 3 of the
[roadmap](https://github.com/abhineet-agarwal/opentcad/blob/main/PHASES.md)
asks for this list to be empty; `tests/provenance` stops it from growing.

| Where | Values |
|---|---|
| `Si.yaml` | `bandgap.varshni_alpha`, `bandgap.varshni_beta_K`, `Nc_cm3_300K`, `mobility_constant.electron_cm2_Vs`, `mobility_constant.hole_cm2_Vs`, `recombination.tau_n_s`, `recombination.tau_p_s`, `recombination.Et_eV`, `recombination.B_rad_cm3_per_s`, `velocity_saturation.vsat_h_cm_s`, `velocity_saturation.beta_e`, `velocity_saturation.beta_h` |
| `SiO2.yaml` | `electron_affinity_eV` (the file derives it from a 3.1 eV band offset it doesn't cite) |
| Slotboom model code | `E_ref_eV`, `N_ref_cm3` |
| Implant code | lateral straggle σ_lat / ΔRp = 0.7 |
| Oxidation code | Si consumed per unit oxide, 0.44 |
