# Contributing to OpenTCAD

Thanks for helping. The full contributor guide is
[docs/contributing.md](docs/contributing.md). It covers the development setup,
the ground rules, how to add materials, dopants, steps, analyses and models, how
the documentation is built, and open problems that make good first contributions.

The short version:

1. `pip install -e ".[dev,topography,gui]"`, then `pytest tests -q -m "not slow"`.
2. Fixed units (µm, cm⁻³, K, °C for process temperatures, eV, V). `MeshField`
   between modules. No invented or silently defaulted values: every parameter
   cites its source.
3. Physics changes come with a quantitative test and a row in
   [docs/validation.md](docs/validation.md).
4. Update the docs with the code, and regenerate the API reference with
   `python tools/gen_api_docs.py`.
5. Open an issue first for large changes.
