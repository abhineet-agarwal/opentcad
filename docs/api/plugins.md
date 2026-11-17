# Plugin registries

Registering and looking up process steps, analyses, models, metrics and data folders.

For an introduction, see the [user guide](../plugins.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.plugins`: `register_step`, `StepHandler`, `step_handler`, `step_class`, `registered_steps`, `register_analysis`, `get_analysis`, `available_analyses`, `register_model`, `get_model`, `model_name`, `available_models`, `MODEL_CATEGORIES`, `register_metric`, `get_metric`, `available_metrics`, `register_data_dir`, `data_dirs`, `find_data_file`, `load_entry_points`, `plugin_status`.

## register_step

```python
opentcad.plugins.register_step(
    step_type: type,
    *,
    stage: str,
    apply: Callable,
    describe: Optional[Callable] = None,
    name: Optional[str] = None,
    replace: bool = False,
) -> None
```

Register how a recipe-step class runs.

**Parameters**

- `step_type`: the step's class (instances go into ``Recipe.add``).
- `stage`: ``"topography"`` (``apply(state, step)``, before meshing) or ``"doping"`` (``apply(meshfield, step)``, after meshing).
- `apply`: the handler.
- `describe`: optional ``describe(step) -> str`` for ``Recipe.summary``.
- `name`: the step's name in simulation files; defaults to the class name in snake_case (``UniformAcceptor`` → ``uniform_acceptor``). Files can only carry dataclass steps.
- `replace`: allow re-registering a class that already has a handler.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L154)

## StepHandler

```python
class opentcad.plugins.StepHandler(
    step_type: type,
    stage: str,
    apply: Callable,
    describe: Optional[Callable] = None,
    source: str = 'opentcad',
    name: str = '',
) -> None
```

How one recipe-step class is executed and described.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L52)

## step_handler

```python
opentcad.plugins.step_handler(step) -> StepHandler
```

The handler for a step instance (or class). Raises TypeError for
an unregistered step.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L201)

## step_class

```python
opentcad.plugins.step_class(name: str) -> type
```

The step class registered under ``name`` (as used in files).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L191)

## registered_steps

```python
opentcad.plugins.registered_steps() -> dict[str, StepHandler]
```

Every registered process step: ``{class name: StepHandler}``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L214)

## register_analysis

```python
opentcad.plugins.register_analysis(
    name: str,
    fn: Callable,
    *,
    replace: bool = False,
) -> None
```

Register ``fn(solver, **kwargs)`` under ``name`` for
``DeviceSolver.run(name, **kwargs)``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L223)

## get_analysis

```python
opentcad.plugins.get_analysis(name: str) -> Callable
```

The function registered as analysis ``name``. Raises KeyError,
listing the available names, if there is none.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L238)

## available_analyses

```python
opentcad.plugins.available_analyses() -> list[str]
```

Names of all registered analyses, sorted.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L249)

## register_model

```python
opentcad.plugins.register_model(
    category: str,
    name: str,
    cls: type,
    *,
    replace: bool = False,
) -> None
```

Register a physics-model class under ``name`` so simulation files
can refer to it. ``category`` is one of MODEL_CATEGORIES. The class's
constructor arguments become the model's options in the file; each
must be stored on the instance under the same name.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L258)

## get_model

```python
opentcad.plugins.get_model(category: str, name: str) -> type
```

The model class registered as ``name`` in ``category`` (one of
``MODEL_CATEGORIES``). Raises ValueError for an unknown category and
KeyError, listing the available names, for an unknown model.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L279)

## model_name

```python
opentcad.plugins.model_name(category: str, model) -> str
```

The registered name of a model instance's class (exact class match).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L294)

## available_models

```python
opentcad.plugins.available_models(category: str) -> list[str]
```

Names of the models registered in ``category``, sorted.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L304)

## MODEL_CATEGORIES

```python
opentcad.plugins.MODEL_CATEGORIES = ('mobility', 'recombination', 'bgn', 'statistics')
```

## register_metric

```python
opentcad.plugins.register_metric(
    name: str,
    fn: Callable,
    *,
    replace: bool = False,
) -> None
```

Register ``fn(result, **options) -> float`` under ``name``. ``result``
is what the analysis returned (for ``iv``: ``(voltages, currents)``).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L313)

## get_metric

```python
opentcad.plugins.get_metric(name: str) -> Callable
```

The function registered as metric ``name``. Raises KeyError,
listing the available names, if there is none.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L327)

## available_metrics

```python
opentcad.plugins.available_metrics() -> list[str]
```

Names of all registered metrics, sorted.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L338)

## register_data_dir

```python
opentcad.plugins.register_data_dir(kind: str, path) -> None
```

Add a folder searched after the built-in one for ``kind``
(``"materials"`` or ``"dopants"``).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L347)

## data_dirs

```python
opentcad.plugins.data_dirs(kind: str) -> tuple[Path, ...]
```

Folders searched for ``kind``: the built-in one first, then the
registered ones in registration order.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L360)

## find_data_file

```python
opentcad.plugins.find_data_file(kind: str, relative: str) -> Optional[Path]
```

The one file called ``relative`` across the ``kind`` folders, or
None. Two folders providing the same file is an error.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L369)

## load_entry_points

```python
opentcad.plugins.load_entry_points() -> dict[str, str]
```

Import every ``opentcad.plugins`` entry point not yet loaded and
call its target. Returns ``{entry point name: "loaded" | error}``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L112)

## plugin_status

```python
opentcad.plugins.plugin_status() -> dict[str, str]
```

Entry-point plugins seen so far and whether each loaded.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/plugins.py#L135)
