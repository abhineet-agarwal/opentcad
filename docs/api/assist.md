# Assistant

Drafting simulation files and catalog records with a local open-weights model.

For an introduction, see the [user guide](../assistant.md). This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.assist`: `draft_deck`, `Draft`, `Flag`, `unstated_values`, `request_numbers`, `ChatClient`, `LLMError`, `draft_catalog`, `CatalogDraft`.

## draft_deck

```python
opentcad.assist.draft_deck(
    request: str,
    *,
    client,
    current: Optional[dict] = None,
    max_repairs: int = 2,
    constrained: bool = True,
) -> Draft
```

Turn ``request`` into a checked simulation file using ``client``
(anything with ``chat(messages, json_schema=...) -> str``). With
``current`` (a simulation-file dict) the request edits that file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/draft.py#L168)

## Draft

```python
class opentcad.assist.Draft(
    deck: Optional[Deck],
    data: Optional[dict],
    flags: list[Flag] = list(),
    questions: list[str] = list(),
    problems: list[tuple[str, str]] = list(),
    attempts: int = 0,
    transcript: list[dict] = list(),
) -> None
```

The outcome of ``draft_deck``.

``deck`` is the checked simulation file, or None if every attempt
failed; ``data`` is the file as the model last wrote it. ``flags`` lists
every value the request did not state; ``questions`` are the model's
questions for you; ``problems`` are the remaining check failures as
(path, message). ``attempts`` counts replies, ``transcript`` holds the
whole conversation.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/draft.py#L37)

### Draft.ok

```python
property Draft.ok: bool
```

True if the model produced a simulation file that passed the checks.

## Flag

```python
class opentcad.assist.Flag(
    path: str,
    value: Any,
    reason: str = '',
    declared: bool = False,
) -> None
```

A value in the file that the request didn't state.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/draft.py#L28)

## unstated_values

```python
opentcad.assist.unstated_values(
    request: str,
    deck: dict,
    previous: Optional[dict] = None,
) -> list[tuple[str, Any]]
```

Values in ``deck`` the user didn't give: numbers that appear neither
in ``request`` (after unit conversion) nor, unchanged, in ``previous``
(a file already reviewed); and modelling choices (physics models, step
models) whose name the request doesn't mention. Zeros are skipped
(origins and start values).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/draft.py#L120)

## request_numbers

```python
opentcad.assist.request_numbers(text: str) -> list[float]
```

Every number in ``text``, in its own unit and converted to OpenTCAD
units where the unit is recognised (4 nm → 4 and 0.004).

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/draft.py#L77)

## ChatClient

```python
class opentcad.assist.ChatClient(
    base_url: str = <factory>,
    model: str = <factory>,
    api_key: Optional[str] = <factory>,
    timeout_s: float = 300.0,
) -> None
```

A client for any OpenAI-compatible chat server (llama-server, Ollama,
LM Studio, vLLM), using only the standard library.

The defaults come from the environment when the client is created:
``OPENTCAD_LLM_URL`` (else ``DEFAULT_URL``, a llama-server on this
machine), ``OPENTCAD_LLM_MODEL`` (else ``"local"``) and
``OPENTCAD_LLM_API_KEY`` (else none). Nothing is sent anywhere else.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/client.py#L30)

### ChatClient.models

```python
ChatClient.models() -> list[str]
```

Model names the server lists (a cheap connection check).

### ChatClient.chat

```python
ChatClient.chat(
    messages: list[dict],
    *,
    json_schema: Optional[dict] = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str
```

Send a chat; return the reply text. With ``json_schema`` the server
is asked for schema-constrained JSON, falling back to plain JSON
mode, then to no constraint, if it rejects the request format.

## LLMError

```python
class opentcad.assist.LLMError
```

The model server could not be reached or returned an error.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/client.py#L26)

## draft_catalog

```python
opentcad.assist.draft_catalog(
    request: str,
    *,
    client,
    max_repairs: int = 1,
) -> CatalogDraft
```

Draft typed private records using a configured ChatClient-compatible client.

A successful result means schema checked, not scientifically verified. Checks
cannot resolve catalog references because this function never opens a store.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/catalog.py#L75)

## CatalogDraft

```python
class opentcad.assist.CatalogDraft(
    proposal: Proposal | None = None,
    problems: list[str] = list(),
    assessments: list[dict] = list(),
    attempts: int = 0,
    raw_reply: str = '',
    request: str = '',
) -> None
```

The outcome of ``draft_catalog``: the proposed records with their
stated assumptions and questions, remaining ``problems``, a check of each
record, and the raw reply. Nothing is stored; ``to_dict`` writes a review
file.

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/assist/catalog.py#L27)

### CatalogDraft.ok

```python
property CatalogDraft.ok: bool
```

True if there is a proposal and it has no remaining problems.

### CatalogDraft.to_dict

```python
CatalogDraft.to_dict() -> dict
```

The draft as a review file: marked unaccepted and private, with
every generated value flagged as unverified.
