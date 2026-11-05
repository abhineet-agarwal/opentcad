"""opentcad.io — file input/output. Simulation files live in ``deck``."""
from .deck import (Deck, DeckError, DeckResult, deck_from_dict, dumps_deck,
                   load_deck, run_deck, save_deck)

__all__ = ["Deck", "DeckError", "DeckResult", "deck_from_dict", "dumps_deck",
           "load_deck", "run_deck", "save_deck"]
