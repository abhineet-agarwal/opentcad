"""
opentcad/materials/database.py — Material parameter loader.

Loads YAML parameter files from opentcad/materials/params/.
Returns pydantic-validated parameter objects for use in device simulation.

Usage:
    from opentcad.materials.database import load_material
    si = load_material("Si")
    print(si.mobility_constant.electron_cm2_Vs)   # 1350.0
    print(si.recombination.tau_n_s)                # 1e-5
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel

PARAMS_DIR = Path(__file__).parent / "params"


class MobilityConstant(BaseModel):
    electron_cm2_Vs: float = 1350.0
    hole_cm2_Vs: float = 480.0
    uncertainty_percent: float = 5.0


class Recombination(BaseModel):
    tau_n_s: float = 1e-5       # [s] electron SRH lifetime
    tau_p_s: float = 1e-5       # [s] hole SRH lifetime
    Et_eV: float = 0.0          # trap energy re mid-gap [eV]
    Cn_cm6_per_s: float = 2.8e-31  # Auger electron
    Cp_cm6_per_s: float = 9.9e-32  # Auger hole
    B_rad_cm3_per_s: float = 9.5e-15  # Radiative


class BandStructure(BaseModel):
    Eg_eV_300K: float = 1.124
    electron_affinity_eV: float = 4.05
    Nc_cm3_300K: float = 2.86e19
    Nv_cm3_300K: float = 3.10e19
    ni_cm3_300K: float = 9.65e9
    permittivity_relative: float = 11.7


class VelocitySaturation(BaseModel):
    vsat_e_cm_s: float = 1.02e7
    vsat_h_cm_s: float = 0.72e7
    beta_e: float = 2.0
    beta_h: float = 1.0


class MaterialParams(BaseModel):
    """Validated material parameter set for one material."""
    material: str
    symbol: str
    is_insulator: bool = False   # True for SiO2/Si3N4 (Poisson only, no carriers)
    band_structure: BandStructure = BandStructure()
    mobility_constant: MobilityConstant = MobilityConstant()
    recombination: Recombination = Recombination()
    velocity_saturation: VelocitySaturation = VelocitySaturation()
    raw: dict = {}   # full YAML dict for advanced access


def load_material(symbol: str, process: Optional[str] = None) -> MaterialParams:
    """Load material parameters by symbol.

    Args:
        symbol: Material symbol, e.g. "Si", "SiO2", "GaN".
        process: Optional process variant, e.g. "hackerfab". If given, loads
                 from params/{process}/{symbol}.yaml with fallback to params/{symbol}.yaml.

    Returns:
        MaterialParams pydantic object.

    Raises:
        FileNotFoundError: If no YAML file found for the given symbol.
    """
    candidates = []
    if process:
        candidates.append(PARAMS_DIR / process / f"{symbol}.yaml")
    candidates.append(PARAMS_DIR / f"{symbol}.yaml")

    yaml_path = None
    for p in candidates:
        if p.exists():
            yaml_path = p
            break

    if yaml_path is None:
        available = [f.stem for f in PARAMS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"No parameter file found for '{symbol}'. "
            f"Available: {available}. "
            f"Searched: {[str(c) for c in candidates]}"
        )

    raw = yaml.safe_load(yaml_path.read_text())

    # Parse into typed sub-objects
    bs_raw = raw.get("bandgap", {})
    band = BandStructure(
        Eg_eV_300K=bs_raw.get("Eg_eV_300K", 1.124),
        electron_affinity_eV=raw.get("electron_affinity_eV", 4.05),
        Nc_cm3_300K=raw.get("Nc_cm3_300K", 2.86e19),
        Nv_cm3_300K=raw.get("Nv_cm3_300K", 3.10e19),
        ni_cm3_300K=raw.get("ni_cm3_300K", 9.65e9),
        permittivity_relative=raw.get("permittivity_relative", 11.7),
    )

    mob_raw = raw.get("mobility_constant", {})
    mob = MobilityConstant(
        electron_cm2_Vs=mob_raw.get("electron_cm2_Vs", 1350.0),
        hole_cm2_Vs=mob_raw.get("hole_cm2_Vs", 480.0),
    )

    rec_raw = raw.get("recombination", {})
    rec = Recombination(
        tau_n_s=rec_raw.get("tau_n_s", 1e-5),
        tau_p_s=rec_raw.get("tau_p_s", 1e-5),
        Et_eV=rec_raw.get("Et_eV", 0.0),
        Cn_cm6_per_s=rec_raw.get("Cn_cm6_per_s", 2.8e-31),
        Cp_cm6_per_s=rec_raw.get("Cp_cm6_per_s", 9.9e-32),
    )

    vs_raw = raw.get("velocity_saturation", {})
    vs = VelocitySaturation(
        vsat_e_cm_s=vs_raw.get("vsat_e_cm_s", 1.02e7),
        vsat_h_cm_s=vs_raw.get("vsat_h_cm_s", 0.72e7),
        beta_e=vs_raw.get("beta_e", 2.0),
        beta_h=vs_raw.get("beta_h", 1.0),
    )

    return MaterialParams(
        material=raw.get("material", symbol),
        symbol=raw.get("symbol", symbol),
        is_insulator=bool(raw.get("is_insulator", False)),
        band_structure=band,
        mobility_constant=mob,
        recombination=rec,
        velocity_saturation=vs,
        raw=raw,
    )
