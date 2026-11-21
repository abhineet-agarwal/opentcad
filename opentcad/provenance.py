"""
opentcad.provenance — where each number a run used came from.

While a run is recorded, every value it reads from a data file or from the
code is noted with the source that file or code gives for it. That covers
material parameters, implant moments, diffusivities, oxidation rates,
model constants and physical constants. The record also lists the physics
models used (with their references), the data files read (with SHA-256),
the simulation file's hash, and the code and package versions.
``run_deck`` records every run. The record is ``DeckResult.provenance`` and
the ``provenance`` block of the results file ``opentcad run`` writes.

Nothing is inferred. A value whose file or code gives no source is listed
as having none, so the gaps show.

Data files give sources in two top-level sections::

    sources:
      green1990:
        cite: M. A. Green, J. Appl. Phys. 67, 2944 (1990)
        doi: 10.1063/1.345414
    cite:
      bandgap.Eg_eV_300K: green1990     # one value
      mobility_klaassen: klaassen1992   # every value in the block

The most specific ``cite`` entry wins, and a value may cite a list of keys.
``kind`` defaults to ``literature``; the other kinds are in ``KINDS``.

Usage::

    from opentcad.provenance import recording
    with recording() as rec:
        ...                      # build and solve
    print(rec.summary())
    rec.to_dict()                # JSON-ready
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

#: What a source can be.
KINDS = {
    "literature": "published source",
    "fit": "fitted to data",
    "override": "set in code, replacing the file's value",
    "placeholder": "not used by the solver; kept for the file format",
    "default": "OpenTCAD's own value, not from a publication",
    "constant": "physical constant",
    "input": "your simulation file",
}

SCHEMA = 1


@dataclass(frozen=True)
class Source:
    """One source a value can cite.

    Attributes:
        cite: The reference as people read it (authors, journal, volume,
            page, year), or a description for non-literature kinds.
        kind: One of ``KINDS``.
        doi: DOI without the ``https://doi.org/`` prefix.
        url: A link when there is no DOI.
        note: Where in the source (table, equation) or a caveat.
    """
    cite: str
    kind: str = "literature"
    doi: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.cite, str) or not self.cite.strip():
            raise ValueError("a source needs a non-empty 'cite'")
        if self.kind not in KINDS:
            raise ValueError(f"source kind {self.kind!r} is not one of {sorted(KINDS)}")

    @classmethod
    def from_dict(cls, d: Mapping, where: str = "") -> "Source":
        """A source from its file form. Unknown keys are an error."""
        at = f"{where}: " if where else ""
        if not isinstance(d, Mapping):
            raise ValueError(f"{at}a source must be a mapping with at least 'cite'")
        extra = set(d) - {"cite", "kind", "doi", "url", "note"}
        if extra:
            raise ValueError(f"{at}unknown source key(s) {sorted(extra)}; "
                             f"allowed: cite, kind, doi, url, note")
        try:
            return cls(**{k: (str(v) if v is not None else None) for k, v in d.items()})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{at}{exc}") from None

    def to_dict(self) -> dict:
        """The file/JSON form, without empty fields."""
        d = {"cite": self.cite, "kind": self.kind, "doi": self.doi,
             "url": self.url, "note": self.note}
        return {k: v for k, v in d.items() if v is not None}

    @property
    def link(self) -> Optional[str]:
        """A URL for the source: the DOI resolver, else ``url``."""
        return f"https://doi.org/{self.doi}" if self.doi else self.url

    def _key(self) -> tuple:
        # One entry per reference in a record, even if two files cite it
        # in different words; the note is part of the identity.
        return (self.doi or self.cite, self.kind, self.note)


#: The physical constants the solver and the process models use.
CODATA_2018 = Source(
    "E. Tiesinga, P. J. Mohr, D. B. Newell, B. N. Taylor, CODATA recommended "
    "values of the fundamental physical constants: 2018, Rev. Mod. Phys. 93, "
    "025010 (2021)", kind="constant", doi="10.1103/RevModPhys.93.025010")


# =============================================================================
# Sources in data files
# =============================================================================
def parse_sources(raw: Mapping, where: str = "", *, error=ValueError
                  ) -> dict[str, tuple[Source, ...]]:
    """Read a data file's ``sources`` and ``cite`` sections.

    Args:
        raw: The parsed file.
        where: The file, for error messages.
        error: Exception class to raise (the material loader passes its own).

    Returns:
        ``{dotted path: sources}`` for every ``cite`` entry.

    Raises:
        error: a malformed source, a ``cite`` entry naming a key that isn't
            in ``sources``, or a path that isn't in the file.
    """
    at = f"{where}: " if where else ""
    sources_raw = raw.get("sources") or {}
    cite_raw = raw.get("cite") or {}
    if not isinstance(sources_raw, Mapping):
        raise error(f"{at}'sources' must map a key to a source")
    if not isinstance(cite_raw, Mapping):
        raise error(f"{at}'cite' must map a value's path to a source key")
    sources: dict[str, Source] = {}
    for key, d in sources_raw.items():
        try:
            sources[str(key)] = Source.from_dict(d, f"sources.{key}")
        except ValueError as exc:
            raise error(f"{at}{exc}") from None
    out: dict[str, tuple[Source, ...]] = {}
    for path, keys in cite_raw.items():
        path = str(path)
        if path.split(".")[0] in ("sources", "cite") or not _has_path(raw, path):
            raise error(f"{at}cite names {path!r}, which isn't a value or block "
                        f"in the file")
        keys = [keys] if isinstance(keys, str) else keys
        if not isinstance(keys, list) or not keys:
            raise error(f"{at}cite.{path} must be a source key or a list of them")
        missing = [k for k in keys if k not in sources]
        if missing:
            raise error(f"{at}cite.{path} names {missing}, not in 'sources' "
                        f"(which has {sorted(sources)})")
        out[path] = tuple(sources[k] for k in keys)
    return out


def sources_for(cited: Mapping[str, tuple[Source, ...]], path: str
                ) -> tuple[Source, ...]:
    """The sources for ``path``: its own ``cite`` entry, else the nearest
    enclosing block's, else none."""
    parts = path.split(".")
    for n in range(len(parts), 0, -1):
        hit = cited.get(".".join(parts[:n]))
        if hit is not None:
            return hit
    return ()


