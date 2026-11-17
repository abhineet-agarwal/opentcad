"""Deterministic JSON and local immutable-object helpers (no executable imports)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """The revision encoding: sorted UTF-8 JSON, without NaN or insignificant whitespace."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def immutable_write(path: Path, data: bytes) -> bool:
    """Create without overwriting; detect corruption/collision rather than replacing content."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(f"Immutable object collision or corruption: {path}")
        return False
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    return True
