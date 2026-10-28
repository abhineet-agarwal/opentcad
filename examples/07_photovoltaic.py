"""Generic illuminated diode; analytically prescribed doping, no process calibration.

Run from the repository root: python examples/07_photovoltaic.py
Produces a dark/light IV plot and reports the physical current for 20 um depth.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from opentcad.device.optical import BeerLambert, current_from_2d
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def main():
    import devsim
    fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
    for irradiance in (0, 1000):
        mf = (Structure(width_um=1, name="generic_pv")
              .add_substrate("p", 2.7, Material.SI, doping_Na=1e16)
              .add_layer("n", 0.3, Material.SI, doping_Nd=1e18)
              .add_contact("p", 0, 1, "p", surface="bottom")
              .add_contact("n", 0, 1, "n", surface="top")
              .to_meshfield(mesh_size_um=0.08))
        # alpha and R are demonstration choices, not a fitted optical dataset.
        BeerLambert(660, irradiance, 3000, reflectance=0.3).apply(mf, surface_y_um=3)
        solver = DeviceSolver(mf, {"Silicon": load_material("Si")})
        try:
            v, i = solver.iv_sweep("p", "n", 0, 0.65, 0.025)
            physical = current_from_2d(i, depth_um=20)
            ax.plot(v, -physical * 1e9, label=f"{irradiance} W/m²")
            print(f"{irradiance} W/m²: short-circuit delivery {-physical[0]:.6g} A")
        finally:
            devsim.delete_device(device=solver._device_name)
    ax.axhline(0, color="0.6", lw=0.6)
    ax.set(xlabel="Positive-terminal voltage (V)", ylabel="Delivered current (nA)",
           title="3 µm conceptual Si PV; physical area 1 × 20 µm²", ylim=(-10, 8))
    ax.legend()
    fig.savefig(Path(__file__).with_suffix(".png"), dpi=160)


if __name__ == "__main__":
    main()