def _has_path(raw: Mapping, dotted: str) -> bool:
    node: Any = raw
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False
        node = node[part]
    return True


# =============================================================================
# The record
# =============================================================================
@dataclass
class Value:
    """One value a run used."""
    group: str
    name: str
    value: Any
    sources: tuple[Source, ...] = ()
    file: Optional[str] = None
    note: Optional[str] = None


@dataclass
class Record:
    """Everything one run used and where it came from.

    Filled by the code that reads data, while ``recording()`` is active.
    """
    values: dict[tuple[str, str], Value] = field(default_factory=dict)
    models: dict[str, dict] = field(default_factory=dict)
    files: dict[str, dict] = field(default_factory=dict)
    inputs: list[dict] = field(default_factory=list)

    def add_value(self, group: str, name: str, value: Any,
                  sources: Iterable[Source] = (), *, file=None,
                  note: Optional[str] = None) -> None:
        """Note that the run used ``value``. Reading the same value again
        is a no-op; a different value under the same name replaces it and
        says so in the note."""
        value = _plain(value)
        key = (group, name)
        old = self.values.get(key)
        if old is not None and old.value == value:
            return
        if old is not None:
            note = "; ".join(filter(None, [note, "changed during the run; "
                                                 "the last value is shown"]))
        path = display_path(file) if file else None
        self.values[key] = Value(group, name, value, tuple(sources), path, note)
        if file:
            self.add_file(file, group)

    def add_model(self, category: str, spec: Any,
                  sources: Iterable[Source] = ()) -> None:
        """Note the model used for ``category`` (``mobility``, ``bgn``…)."""
        self.models[category] = {"model": _plain(spec), "sources": tuple(sources)}

    def add_file(self, path, kind: str) -> None:
        """Note a data file the run read, with its SHA-256."""
        shown = display_path(path)
        if shown not in self.files:
            self.files[shown] = {"kind": kind, "sha256": file_sha256(path)}

    def add_input(self, what: str, **info) -> None:
        """Note an input (the simulation file) and how to identify it."""
        entry = {"what": what, **{k: _plain(v) for k, v in info.items()}}
        if entry not in self.inputs:
            self.inputs.append(entry)

    def merge(self, other: "Record") -> None:
        """Add ``other``'s entries (a process record into a device one)."""
        for v in other.values.values():
            self.values.setdefault((v.group, v.name), v)
        for k, m in other.models.items():
            self.models.setdefault(k, m)
        for k, f in other.files.items():
            self.files.setdefault(k, f)
        for i in other.inputs:
            if i not in self.inputs:
                self.inputs.append(i)

    def without_source(self) -> list[Value]:
        """Values whose file or code gives no source."""
        return [v for v in self.values.values() if not v.sources]

    def to_dict(self) -> dict:
        """JSON-ready form: sources are numbered ``S1``, ``S2``… in the
        order first cited, and values and models refer to them."""
        ids: dict[tuple, str] = {}
        table: dict[str, dict] = {}

        def ref(sources):
            out = []
            for s in sources:
                k = s._key()
                if k not in ids:
                    ids[k] = f"S{len(ids) + 1}"
                    table[ids[k]] = s.to_dict()
                out.append(ids[k])
            return out

        models = [{"category": c, "model": m["model"], "sources": ref(m["sources"])}
                  for c, m in self.models.items()]
        values = []
        for v in sorted(self.values.values(), key=lambda v: (v.group, v.name)):
            d = {"group": v.group, "name": v.name, "value": v.value,
                 "sources": ref(v.sources)}
            if v.file:
                d["file"] = v.file
            if v.note:
                d["note"] = v.note
            values.append(d)
        return {
            "schema": SCHEMA,
            "code": code_version(),
            "inputs": list(self.inputs),
            "files": [{"path": p, **f} for p, f in sorted(self.files.items())],
            "sources": table,
            "models": models,
            "values": values,
            "without_source": sum(1 for v in values if not v["sources"]),
            "opentcad_defaults": sum(
                1 for v in values if v["sources"]
                and all(table[s].get("kind") == "default" for s in v["sources"])),
        }

    def summary(self) -> str:
        """One line: how many values, sources and gaps."""
        return summarize(self.to_dict())


