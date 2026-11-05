"""
Example 09 — Fair concentration-coupled anneal vs intrinsic Gaussian.

Demonstrates Phase 2.3b's new `apply_anneal_fair` against the earlier
`apply_anneal` on an implanted phosphorus profile. Both anneals start
from the same sharp Gaussian peak (as-implanted shape). The Fair model
integrates D_eff(n/n_i) sub-step by sub-step; the intrinsic model does
one analytic D_i Gaussian.

At S/D-level doping (n > n_i(T)) Fair's D⁻ and D⁻⁻ terms dominate and
drop the peak concentration faster — the classic phosphorus flattening
that doesn't exist in the intrinsic model.

Run:
    python examples/09_fair_anneal_profile.py
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping.anneal import (
    apply_anneal, apply_anneal_fair,
    fair_diffusivity_components, temperature_celsius_to_kelvin,
    _intrinsic_carrier_density_cm3)


def build():
    """Blank silicon substrate — the sharp P profile is installed
    directly on the MeshField to stand in for an implant step."""
    return (Structure(width_um=1.0, name="imp")
            .add_substrate("sub", 1.0, Material.SI, doping_Na=1e14)
            .add_contact("top",    0.0, 1.0, "sub", surface="top")
            .add_contact("bottom", 0.0, 1.0, "sub", surface="bottom")
            .to_meshfield(mesh_size_um=0.02))


def install_P_implant(mf, peak_y_um=0.95, sigma_um=0.03, peak_cm3=1e20):
    pts = np.asarray(mf.grid.points, dtype=float)
    y = pts[:, 1]
    mf.Nd = peak_cm3 * np.exp(-((y - peak_y_um) ** 2) / (2 * sigma_um ** 2))


def column_profile(mf, cx_um=0.5, strip_um=0.05):
    """Extract (y, Nd) along a vertical strip at x = cx_um."""
    pts = np.asarray(mf.grid.points, dtype=float)
    ok = np.abs(pts[:, 0] - cx_um) < strip_um
    y = pts[ok, 1]; Nd = mf.Nd[ok]
    idx = np.argsort(y)
    return y[idx], Nd[idx]


def main():
    T_C, t_s = 1000.0, 10.0
    T_K = temperature_celsius_to_kelvin(T_C)
    n_i_T = _intrinsic_carrier_density_cm3(T_K)
    cP = fair_diffusivity_components("P", T_K)

    print(f"Anneal condition: {T_C} C for {t_s} s")
    print(f"  n_i(T) = {n_i_T:.2e} cm^-3")
    print(f"  P: D_i={cP['D_i']:.2e}, D⁻={cP['D_minus']:.2e}, "
          f"D⁻⁻={cP['D_minus_minus']:.2e}")

    mf_i = build(); install_P_implant(mf_i)
    mf_f = build(); install_P_implant(mf_f)
    peak0 = float(mf_i.Nd.max())
    print(f"\nInitial P peak = {peak0:.3e} cm^-3  (u₀ = {peak0/n_i_T:.1f})")

    r_i = apply_anneal(mf_i, T_C, t_s, species_Nd="P")
    r_f = apply_anneal_fair(mf_f, T_C, t_s, species_Nd="P",
                             species_Na="B", stability_factor=0.4)

    print("\nResults:")
    print(f"  Intrinsic: sigma = {r_i.sigma_Nd_um:.4f} um, "
          f"peak after = {mf_i.Nd.max():.3e}")
    print(f"  Fair     : {r_f.n_sub_steps} sub-steps, "
          f"D_eff_peak/D_i = {r_f.D_eff_Nd_peak_cm2_s/r_f.D_i_Nd_cm2_s:.1f}x, "
          f"peak after = {mf_f.Nd.max():.3e}")
    drop_i = (peak0 - mf_i.Nd.max()) / peak0
    drop_f = (peak0 - mf_f.Nd.max()) / peak0
    print(f"  Peak drop: intrinsic {drop_i*100:.1f}%, "
          f"Fair {drop_f*100:.1f}% (ratio {drop_f/drop_i:.2f}x)")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  (matplotlib not installed - skipping plot)")
        return

    yi, Ndi = column_profile(mf_i)
    yf, Ndf = column_profile(mf_f)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    axes[0].semilogy(yi, np.maximum(Ndi, 1e8), label="intrinsic")
    axes[0].semilogy(yf, np.maximum(Ndf, 1e8), label="Fair")
    axes[0].axhline(n_i_T, ls=":", color="k", alpha=0.4, label=f"n_i(T)")
    axes[0].set_xlabel("y (um)"); axes[0].set_ylabel("Nd (cm^-3)")
    axes[0].set_title(f"P profile after {T_C:.0f}°C / {t_s:.0f} s")
    axes[0].set_ylim(1e14, 2e20)
    axes[0].legend(); axes[0].grid(True, alpha=0.3)

    # D_eff vs n for visual intuition — this is the formula actually used
    u = np.logspace(-2, 2, 200)
    n = u * n_i_T
    D_eff = cP["D_i"] + cP.get("D_minus", 0)*u + cP.get("D_minus_minus", 0)*u*u
    axes[1].loglog(n, [cP["D_i"]] * len(n), ls="--", label="D_i (intrinsic)")
    axes[1].loglog(n, D_eff, label="D_eff (Fair)")
    axes[1].axvline(n_i_T, ls=":", color="k", alpha=0.4, label="n_i(T)")
    axes[1].set_xlabel("n (cm^-3)"); axes[1].set_ylabel("D (cm²/s)")
    axes[1].set_title("Fair D_eff vs concentration")
    axes[1].legend(); axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    out = "examples/09_fair_anneal_profile.png"
    fig.savefig(out, dpi=120)
    print(f"\n  plot saved to {out}")


if __name__ == "__main__":
    main()
