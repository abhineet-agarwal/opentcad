"""
opentcad/device/models/references.py — the papers the physics models cite.

Model classes list these in ``references`` so a run's provenance record names
the source of each model's equations. A model's parameter values cite their
own sources in the material file. Each DOI, author list and title below
was checked against Crossref's record for the paper.
"""
from __future__ import annotations

from opentcad.provenance import Source

KLAASSEN_1992 = Source(
    "D. B. M. Klaassen, A unified mobility model for device simulation - I. Model "
    "equations and concentration dependence, Solid-State Electron. 35, 953 (1992)",
    doi="10.1016/0038-1101(92)90325-7")
LOMBARDI_1988 = Source(
    "C. Lombardi, S. Manzini, A. Saporito, M. Vanzi, A physically based mobility "
    "model for numerical simulation of nonplanar devices, IEEE Trans. Comput.-Aided "
    "Des. 7, 1164 (1988)", doi="10.1109/43.9186")
CANALI_1975 = Source(
    "C. Canali, G. Majni, R. Minder, G. Ottaviani, Electron and hole drift velocity "
    "measurements in silicon and their empirical relation to electric field and "
    "temperature, IEEE Trans. Electron Devices 22, 1045 (1975)",
    doi="10.1109/T-ED.1975.18267")
SHOCKLEY_READ_1952 = Source(
    "W. Shockley, W. T. Read, Statistics of the recombinations of holes and "
    "electrons, Phys. Rev. 87, 835 (1952)", doi="10.1103/PhysRev.87.835")
HALL_1952 = Source(
    "R. N. Hall, Electron-hole recombination in germanium, Phys. Rev. 87, 387 (1952)",
    doi="10.1103/PhysRev.87.387")
DZIEWIOR_SCHMID_1977 = Source(
    "J. Dziewior, W. Schmid, Auger coefficients for highly doped and highly excited "
    "silicon, Appl. Phys. Lett. 31, 346 (1977)", doi="10.1063/1.89694")
VAN_OVERSTRAETEN_DE_MAN_1970 = Source(
    "R. Van Overstraeten, H. De Man, Measurement of the ionization rates in diffused "
    "silicon p-n junctions, Solid-State Electron. 13, 583 (1970)",
    doi="10.1016/0038-1101(70)90139-5")
SLOTBOOM_DE_GRAAFF_1976 = Source(
    "J. W. Slotboom, H. C. de Graaff, Measurements of bandgap narrowing in Si "
    "bipolar transistors, Solid-State Electron. 19, 857 (1976)",
    doi="10.1016/0038-1101(76)90043-5")
BLAKEMORE_1982 = Source(
    "J. S. Blakemore, Approximations for Fermi-Dirac integrals, especially the "
    "function used to describe electron density in a semiconductor, "
    "Solid-State Electron. 25, 1067 (1982)", doi="10.1016/0038-1101(82)90143-5")
JOYCE_DIXON_1977 = Source(
    "W. B. Joyce, R. W. Dixon, Analytic approximations for the Fermi energy of an "
    "ideal Fermi gas, Appl. Phys. Lett. 31, 354 (1977)", doi="10.1063/1.89697")