def summarize(prov: Mapping) -> str:
    """One line for a provenance dict (``Record.to_dict()`` form)."""
    n, gaps = len(prov.get("values", [])), prov.get("without_source", 0)
    own = prov.get("opentcad_defaults", 0)
    line = (f"{n} value(s) from data files and code, citing "
            f"{len(prov.get('sources', {}))} source(s)")
    if gaps:
        line += f"; {gaps} have no recorded source"
    if own:
        line += f"; {own} are OpenTCAD's own values, not from a publication"
    return line


def unpublished(value: Mapping, sources: Mapping) -> bool:
    """True if a value (``to_dict`` form) has no source, or only OpenTCAD's own."""
    return all(sources.get(s, {}).get("kind") == "default" for s in value["sources"])


def format_table(prov: Mapping, *, only_missing: bool = False) -> str:
    """A plain-text listing of a provenance dict, for the terminal.
    ``only_missing`` lists only values with no published source."""
    srcs = prov.get("sources", {})
    lines = []
    code = prov.get("code", {})
    lines.append(f"OpenTCAD {code.get('opentcad', '?')}"
                 + (f", commit {code['git_commit'][:12]}" if code.get("git_commit") else "")
                 + (" (with uncommitted changes)" if code.get("git_modified") else ""))
    for i in prov.get("inputs", []):
        lines.append("input: " + ", ".join(f"{k}={v}" for k, v in i.items()))
    if prov.get("models") and not only_missing:
        lines.append("")
        lines.append("Models")
        for m in prov["models"]:
            lines.append(f"  {m['category']}: {json.dumps(m['model'])}"
                         + (f"  [{', '.join(m['sources'])}]" if m["sources"] else ""))
    lines.append("")
    lines.append("Values")
    files: dict[str, list[str]] = {}
    for v in prov.get("values", []):
        if v.get("file") and v["file"] not in files.setdefault(v["group"], []):
            files[v["group"]].append(v["file"])
    group = None
    for v in prov.get("values", []):
        if only_missing and not unpublished(v, srcs):
            continue
        if v["group"] != group:
            group = v["group"]
            shown = files.get(group)
            lines.append(f"  {group}" + (f"  ({', '.join(shown)})" if shown else ""))
        tag = ", ".join(v["sources"]) if v["sources"] else "NO SOURCE"
        lines.append(f"    {v['name']} = {_short(v['value'])}  [{tag}]"
                     + (f"  — {v['note']}" if v.get("note") else ""))
    if srcs:
        lines.append("")
        lines.append("Sources")
        for sid, s in srcs.items():
            link = f"  https://doi.org/{s['doi']}" if s.get("doi") else (
                f"  {s['url']}" if s.get("url") else "")
            kind = "" if s.get("kind", "literature") == "literature" else f" ({s['kind']})"
            lines.append(f"  {sid}{kind}: {s['cite']}{link}"
                         + (f" — {s['note']}" if s.get("note") else ""))
    lines.append("")
    lines.append(summarize(prov))
    return "\n".join(lines)


