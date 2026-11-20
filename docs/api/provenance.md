# Provenance

Where each value a run used came from: sources in data files and run records.

For an introduction, see the [user guide](../provenance.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.provenance`: `recording`, `Record`, `Value`, `Source`, `parse_sources`, `sources_for`, `note_value`, `note_model`, `note_file`, `note_input`, `active`, `summarize`, `format_table`, `code_version`, `display_path`.

## recording

```python
opentcad.provenance.recording(record: Optional[Record] = None) -> Iterator[Record]
```

Record what the code inside the block reads. Yields the ``Record``.

Recordings nest: the inner one collects on its own and the outer one
resumes afterwards.

## Record

```python
class opentcad.provenance.Record(
    values: dict[tuple[str, str], Value] = dict(),
    models: dict[str, dict] = dict(),
    files: dict[str, dict] = dict(),
    inputs: list[dict] = list(),
) -> None
```

Everything one run used and where it came from.

Filled by the code that reads data, while ``recording()`` is active.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L211)

### Record.add_value

```python
Record.add_value(
    group: str,
    name: str,
    value: Any,
    sources: Iterable[Source] = (),
    *,
    file=None,
    note: Optional[str] = None,
) -> None
```

Note that the run used ``value``. Reading the same value again
is a no-op; a different value under the same name replaces it and
says so in the note.

### Record.add_model

```python
Record.add_model(category: str, spec: Any, sources: Iterable[Source] = ()) -> None
```

Note the model used for ``category`` (``mobility``, ``bgn``…).

### Record.add_file

```python
Record.add_file(path, kind: str) -> None
```

Note a data file the run read, with its SHA-256.

### Record.add_input

```python
Record.add_input(what: str, **info) -> None
```

Note an input (the simulation file) and how to identify it.

### Record.merge

```python
Record.merge(other: Record) -> None
```

Add ``other``'s entries (a process record into a device one).

### Record.without_source

```python
Record.without_source() -> list[Value]
```

Values whose file or code gives no source.

### Record.to_dict

```python
Record.to_dict() -> dict
```

JSON-ready form: sources are numbered ``S1``, ``S2``… in the
order first cited, and values and models refer to them.

### Record.summary

```python
Record.summary() -> str
```

One line: how many values, sources and gaps.

## Value

```python
class opentcad.provenance.Value(
    group: str,
    name: str,
    value: Any,
    sources: tuple[Source, ...] = (),
    file: Optional[str] = None,
    note: Optional[str] = None,
) -> None
```

One value a run used.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L200)

## Source

```python
class opentcad.provenance.Source(
    cite: str,
    kind: str = 'literature',
    doi: Optional[str] = None,
    url: Optional[str] = None,
    note: Optional[str] = None,
) -> None
```

One source a value can cite.

**Attributes**

- `cite`: The reference as people read it (authors, journal, volume, page, year), or a description for non-literature kinds.
- `kind`: One of ``KINDS``.
- `doi`: DOI without the ``https://doi.org/`` prefix.
- `url`: A link when there is no DOI.
- `note`: Where in the source (table, equation) or a caveat.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L64)

### Source.from_dict

```python
classmethod Source.from_dict(d: Mapping, where: str = '') -> Source
```

A source from its file form. Unknown keys are an error.

### Source.to_dict

```python
Source.to_dict() -> dict
```

The file/JSON form, without empty fields.

### Source.link

```python
property Source.link: Optional[str]
```

A URL for the source: the DOI resolver, else ``url``.

## parse_sources

```python
opentcad.provenance.parse_sources(
    raw: Mapping,
    where: str = '',
    *,
    error=ValueError,
) -> dict[str, tuple[Source, ...]]
```

Read a data file's ``sources`` and ``cite`` sections.

**Parameters**

- `raw`: The parsed file.
- `where`: The file, for error messages.
- `error`: Exception class to raise (the material loader passes its own).

**Returns**

``{dotted path: sources}`` for every ``cite`` entry.

**Raises**

- `error`: a malformed source, a ``cite`` entry naming a key that isn't in ``sources``, or a path that isn't in the file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L130)

## sources_for

```python
opentcad.provenance.sources_for(
    cited: Mapping[str, tuple[Source, ...]],
    path: str,
) -> tuple[Source, ...]
```

The sources for ``path``: its own ``cite`` entry, else the nearest
enclosing block's, else none.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L176)

## note_value

```python
opentcad.provenance.note_value(
    group: str,
    name: str,
    value: Any,
    sources: Iterable[Source] = (),
    *,
    file=None,
    note: Optional[str] = None,
) -> None
```

``Record.add_value`` on the active record; a no-op without one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L420)

## note_model

```python
opentcad.provenance.note_model(
    category: str,
    spec: Any,
    sources: Iterable[Source] = (),
) -> None
```

``Record.add_model`` on the active record; a no-op without one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L428)

## note_file

```python
opentcad.provenance.note_file(path, kind: str) -> None
```

``Record.add_file`` on the active record; a no-op without one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L435)

## note_input

```python
opentcad.provenance.note_input(what: str, **info) -> None
```

``Record.add_input`` on the active record; a no-op without one.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L442)

## active

```python
opentcad.provenance.active() -> Optional[Record]
```

The record being filled, or None outside ``recording()``.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L415)

## summarize

```python
opentcad.provenance.summarize(prov: Mapping) -> str
```

One line for a provenance dict (``Record.to_dict()`` form).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L317)

## format_table

```python
opentcad.provenance.format_table(prov: Mapping, *, only_missing: bool = False) -> str
```

A plain-text listing of a provenance dict, for the terminal.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L325)

## code_version

```python
opentcad.provenance.code_version() -> dict
```

OpenTCAD's version, the git commit of the checkout (if it is one)
and whether it has uncommitted changes, plus Python and package
versions.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L498)

## display_path

```python
opentcad.provenance.display_path(path) -> str
```

``path`` relative to the OpenTCAD checkout (or install) or to the
working directory when it is inside one; otherwise as given.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/provenance.py#L455)
