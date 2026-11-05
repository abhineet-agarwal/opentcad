"""
opentcad.device.builtin_models — registers the built-in physics models
under the names simulation files use. ``opentcad.plugins`` calls
``register()`` the first time a registry is consulted.
"""
from __future__ import annotations

from opentcad.plugins import register_model


def register() -> None:
    from .models import (SRH, Auger, Avalanche, Boltzmann, Canali,
                         ConstantMobility, FermiDirac, JoyceDixon, Klaassen,
                         Lombardi, NoBGN, Radiative, Slotboom)
    for name, cls in (("constant", ConstantMobility), ("klaassen", Klaassen),
                      ("canali", Canali), ("lombardi", Lombardi)):
        register_model("mobility", name, cls)
    for name, cls in (("srh", SRH), ("auger", Auger),
                      ("radiative", Radiative), ("avalanche", Avalanche)):
        register_model("recombination", name, cls)
    for name, cls in (("none", NoBGN), ("slotboom", Slotboom)):
        register_model("bgn", name, cls)
    for name, cls in (("boltzmann", Boltzmann), ("fermi_dirac", FermiDirac),
                      ("joyce_dixon", JoyceDixon)):
        register_model("statistics", name, cls)