def _short(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_short(v)}" for k, v in value.items()) + "}"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _plain(v):
    """JSON-friendly copy (numpy scalars → float, tuples → lists)."""
    if isinstance(v, Mapping):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "item") and callable(v.item):
        try:
            return v.item()
        except (TypeError, ValueError):
            pass
    return v


# =============================================================================
# Recording
# =============================================================================
_current: ContextVar[Optional[Record]] = ContextVar("opentcad_provenance", default=None)


@contextmanager
def recording(record: Optional[Record] = None) -> Iterator[Record]:
    """Record what the code inside the block reads. Yields the ``Record``.

    Recordings nest: the inner one collects on its own and the outer one
    resumes afterwards.
    """
    rec = record if record is not None else Record()
    token = _current.set(rec)
    try:
        yield rec
    finally:
        _current.reset(token)


def active() -> Optional[Record]:
    """The record being filled, or None outside ``recording()``."""
    return _current.get()


def note_value(group: str, name: str, value: Any, sources: Iterable[Source] = (),
               *, file=None, note: Optional[str] = None) -> None:
    """``Record.add_value`` on the active record; a no-op without one."""
    rec = _current.get()
    if rec is not None:
        rec.add_value(group, name, value, sources, file=file, note=note)


def note_model(category: str, spec: Any, sources: Iterable[Source] = ()) -> None:
    """``Record.add_model`` on the active record; a no-op without one."""
    rec = _current.get()
    if rec is not None:
        rec.add_model(category, spec, sources)


def note_file(path, kind: str) -> None:
    """``Record.add_file`` on the active record; a no-op without one."""
    rec = _current.get()
    if rec is not None:
        rec.add_file(path, kind)


def note_input(what: str, **info) -> None:
    """``Record.add_input`` on the active record; a no-op without one."""
    rec = _current.get()
    if rec is not None:
        rec.add_input(what, **info)


# =============================================================================
# Files and versions
# =============================================================================
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def display_path(path) -> str:
    """``path`` relative to the OpenTCAD checkout (or install) or to the
    working directory when it is inside one; otherwise as given."""
    p = Path(path).resolve()
    for base in (_PACKAGE_ROOT, Path.cwd().resolve()):
        try:
            return p.relative_to(base).as_posix()
        except ValueError:
            continue
    return str(p)


def file_sha256(path) -> Optional[str]:
    """SHA-256 of a file's bytes, or None if it can't be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def text_sha256(text: str) -> str:
    """SHA-256 of a string (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_PACKAGES = ("devsim", "ViennaLS", "gmsh", "numpy", "scipy", "pyvista")


@lru_cache(maxsize=1)
def _static_versions() -> dict:
    from importlib import metadata

    from opentcad import __version__
    pkgs = {}
    for name in _PACKAGES:
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return {"opentcad": __version__, "python": platform.python_version(),
            "packages": pkgs}


def code_version() -> dict:
    """OpenTCAD's version, the git commit of the checkout (if it is one)
    and whether it has uncommitted changes, plus Python and package
    versions."""
    out = dict(_static_versions())
    commit, modified = _git_state()
    if commit:
        out["git_commit"] = commit
        out["git_modified"] = modified
    return out


def _git_state() -> tuple[Optional[str], bool]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(_PACKAGE_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5)
        if commit.returncode != 0:
            return None, False
        status = subprocess.run(
            ["git", "-C", str(_PACKAGE_ROOT), "status", "--porcelain",
             "--untracked-files=no", "--", "opentcad"],
            capture_output=True, text=True, timeout=5)
        return commit.stdout.strip(), bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None, False
