"""
opentcad.assist.draft — natural-language request → checked simulation file.

    draft = draft_deck("NMOS, 1 µm gate, 4 nm oxide, Id-Vg to 1.8 V", client=ChatClient())
    draft.deck          # a checked opentcad.io.Deck, or None if it never passed
    draft.flags         # every value not taken from the request, with reasons
    draft.questions     # what the model wants to know
    draft.problems      # checker problems left after the last repair round

The model's JSON goes through ``deck_from_dict``; any problems are sent
back for repair (``max_repairs`` rounds). Two independent sources mark
values as assumed: the model's own list, and a deterministic comparison
of every number in the file against the numbers in the request (after
unit conversion). A number the model didn't declare is still flagged.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from opentcad.io.deck import Deck, DeckError, deck_from_dict

from .prompt import deck_json_schema, response_schema, system_prompt


@dataclass
class Flag:
    """A value in the file that the request didn't state."""
    path: str
    value: Any
    reason: str = ""            # the model's reason, if it gave one
    declared: bool = False      # the model listed it as an assumption


@dataclass
class Draft:
    deck: Optional[Deck]
    data: Optional[dict]                     # the file as the model wrote it
    flags: list[Flag] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)
    attempts: int = 0
    transcript: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.deck is not None


# =============================================================================
# Numbers in the request vs numbers in the file
# =============================================================================
_UNIT_FACTORS = {   # → OpenTCAD units (µm, V, s; keV, cm⁻³, °C, K unchanged)
    "nm": 1e-3, "um": 1.0, "µm": 1.0, "μm": 1.0, "micron": 1.0, "microns": 1.0,
    "mm": 1e3, "a": 1e-4, "å": 1e-4, "angstrom": 1e-4,
    "mv": 1e-3, "v": 1.0, "kv": 1e3,
    "ms": 1e-3, "s": 1.0, "sec": 1.0, "min": 60.0, "mins": 60.0, "minute": 60.0,
    "minutes": 60.0, "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "kev": 1.0, "mev": 1e3, "ev": 1e-3,
}
_NUM = re.compile(
    r"(?<![\w.])([-+]?(?:\d+\.?\d*|\.\d+)(?:\s*[eE]\s*[-+]?\d+|\s*[x×]\s*10\^?\s*[-+]?\d+)?)"
    r"\s*([a-zA-Zµμå°]+)?")


def request_numbers(text: str) -> list[float]:
    """Every number in ``text``, in its own unit and converted to OpenTCAD
    units where the unit is recognised (4 nm → 4 and 0.004)."""
    out: list[float] = []
    for m in _NUM.finditer(text):
        raw = re.sub(r"\s+", "", m.group(1)).replace("×", "x")
        raw = re.sub(r"x10\^?", "e", raw)
        try:
            v = float(raw)
        except ValueError:
            continue
        out.append(v)
        unit = (m.group(2) or "").lower()
        if unit in _UNIT_FACTORS:
            out.append(v * _UNIT_FACTORS[unit])
        if unit in ("k", "kelvin") and v > 0:
            out.append(v - 273.15)           # K given, °C used (and vice versa)
        if unit in ("c", "°c", "°"):
            out.append(v + 273.15)
    return out


def _leaves(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, node


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-30)


_IGNORED = re.compile(r"^version$")
# Text values that are modelling choices (flagged unless the request names
# them): physics models, and the model/profile/ambient of process steps.
_CHOICE = re.compile(r"^device\.physics\.|^recipe\[\d+\]\.(model|profile|ambient)$")


def unstated_values(request: str, deck: dict,
                    previous: Optional[dict] = None) -> list[tuple[str, Any]]:
    """Values in ``deck`` the user didn't give: numbers that appear neither
    in ``request`` (after unit conversion) nor, unchanged, in ``previous``
    (a file already reviewed); and modelling choices (physics models, step
    models) whose name the request doesn't mention. Zeros are skipped
    (origins and start values)."""
    stated = request_numbers(request)
    words = request.lower()
    before = dict(_leaves(previous)) if previous else {}
    out = []
    for path, v in _leaves(deck):
        if _IGNORED.match(path) or (path in before and before[path] == v):
            continue
        if isinstance(v, str):
            if _CHOICE.match(path) and v.lower().replace("_", " ") not in words \
                    and v.lower() not in words:
                out.append((path, v))
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v == 0:
            continue
        if any(_close(float(v), s) for s in stated):
            continue
        out.append((path, v))
    return out


# =============================================================================
# Drafting
# =============================================================================
def _parse_reply(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("the reply is not JSON")
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    if "deck" not in data and "structure" in data:     # model skipped the wrapper
        data = {"deck": data, "assumptions": [], "questions": []}
    return data


def draft_deck(request: str, *, client, current: Optional[dict] = None,
               max_repairs: int = 2, constrained: bool = True) -> Draft:
    """Turn ``request`` into a checked simulation file using ``client``
    (anything with ``chat(messages, json_schema=...) -> str``). With
    ``current`` (a simulation-file dict) the request edits that file."""
    schema = response_schema(deck_json_schema() if constrained else None)
    messages = [{"role": "system", "content": system_prompt()}]
    if current is not None:
        messages.append({"role": "user", "content":
                         "Current simulation file:\n"
                         + json.dumps(current, separators=(",", ":"))
                         + f"\n\nChange it as follows: {request}"})
    else:
        messages.append({"role": "user", "content": request})

    draft = Draft(deck=None, data=None)
    declared: dict[str, dict] = {}
    for attempt in range(max_repairs + 1):
        draft.attempts = attempt + 1
        reply = client.chat(messages, json_schema=schema)
        messages.append({"role": "assistant", "content": reply})
        try:
            parsed = _parse_reply(reply)
        except (ValueError, json.JSONDecodeError) as exc:
            draft.problems = [("", f"unreadable reply: {exc}")]
            messages.append({"role": "user", "content":
                             f"That was not valid JSON ({exc}). Reply with the "
                             f"JSON object only."})
            continue
        deck_data = parsed.get("deck")
        for a in parsed.get("assumptions") or []:
            if isinstance(a, dict) and isinstance(a.get("path"), str):
                declared[a["path"]] = a
        draft.questions = [q for q in parsed.get("questions") or []
                           if isinstance(q, str)]
        draft.data = deck_data if isinstance(deck_data, dict) else None
        try:
            draft.deck = deck_from_dict(deck_data)
            draft.problems = []
            break
        except DeckError as exc:
            draft.deck = None
            draft.problems = exc.problems
            listing = "\n".join(f"- {p}: {m}" if p else f"- {m}"
                                for p, m in exc.problems)
            messages.append({"role": "user", "content":
                             "The simulation file has these problems:\n" + listing
                             + "\nFix them and reply with the complete JSON object "
                               "again (deck, assumptions, questions)."})
    draft.transcript = messages

    # Flags come from the file itself: anything the request didn't state.
    # The model's own assumption list only adds its reasons; a value it
    # "declared" that the request did state is not flagged.
    if draft.data is not None:
        source = draft.deck.to_dict() if draft.deck is not None else draft.data
        for path, value in unstated_values(request, source, previous=current):
            a = declared.get(path, {})
            reason = a.get("reason", "") if isinstance(a.get("reason"), str) else ""
            draft.flags.append(Flag(path, value, reason, declared=path in declared))
    return draft
