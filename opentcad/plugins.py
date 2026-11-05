"""
opentcad.plugins — extension points for code and data outside the core.

Four things can be added without editing OpenTCAD itself:

* **Process steps** — ``register_step(StepClass, stage=..., apply=...)``.
  ``stage="topography"`` handlers run as ``apply(state, step)`` on the
  level-set ``TopographyState``; ``stage="doping"`` handlers run as
  ``apply(meshfield, step)`` on the meshed device and may return a result
  object. Add instances with ``Recipe.add(step)``.
* **Device analyses** — ``register_analysis("name", fn)``; run with
  ``DeviceSolver.run("name", **kwargs)``, which calls ``fn(solver, **kwargs)``.
* **Physics models** — ``register_model("mobility", "name", cls)`` (also
  ``recombination``, ``bgn``, ``statistics``) so simulation files can name
  them.
* **Data folders** — ``register_data_dir("materials", path)`` adds material
  YAMLs; ``register_data_dir("dopants", path)`` adds implant
  (``<Sym>_in_Si.yaml``) and diffusion (``<Sym>_diffusion.yaml``) tables.
  A name that already exists elsewhere is an error, never a silent override.
* **Packages** — a distribution can declare an entry point in the
  ``opentcad.plugins`` group. Its target is called once, with no
  arguments, the first time any registry is consulted; it should call the
  ``register_*`` functions above. Set ``OPENTCAD_DISABLE_PLUGINS=1`` to
  skip entry-point discovery. A plugin that fails to load produces a
  warning, not a crash.

Built-in steps and analyses go through the same registries.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Callable, Optional

ENTRY_POINT_GROUP = "opentcad.plugins"
DISABLE_ENV_VAR = "OPENTCAD_DISABLE_PLUGINS"
STAGES = ("topography", "doping")
DATA_KINDS = ("materials", "dopants")
MODEL_CATEGORIES = ("mobility", "recombination", "bgn", "statistics")

_BUILTIN_DATA_DIRS = {
    "materials": Path(__file__).parent / "materials" / "params",
    "dopants": Path(__file__).parent / "process" / "doping" / "data",
}


@dataclass(frozen=True)
class StepHandler:
    """How one recipe-step class is executed and described."""
    step_type: type
    stage: str
    apply: Callable
    describe: Optional[Callable] = None
    source: str = "opentcad"
    name: str = ""              # the step's name in simulation files


_steps: dict[type, StepHandler] = {}
_analyses: dict[str, tuple[Callable, str]] = {}
_models: dict[str, dict[str, tuple[type, str]]] = {c: {} for c in MODEL_CATEGORIES}
_data_dirs: dict[str, list[tuple[Path, str]]] = {k: [] for k in DATA_KINDS}
_plugin_status: dict[str, str] = {}
_builtins_loaded = False
_entry_points_loaded = False
_current_source = "user"


# =============================================================================
# Loading
# =============================================================================
def _ensure_builtins() -> None:
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        _register_builtins()


def _ensure_loaded() -> None:
    global _entry_points_loaded
    _ensure_builtins()
    if not _entry_points_loaded:
        _entry_points_loaded = True
        if os.environ.get(DISABLE_ENV_VAR, "").strip() not in ("", "0"):
            return
        load_entry_points()


def _register_builtins() -> None:
    global _current_source
    _current_source = "opentcad"
    try:
        from opentcad.device import builtin_analyses, builtin_models
        from opentcad.process import builtin_steps
        builtin_steps.register()
        builtin_analyses.register()
        builtin_models.register()
    finally:
        _current_source = "user"


def _iter_entry_points():
    return metadata.entry_points(group=ENTRY_POINT_GROUP)


def load_entry_points() -> dict[str, str]:
    """Import every ``opentcad.plugins`` entry point not yet loaded and
    call its target. Returns ``{entry point name: "loaded" | error}``."""
    global _current_source
    for ep in _iter_entry_points():
        if ep.name in _plugin_status:
            continue
        _current_source = f"plugin:{ep.name}"
        try:
            target = ep.load()
            if callable(target):
                target()
            _plugin_status[ep.name] = "loaded"
        except Exception as exc:   # a broken plugin must not break the core
            _plugin_status[ep.name] = f"{type(exc).__name__}: {exc}"
            warnings.warn(f"OpenTCAD plugin {ep.name!r} failed to load: "
                          f"{type(exc).__name__}: {exc}", RuntimeWarning,
                          stacklevel=2)
        finally:
            _current_source = "user"
    return dict(_plugin_status)


def plugin_status() -> dict[str, str]:
    """Entry-point plugins seen so far and whether each loaded."""
    _ensure_loaded()
    return dict(_plugin_status)


# =============================================================================
# Process steps
# =============================================================================
def _snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and (not name[i - 1].isupper()
                                   or (i + 1 < len(name) and name[i + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def register_step(step_type: type, *, stage: str, apply: Callable,
                  describe: Optional[Callable] = None,
                  name: Optional[str] = None,
                  replace: bool = False) -> None:
    """Register how a recipe-step class runs.

    Args:
        step_type: the step's class (instances go into ``Recipe.add``).
        stage: ``"topography"`` (``apply(state, step)``, before meshing)
            or ``"doping"`` (``apply(meshfield, step)``, after meshing).
        apply: the handler.
        describe: optional ``describe(step) -> str`` for ``Recipe.summary``.
        name: the step's name in simulation files; defaults to the class
            name in snake_case (``UniformAcceptor`` → ``uniform_acceptor``).
            Files can only carry dataclass steps.
        replace: allow re-registering a class that already has a handler.
    """
    _ensure_builtins()      # so a clash with a built-in is caught here
    if not isinstance(step_type, type):
        raise TypeError(f"step_type must be a class, got {step_type!r}")
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}, got {stage!r}")
    if not callable(apply):
        raise TypeError("apply must be callable")
    if step_type in _steps and not replace:
        raise ValueError(
            f"step {step_type.__name__} is already registered "
            f"(by {_steps[step_type].source}); pass replace=True to override")
    step_name = name or _snake(step_type.__name__)
    for other in _steps.values():
        if other.name == step_name and other.step_type is not step_type:
            raise ValueError(f"step name {step_name!r} is already used by "
                             f"{other.step_type.__name__}")
    _steps[step_type] = StepHandler(step_type, stage, apply, describe,
                                    _current_source, step_name)


def step_class(name: str) -> type:
    """The step class registered under ``name`` (as used in files)."""
    _ensure_loaded()
    for h in _steps.values():
        if h.name == name:
            return h.step_type
    raise KeyError(f"Unknown step {name!r}; available: "
                   f"{sorted(h.name for h in _steps.values())}")


def step_handler(step) -> StepHandler:
    """The handler for a step instance (or class). Raises TypeError for
    an unregistered step."""
    _ensure_loaded()
    cls = step if isinstance(step, type) else type(step)
    try:
        return _steps[cls]
    except KeyError:
        raise TypeError(
            f"Unknown recipe step type {cls.__name__}: register it with "
            f"opentcad.plugins.register_step") from None


def registered_steps() -> dict[str, StepHandler]:
    _ensure_loaded()
    return {cls.__name__: h for cls, h in _steps.items()}


# =============================================================================
# Device analyses
# =============================================================================
def register_analysis(name: str, fn: Callable, *, replace: bool = False) -> None:
    """Register ``fn(solver, **kwargs)`` under ``name`` for
    ``DeviceSolver.run(name, **kwargs)``."""
    _ensure_builtins()
    if not isinstance(name, str) or not name:
        raise ValueError("analysis name must be a non-empty string")
    if not callable(fn):
        raise TypeError("analysis must be callable")
    if name in _analyses and not replace:
        raise ValueError(
            f"analysis {name!r} is already registered (by "
            f"{_analyses[name][1]}); pass replace=True to override")
    _analyses[name] = (fn, _current_source)


def get_analysis(name: str) -> Callable:
    _ensure_loaded()
    try:
        return _analyses[name][0]
    except KeyError:
        raise KeyError(f"Unknown analysis {name!r}; available: "
                       f"{sorted(_analyses)}") from None


def available_analyses() -> list[str]:
    _ensure_loaded()
    return sorted(_analyses)


# =============================================================================
# Physics models (named, for simulation files)
# =============================================================================
def register_model(category: str, name: str, cls: type, *,
                   replace: bool = False) -> None:
    """Register a physics-model class under ``name`` so simulation files
    can refer to it. ``category`` is one of MODEL_CATEGORIES. The class's
    constructor arguments become the model's options in the file; each
    must be stored on the instance under the same name."""
    _ensure_builtins()
    if category not in MODEL_CATEGORIES:
        raise ValueError(f"category must be one of {MODEL_CATEGORIES}, "
                         f"got {category!r}")
    if not isinstance(cls, type):
        raise TypeError(f"model must be a class, got {cls!r}")
    if not isinstance(name, str) or not name:
        raise ValueError("model name must be a non-empty string")
    table = _models[category]
    if name in table and not replace:
        raise ValueError(f"{category} model {name!r} is already registered "
                         f"(by {table[name][1]}); pass replace=True")
    table[name] = (cls, _current_source)


def get_model(category: str, name: str) -> type:
    _ensure_loaded()
    if category not in MODEL_CATEGORIES:
        raise ValueError(f"category must be one of {MODEL_CATEGORIES}, "
                         f"got {category!r}")
    try:
        return _models[category][name][0]
    except KeyError:
        raise KeyError(f"Unknown {category} model {name!r}; available: "
                       f"{sorted(_models[category])}") from None


def model_name(category: str, model) -> str:
    """The registered name of a model instance's class (exact class match)."""
    _ensure_loaded()
    for name, (cls, _) in _models[category].items():
        if type(model) is cls:
            return name
    raise KeyError(f"{type(model).__name__} is not a registered "
                   f"{category} model")


