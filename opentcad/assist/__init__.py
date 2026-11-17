"""
opentcad.assist — draft simulation files from plain-language requests with
an open-weights model served locally (llama-server, Ollama, LM Studio,
vLLM). Optional: the core never imports it.

    from opentcad.assist import ChatClient, draft_deck
    draft = draft_deck("pn diode, 1e17 both sides, forward I-V to 0.7 V",
                       client=ChatClient())
"""
from .client import ChatClient, LLMError

__all__ = ["ChatClient", "LLMError", "Draft", "Flag", "draft_deck",
           "request_numbers", "unstated_values", "CatalogDraft", "draft_catalog"]


def __getattr__(name):
    # Catalog drafting does not need geometry, deck plugins or solver imports.
    if name in {"Draft", "Flag", "draft_deck", "request_numbers", "unstated_values"}:
        from . import draft
        return getattr(draft, name)
    if name in {"CatalogDraft", "draft_catalog"}:
        from . import catalog
        return getattr(catalog, name)
    raise AttributeError(name)
