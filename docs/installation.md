# Installation

OpenTCAD needs **Python 3.10 or newer** on Linux or macOS. Its numerical
dependencies (DEVSIM, Gmsh, PyVista, NumPy, SciPy) install as binary wheels.

OpenTCAD is not on PyPI yet, so install it from source:

{% tabs %}
{% tab title="Core" %}
```bash
git clone https://github.com/abhineet-agarwal/opentcad.git
cd opentcad
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

The core covers structures, meshing, implants, anneals, the device solver,
simulation files and sweeps.
{% endtab %}

{% tab title="Everything" %}
```bash
git clone https://github.com/abhineet-agarwal/opentcad.git
cd opentcad
python -m venv .venv
source .venv/bin/activate
pip install -e ".[topography,gui,dev]"
```
{% endtab %}

{% tab title="Contributor" %}
```bash
git clone https://github.com/abhineet-agarwal/opentcad.git
cd opentcad
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,topography,gui]"
pytest tests -q -m "not slow"
```

Then read the [contributing guide](contributing.md).
{% endtab %}
{% endtabs %}

## Optional extras

| Extra | Installs | Needed for |
|---|---|---|
| `topography` | ViennaLS | `deposit`, `etch` and `oxidize` steps |
| `gui` | Streamlit, Plotly | The browser GUI and interactive figures (`opentcad.viz.interactive`) |
| `dev` | pytest, ruff, mypy | Running the tests and linters |

Without an extra, everything else keeps working. A topography step without
ViennaLS raises an error that names the missing package.

{% hint style="warning" %}
**ViennaLS licence.** The current ViennaLS wheels (5.8.3, 5.9.0) ship a GPL v3
licence file, while OpenTCAD is Apache-2.0. That is why ViennaLS is an optional
extra rather than a dependency. Check that its licence suits your use before
distributing an environment that includes it.
{% endhint %}

## Check the installation

```bash
python -m opentcad plugins             # lists steps, analyses and models: the package imports
pytest tests/geometry -q               # meshing only; no DEVSIM needed
pytest tests -q -m "not slow"          # everything except the long end-to-end checks
```

`pip install` also creates the `opentcad` command. `python -m opentcad` is the
same command if your shell can't find it.

## The local model for the assistant (optional)

The GUI's assistant page drafts simulation files with an open-weights model
running on your machine. Any OpenAI-compatible server works: llama-server,
Ollama, LM Studio or vLLM. Point OpenTCAD at it with `OPENTCAD_LLM_URL` (the
default is `http://127.0.0.1:8080/v1`). The [assistant guide](assistant.md) has
the setup.

## Troubleshooting

- **`import devsim` fails.** There may be no DEVSIM wheel for your platform or
  Python version. `pip download devsim` shows what pip can find, and
  [devsim.org](https://devsim.org) lists the supported platforms.
- **ViennaPS.** OpenTCAD uses ViennaLS directly. Don't install ViennaPS into the
  same environment on macOS: versions 4.6.1 and 4.7.0 segfault on first use there,
  because both packages bundle their own VTK and OpenMP.
- **Slow tests.** The full suite takes about 8 minutes, most of it in the SKY130
  check. On a laptop in low-power mode it can take twice that. Use
  `-m "not slow"` while developing.
