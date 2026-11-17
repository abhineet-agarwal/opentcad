# Simulation files and sweeps

Loading, checking, running and saving simulation files; parameter sweeps.

For an introduction, see the [user guide](../simulation_files.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.io`: `load_deck`, `run_deck`, `save_deck`, `dumps_deck`, `deck_from_dict`, `Deck`, `DeckResult`, `DeckError`, `load_sweep`, `run_sweep`, `Sweep`, `SweepResult`.

## load_deck

```python
opentcad.io.load_deck(source) -> Deck
```

Read and check a simulation file (``.yaml``/``.yml``/``.json`` path),
or a dict already parsed. Raises DeckError listing every problem.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L827)

## run_deck

```python
opentcad.io.run_deck(deck: Deck, *, log=None) -> DeckResult
```

Run a deck: build the structure, run the recipe (topography, mesh,
doping), then — if the deck has a ``device`` section — create one
DeviceSolver and run the analyses on it in order.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L911)

## save_deck

```python
opentcad.io.save_deck(deck: Deck, path) -> Path
```

Write ``deck`` as YAML (or JSON for a ``.json`` path).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L865)

## dumps_deck

```python
opentcad.io.dumps_deck(deck: Deck) -> str
```

The deck as YAML text.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L859)

## deck_from_dict

```python
opentcad.io.deck_from_dict(data: dict) -> Deck
```

Check and build a Deck from parsed YAML/JSON. Raises DeckError
listing every problem found.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L722)

## Deck

```python
class opentcad.io.Deck(
    name: str,
    structure: Structure,
    recipe: Recipe = Recipe(),
    description: str = '',
    mesh_size_um: float = 0.03,
    grid_delta_um: float = 0.005,
    device: Optional[DeviceSettings] = None,
    analyses: list[AnalysisSpec] = list(),
) -> None
```

A checked simulation file. Edit the objects freely; ``to_dict`` and
``save_deck`` write the current state back out.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L690)

### Deck.to_dict

```python
Deck.to_dict() -> dict
```

The simulation file as plain data (what ``save_deck`` writes).
``deck_from_dict`` turns it back into an equal Deck.

## DeckResult

```python
class opentcad.io.DeckResult(
    meshfield: Any,
    recipe_result: Any,
    analyses: dict[str, Any] = dict(),
) -> None
```

What ``run_deck`` produced.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L878)

### DeckResult.analyses_to_dict

```python
DeckResult.analyses_to_dict() -> dict
```

Analysis results as JSON-friendly values (complex → [re, im]).

## DeckError

```python
class opentcad.io.DeckError(problems: list[tuple[str, str]])
```

Every problem found in a simulation file, each with its location
(e.g. ``recipe[1].energy_keV``).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L78)

## load_sweep

```python
opentcad.io.load_sweep(source, *, base_dir=None) -> Sweep
```

Read and check a sweep file (path) or an already-parsed dict.
Every point's simulation file is checked; DeckError lists all problems.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/sweep.py#L152)

## run_sweep

```python
opentcad.io.run_sweep(sweep: Sweep, outdir, *, jobs: int = 1, log=None) -> SweepResult
```

Run every point and write the output folder. Returns the rows.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/sweep.py#L316)

## Sweep

```python
class opentcad.io.Sweep(
    name: str,
    base: dict,
    vary: list[tuple[str, list]],
    mode: str = 'product',
    metrics: list[MetricSpec] = list(),
    description: str = '',
    points: list[dict] = list(),
) -> None
```

A checked sweep: the base simulation file (as a dict) and every point.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/sweep.py#L126)

### Sweep.point_deck

```python
Sweep.point_deck(values: dict) -> dict
```

The simulation-file dict for one point.

## SweepResult

```python
class opentcad.io.SweepResult(outdir: Path, rows: list[dict]) -> None
```

A finished sweep: the output folder (``table.csv`` plus each point's
file and results) and one row per point.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/sweep.py#L304)

### SweepResult.table

```python
SweepResult.table() -> list[dict]
```

The rows of ``table.csv``: each point's varied values and metrics.

Import from `opentcad.io.deck`: `example_decks_dir`.

## example_decks_dir

```python
opentcad.io.deck.example_decks_dir() -> Path
```

The bundled example simulation files (also the assistant's
templates): inside the package when installed from a wheel,
``examples/decks`` in a source checkout.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/io/deck.py#L818)
