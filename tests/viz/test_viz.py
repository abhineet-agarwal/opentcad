"""Figure data (opentcad.viz.fields), palette, and Plotly builders."""
import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.viz import fields as F
from opentcad.viz import palette as P


@pytest.fixture(scope="module")
def mf():
    """1.0 × 0.5 µm Si with a 50 nm oxide; n-well over p-body."""
    s = (Structure(width_um=1.0, name="viz")
         .add_substrate("body", 0.3, Material.SI, doping_Na=1e16)
         .add_layer("well", 0.2, Material.SI, doping_Nd=1e18)
         .add_layer("ox", 0.05, Material.SIO2)
         .add_contact("gate", 0.2, 0.8, "ox", surface="top")
         .add_contact("body", 0.0, 1.0, "body", surface="bottom"))
    return s.to_meshfield(mesh_size_um=0.04)


def _linear(mf):
    p = F.points_um(mf)
    return 2.0 * p[:, 0] + 3.0 * p[:, 1]


# ---- fields ---------------------------------------------------------------------
def test_grid_sampling_is_exact_for_linear_fields(mf):
    g = F.sample_on_grid(mf, _linear(mf), nx=80)
    xx, yy = np.meshgrid(g.x, g.y)
    ok = np.isfinite(g.z)
    assert ok.mean() > 0.95
    assert np.allclose(g.z[ok], 2 * xx[ok] + 3 * yy[ok], atol=1e-9)
    only_si = F.sample_on_grid(mf, _linear(mf), nx=80, materials=[Material.SI])
    assert np.all(np.isnan(only_si.z[g.y > 0.5 + 1e-6]))      # oxide masked


def test_signed_log10():
    v = F.signed_log10([1e18, -1e16, 5e13, 0.0], floor=1e14)
    assert np.allclose(v, [4.0, -2.0, 0.0, 0.0])


def test_zero_contour_finds_the_junction(mf):
    net = F.net_doping(mf)
    segs = F.zero_contour(mf, net)
    assert len(segs) > 0
    # Nodes on the interface carry the well's Nd and the body's Na, so the
    # sign change sits within one element of y = 0.3 µm.
    assert np.all(np.abs(segs[..., 1] - 0.3) < 0.04)
    assert F.zero_contour(mf, np.ones(mf.n_points)).shape == (0, 2, 2)


def test_material_edges_and_labels(mf):
    edges = F.material_edges(mf)
    ys = edges[..., 1]
    on_interface = np.all(np.abs(ys - 0.5) < 1e-9, axis=1)
    assert on_interface.any()                          # Si/SiO2 boundary
    assert not np.any(np.all(np.abs(ys - 0.3) < 1e-9, axis=1))   # Si/Si isn't one
    labels = F.material_labels(mf)
    assert set(labels) == {Material.SI, Material.SIO2}
    x, y = labels[Material.SIO2]
    assert 0.5 < y < 0.55
    thin = F.material_labels(mf, min_thickness_frac=0.2)   # 50 nm < 0.2 × 550 nm
    assert Material.SIO2 not in thin and Material.SI in thin


def test_vertical_cut_and_cells(mf):
    cut = F.vertical_cut(mf, 0.4, {"f": _linear(mf)}, n=50)
    ok = np.isfinite(cut["f"])
    assert np.allclose(cut["f"][ok], 0.8 + 3 * cut["y_um"][ok], atol=1e-9)
    assert np.all(cut["y_um"][~ok] > 0.5 - 1e-9)          # only the oxide is cut off
    cells = F.cells_on_grid(mf, np.array([0.5, 2.0]), np.array([0.1]))
    assert cells[0, 0] >= 0 and cells[0, 1] == -1


# ---- palette --------------------------------------------------------------------
def test_diverging_arms_are_lightness_matched():
    for step, red in P.RED.items():
        Lb, Cb, _ = P.oklch(P.BLUE[step])
        Lr, Cr, hr = P.oklch(red)
        assert Lr == pytest.approx(Lb, abs=0.005)
        assert Cr == pytest.approx(Cb, abs=0.01)
        assert hr == pytest.approx(24.9, abs=2.0)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_diverging_scale_is_monotone_towards_the_midpoint(theme):
    L = [P.oklch(c)[0] for _, c in P.diverging_colorscale(theme)]
    mid = len(L) // 2
    left, right = L[: mid + 1], L[mid:]
    if theme == "light":      # brightest at zero
        assert left == sorted(left) and right == sorted(right, reverse=True)
    else:                     # darkest at zero
        assert left == sorted(left, reverse=True) and right == sorted(right)