def available_models(category: str) -> list[str]:
    _ensure_loaded()
    return sorted(_models[category])


# =============================================================================
# Data folders
# =============================================================================
def register_data_dir(kind: str, path) -> None:
    """Add a folder searched after the built-in one for ``kind``
    (``"materials"`` or ``"dopants"``)."""
    if kind not in DATA_KINDS:
        raise ValueError(f"kind must be one of {DATA_KINDS}, got {kind!r}")
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"data folder does not exist: {p}")
    if p == _BUILTIN_DATA_DIRS[kind].resolve() or any(p == q for q, _ in _data_dirs[kind]):
        return
    _data_dirs[kind].append((p, _current_source))


def data_dirs(kind: str) -> tuple[Path, ...]:
    """Folders searched for ``kind``: the built-in one first, then the
    registered ones in registration order."""
    if kind not in DATA_KINDS:
        raise ValueError(f"kind must be one of {DATA_KINDS}, got {kind!r}")
    _ensure_loaded()
    return (_BUILTIN_DATA_DIRS[kind],) + tuple(p for p, _ in _data_dirs[kind])


def find_data_file(kind: str, relative: str) -> Optional[Path]:
    """The one file called ``relative`` across the ``kind`` folders, or
    None. Two folders providing the same file is an error."""
    hits = [d / relative for d in data_dirs(kind) if (d / relative).is_file()]
    if len(hits) > 1:
        raise ValueError(f"{relative} is provided by more than one data "
                         f"folder: {[str(h) for h in hits]}")
    return hits[0] if hits else None


# =============================================================================
# Testing support
# =============================================================================
def _reset_for_tests() -> None:
    """Forget plugin-registered entries and reload built-ins. Tests only."""
    global _builtins_loaded, _entry_points_loaded
    _steps.clear()
    _analyses.clear()
    for table in _models.values():
        table.clear()
    for v in _data_dirs.values():
        v.clear()
    _plugin_status.clear()
    _builtins_loaded = False
    _entry_points_loaded = False
