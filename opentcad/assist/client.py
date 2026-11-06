"""
opentcad.assist.client — a minimal chat client for OpenAI-compatible servers.

Works with local open-weights servers: llama.cpp's ``llama-server``,
Ollama (``/v1``), LM Studio, vLLM. Standard library only (no SDK).

Configuration (arguments override the environment):

    OPENTCAD_LLM_URL      base URL, default http://127.0.0.1:8080/v1 (llama-server)
                          Ollama: http://127.0.0.1:11434/v1
    OPENTCAD_LLM_MODEL    model name the server expects, default "local"
    OPENTCAD_LLM_API_KEY  only if the server wants one
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_URL = "http://127.0.0.1:8080/v1"


class LLMError(RuntimeError):
    """The model server could not be reached or returned an error."""


@dataclass
class ChatClient:
    base_url: str = field(default_factory=lambda: os.environ.get(
        "OPENTCAD_LLM_URL", DEFAULT_URL))
    model: str = field(default_factory=lambda: os.environ.get(
        "OPENTCAD_LLM_MODEL", "local"))
    api_key: Optional[str] = field(default_factory=lambda: os.environ.get(
        "OPENTCAD_LLM_API_KEY"))
    timeout_s: float = 300.0

    def _post(self, path: str, body: dict) -> dict:
        url = self.base_url.rstrip("/") + path
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"cannot reach the model server at {url}: {exc}. "
                           f"Start one (e.g. llama-server -m model.gguf "
                           f"--port 8080) or set OPENTCAD_LLM_URL.") from None

    def models(self) -> list[str]:
        """Model names the server lists (a cheap connection check)."""
        url = self.base_url.rstrip("/") + "/models"
        req = urllib.request.Request(url, headers=(
            {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"cannot reach the model server at {url}: {exc}") from None
        return [m.get("id", "?") for m in data.get("data", [])]

    def chat(self, messages: list[dict], *, json_schema: Optional[dict] = None,
             temperature: float = 0.1, max_tokens: int = 4096) -> str:
        """Send a chat; return the reply text. With ``json_schema`` the server
        is asked for schema-constrained JSON, falling back to plain JSON
        mode, then to no constraint, if it rejects the request format."""
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        formats: list[Optional[dict]] = [None]
        if json_schema is not None:
            formats = [{"type": "json_schema",
                        "json_schema": {"name": "response", "schema": json_schema}},
                       {"type": "json_object"}, None]
        last: Optional[LLMError] = None
        for fmt in formats:
            payload = dict(body)
            if fmt is not None:
                payload["response_format"] = fmt
            try:
                data = self._post("/chat/completions", payload)
            except LLMError as exc:
                if "HTTP 4" in str(exc) and fmt is not None:
                    last = exc                  # format not supported: try next
                    continue
                raise
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise LLMError(f"unexpected reply from the server: "
                               f"{json.dumps(data)[:300]}") from None
        raise last or LLMError("no response format accepted by the server")