def test_fixed_colours_per_entity():
    assert P.material_color(Material.SI) == P.CATEGORICAL["light"][0]
    assert P.material_color(Material.SIO2, "dark") == P.CATEGORICAL["dark"][1]
    assert P.species_color("boron") == P.CATEGORICAL["light"][0]
    assert P.species_color("arsenic", known=["arsenic", "zinc"]) == \
        P.species_color("arsenic")
    with pytest.raises(ValueError):
        P.diverging_colorscale("sepia")


# ---- Plotly builders --------------------------------------------------------------
def test_plotly_builders(mf):
    pytest.importorskip("plotly")
    from opentcad.viz import interactive as I
    for theme in ("light", "dark"):
        fig = I.doping_map(mf, theme=theme, nx=120)
        heat = [t for t in fig.data if t.type == "heatmap" and t.name == "net doping"][0]
        assert heat.zmin == -heat.zmax
        assert "0" in heat.colorbar.ticktext
        assert any(t.name == "p-n junction" for t in fig.data)
        assert fig.layout.paper_bgcolor == P.INK[theme]["surface"]

        s = I.structure_map(mf, theme=theme, nx=120, show_mesh=True)
        texts = {a.text for a in s.layout.annotations}
        assert {"Silicon", "gate", "body"} <= texts

        prof = I.doping_profile(mf, 0.5, theme=theme)
        assert prof.layout.yaxis.type == "log"
        assert any("xj" in (a.text or "") for a in prof.layout.annotations)

        lin, log = I.iv_figures([0, 0.5, 1.0], [1e-9, -1e-6, -1e-3], theme=theme,
                                y_label="I [A/cm]")
        assert lin.layout.yaxis.type == "linear" and log.layout.yaxis.type == "log"
        assert log.layout.yaxis.title.text == "|I| [A/cm]"
        assert list(log.data[0].y) == [1e-9, 1e-6, 1e-3]

        m = I.metric_figure([3, 5, 7], [0.5, None, 0.7], theme=theme)
        assert np.isnan(m.data[0].y[1])
    with pytest.raises(ValueError, match="does not cross"):
        I.doping_profile(mf, 5.0)


# ---- solution fields ------------------------------------------------------------
def _with_solution(mf):
    snap = type(mf)(grid=mf.grid.copy(deep=True), contacts=list(mf.contacts),
                    metadata={"solution_bias_V": {"gate": 1.0}})
    p = F.points_um(snap)
    snap.grid.point_data["Potential"] = 0.5 - 2.0 * p[:, 1]       # E_y = 2 V/µm
    snap.grid.point_data["Electrons"] = 10.0 ** (5 + 10 * p[:, 1])
    snap.grid.point_data["Holes"] = np.full(snap.n_points, 1e16)
    return snap


def test_cell_gradient_and_electric_field(mf):
    g = F.cell_gradient(mf, _linear(mf))
    assert np.allclose(g, [2.0, 3.0])
    snap = _with_solution(mf)
    e = F.electric_field_V_per_cm(snap)
    assert np.allclose(e, 2.0e4)                                    # 2 V/µm
    grid = F.cell_values_on_grid(mf, e, np.array([0.5, 3.0]), np.array([0.2]))
    assert grid[0, 0] == pytest.approx(2e4) and np.isnan(grid[0, 1])


def test_field_map_builder(mf):
    pytest.importorskip("plotly")
    from opentcad.viz import interactive as I
    snap = _with_solution(mf)
    for q in I.FIELD_QUANTITIES:
        fig = I.field_map(snap, q, nx=120)
        assert "gate 1 V" in fig.layout.title.text
    pot = I.field_map(snap, "Potential", nx=120).data[0]
    assert pot.zmin == -pot.zmax
    e = I.field_map(snap, "ElectricField", nx=120).data[0]
    assert np.nanmax(e.z) == pytest.approx(np.log10(2e4))          # log scale
    with pytest.raises(ValueError, match="snapshot"):
        I.field_map(mf, "Electrons")
    with pytest.raises(ValueError, match="quantity"):
        I.field_map(snap, "Temperature")
