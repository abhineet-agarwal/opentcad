"""
opentcad.viz.interactive — Plotly figures (the GUI's charts).

Each builder takes data plus ``theme="light" | "dark"`` and returns a
``plotly.graph_objects.Figure`` styled with ``opentcad.viz.palette``:
thin lines, recessive grid, one y-axis per chart, hover readouts, and
direct labels where colour alone would carry identity.

    doping_map(mf)            net doping, signed log scale, p-n junction drawn
    structure_map(mf)         materials and contacts
    doping_profile(mf, x)     species concentrations down a vertical cut
    iv_figures(v, i)          linear and log charts (two figures, never two axes)
    metric_figure(xs, ys)     one sweep metric against the swept value

Plotly is an optional dependency (``pip install -e ".[gui]"``).
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from opentcad.geometry.formats import MATERIAL_NAMES, Material, MeshField

from . import fields as F
from .palette import (CATEGORICAL, FONT, INK, diverging_colorscale, material_color,
                      sequential_colorscale, species_color)


def _go():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:                # pragma: no cover
        raise ImportError("interactive figures need plotly: "
                          "pip install -e '.[gui]'") from exc
    return go


def _layout(theme: str, title: str = "", *, height: Optional[int] = None) -> dict:
    ink = INK[theme]
    axis = dict(gridcolor=ink["grid"], linecolor=ink["axis"], zeroline=False,
                ticks="outside", tickcolor=ink["axis"], showline=True,
                title_font=dict(color=ink["secondary"], size=12),
                tickfont=dict(color=ink["muted"], size=11))
    out = dict(
        title=dict(text=title, font=dict(size=14, color=ink["primary"]), x=0.0,
                   xanchor="left"),
        font=dict(family=FONT, color=ink["primary"], size=12),
        paper_bgcolor=ink["surface"], plot_bgcolor=ink["surface"],
        xaxis=dict(axis), yaxis=dict(axis),
        margin=dict(l=64, r=24, t=48 if title else 16, b=48),
        hoverlabel=dict(bgcolor=ink["surface"], bordercolor=ink["axis"],
                        font=dict(family=FONT, color=ink["primary"])),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right",
                    x=1.0, font=dict(color=ink["secondary"])),
    )
    if height:
        out["height"] = height
    return out


def _segments_xy(segs: np.ndarray) -> tuple[list, list]:
    """(n, 2, 2) segments → x/y lists with None breaks (one Plotly trace)."""
    xs, ys = [], []
    for (x0, y0), (x1, y1) in segs:
        xs += [x0, x1, None]
        ys += [y0, y1, None]
    return xs, ys


def _equal_aspect(fig, mf: MeshField, width_px: int = 760) -> None:
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    plot_w = width_px - 64 - 110
    h = int(plot_w * (ymax - ymin) / max(xmax - xmin, 1e-12)) + 100
    fig.update_layout(height=max(220, min(h, 900)))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, constrain="domain")
    fig.update_xaxes(range=[xmin, xmax], constrain="domain")


def _sup(n: int) -> str:
    return f"10<sup>{n}</sup>"


# =============================================================================
# 2-D maps
# =============================================================================
def doping_map(mf: MeshField, *, theme: str = "light", nx: int = 500,
               floor: float = 1e14, title: str = "Net doping"):
    """Net doping Nd − Na on a signed log scale: p-type blue, n-type red,
    gray within ±floor. Non-semiconductor regions are shown flat and
    labelled; material edges as hairlines; the p-n junction as a line."""
    go = _go()
    ink = INK[theme]
    net = F.net_doping(mf)
    g = F.sample_on_grid(mf, F.signed_log10(net, floor), nx=nx,
                         materials=F.SEMICONDUCTORS)
    nd = F.sample_on_grid(mf, mf.Nd, nx=nx, materials=F.SEMICONDUCTORS).z
    na = F.sample_on_grid(mf, mf.Na, nx=nx, materials=F.SEMICONDUCTORS).z
    zmax = max(2.0, float(np.ceil(np.nanmax(np.abs(g.z))))) if np.isfinite(g.z).any() else 2.0
    decades = int(zmax)
    log0 = int(round(np.log10(floor)))
    # Every second decade, so labels never crowd; 0 = |N| below the floor.
    ticks = list(range(-(decades // 2) * 2, (decades // 2) * 2 + 1, 2))
    labels = [("p " if k < 0 else "n ") + _sup(log0 + abs(k)) if k else "0"
              for k in ticks]
    custom = np.stack([nd - na, nd, na], axis=-1)
    fig = go.Figure()

    # Insulators/metals: one flat neutral fill, named on hover.
    cells = F.cells_on_grid(mf, g.x, g.y)
    mats = np.asarray(mf.material_ids)
    mat_at = np.where(cells >= 0, mats[np.clip(cells, 0, None)], -1)
    semi_ids = [int(m) for m in F.SEMICONDUCTORS]
    mask = (mat_at >= 0) & ~np.isin(mat_at, semi_ids)
    other = np.where(mask, 1.0, np.nan)
    names = np.full(cells.shape, "", dtype=object)
    for mid in np.unique(mat_at[mask]):
        m = Material(int(mid))
        names[mat_at == mid] = MATERIAL_NAMES.get(m, m.name)
    if mask.any():
        fig.add_trace(go.Heatmap(
            x=g.x, y=g.y, z=other, customdata=names, showscale=False,
            colorscale=[[0, ink["grid"]], [1, ink["grid"]]],
            hovertemplate="%{customdata}<extra></extra>", name="insulator"))

    fig.add_trace(go.Heatmap(
        x=g.x, y=g.y, z=g.z, customdata=custom, zmin=-zmax, zmax=zmax,
        colorscale=diverging_colorscale(theme), zsmooth=False,
        colorbar=dict(title=dict(text="Nd − Na [cm⁻³]",
                                 font=dict(color=ink["secondary"], size=11)),
                      tickvals=ticks, ticktext=labels, thickness=12,
                      outlinewidth=0, tickfont=dict(color=ink["muted"], size=10)),
        hovertemplate=("x %{x:.3f} µm · y %{y:.3f} µm<br>"
                       "net %{customdata[0]:.2e} cm⁻³<br>"
                       "Nd %{customdata[1]:.2e} · Na %{customdata[2]:.2e}"
                       "<extra></extra>"),
        name="net doping"))

    ex, ey = _segments_xy(F.material_edges(mf))
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip",
                             line=dict(color=ink["axis"], width=1),
                             showlegend=False, name="material edges"))
    junction = F.zero_contour(mf, net)
    if len(junction):
        jx, jy = _segments_xy(junction)
        fig.add_trace(go.Scatter(x=jx, y=jy, mode="lines", hoverinfo="skip",
                                 line=dict(color=ink["primary"], width=2),
                                 name="p-n junction"))
    for m, (x, y) in F.material_labels(mf, min_thickness_frac=0.04).items():
        if m not in F.SEMICONDUCTORS:
            fig.add_annotation(x=x, y=y, text=MATERIAL_NAMES.get(m, m.name),
                               showarrow=False,
                               font=dict(color=ink["secondary"], size=11))
    fig.update_layout(**_layout(theme, title))
    fig.update_xaxes(title_text="x [µm]")
    fig.update_yaxes(title_text="y [µm]")
    _equal_aspect(fig, mf)
    return fig


FIELD_QUANTITIES = ("Potential", "Electrons", "Holes", "ElectricField")


def field_map(mf: MeshField, quantity: str, *, theme: str = "light",
              nx: int = 500, title: Optional[str] = None):
    """A solution field from a solver snapshot (``DeviceSolver.snapshot`` or
    the ``fields`` analysis):

      * ``Potential`` — ψ [V], diverging around 0 (n-like +, p-like −), all regions
      * ``Electrons`` / ``Holes`` — log10 density [cm⁻³], semiconductors only
      * ``ElectricField`` — |E| [V/cm] per triangle, all regions

    Material edges and the p-n junction are drawn on top."""
    go = _go()
    ink = INK[theme]
    if quantity not in FIELD_QUANTITIES:
        raise ValueError(f"quantity must be one of {FIELD_QUANTITIES}")
    if quantity != "ElectricField" and quantity not in mf.grid.point_data:
        raise ValueError(f"the MeshField has no {quantity!r} data; take a "
                         f"solver snapshot first")
    if quantity == "ElectricField" and "Potential" not in mf.grid.point_data:
        raise ValueError("the MeshField has no 'Potential' data; take a "
                         "solver snapshot first")
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    if quantity == "Potential":
        g = F.sample_on_grid(mf, mf.grid.point_data["Potential"], nx=nx)
        x, y, z = g.x, g.y, g.z
        zmax = float(np.nanmax(np.abs(z))) or 1.0
        trace = dict(z=z, zmin=-zmax, zmax=zmax,
                     colorscale=diverging_colorscale(theme),
                     colorbar_title="ψ [V]",
                     hovertemplate="ψ %{z:.3f} V<extra></extra>")
        label = "Electrostatic potential"
    elif quantity in ("Electrons", "Holes"):
        vals = np.asarray(mf.grid.point_data[quantity], dtype=float)
        logv = np.log10(np.clip(vals, 1.0, None))
        g = F.sample_on_grid(mf, logv, nx=nx, materials=F.SEMICONDUCTORS)
        x, y, z = g.x, g.y, g.z
        hi = float(np.ceil(np.nanmax(z))) if np.isfinite(z).any() else 1.0
        lo = max(0.0, hi - 16.0, float(np.floor(np.nanmin(z))))
        ticks = list(range(int(lo), int(hi) + 1, 2 if hi - lo > 8 else 1))
        trace = dict(z=z, zmin=lo, zmax=hi, colorscale=sequential_colorscale(theme),
                     colorbar=dict(tickvals=ticks, ticktext=[_sup(k) for k in ticks]),
                     colorbar_title=f"{quantity.lower()} [cm⁻³]",
                     hovertemplate=f"{quantity.lower()} 10^%{{z:.2f}} cm⁻³<extra></extra>")
        label = f"{quantity} density"
    else:
        # Log scale: the oxide field (MV/cm) would wash out the silicon on a
        # linear one.
        e = np.log10(np.clip(F.electric_field_V_per_cm(mf), 1.0, None))
        ny = max(2, int(round(nx * (ymax - ymin) / max(xmax - xmin, 1e-12))))
        x, y = np.linspace(xmin, xmax, nx), np.linspace(ymin, ymax, ny)
        z = F.cell_values_on_grid(mf, e, x, y)
        hi = float(np.ceil(np.nanmax(z))) if np.isfinite(z).any() else 1.0
        lo = max(0.0, hi - 5.0)
        ticks = list(range(int(lo), int(hi) + 1))
        trace = dict(z=z, zmin=lo, zmax=hi, colorscale=sequential_colorscale(theme),
                     colorbar=dict(tickvals=ticks, ticktext=[_sup(k) for k in ticks]),
                     colorbar_title="|E| [V/cm]",
                     hovertemplate="|E| 10^%{z:.2f} V/cm<extra></extra>")
        label = "Electric field"
    cb = trace.pop("colorbar", {})
    cb_title = trace.pop("colorbar_title")
    fig = go.Figure(go.Heatmap(
        x=x, y=y, zsmooth=False,
        colorbar=dict(title=dict(text=cb_title, font=dict(color=ink["secondary"], size=11)),
                      thickness=12, outlinewidth=0,
                      tickfont=dict(color=ink["muted"], size=10), **cb),
        **trace))
    ex, ey = _segments_xy(F.material_edges(mf))
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip",
                             line=dict(color=ink["axis"], width=1), showlegend=False))
    junction = F.zero_contour(mf, F.net_doping(mf))
    if len(junction):
        jx, jy = _segments_xy(junction)
        fig.add_trace(go.Scatter(x=jx, y=jy, mode="lines", hoverinfo="skip",
                                 line=dict(color=ink["primary"], width=1.5, dash="dot"),
                                 name="p-n junction"))
    bias = mf.metadata.get("solution_bias_V") or {}
    nonzero = {c: v for c, v in bias.items() if v}
    suffix = ("  (" + ", ".join(f"{c} {v:g} V" for c, v in nonzero.items()) + ")"
              if nonzero else "  (all contacts 0 V)")
    fig.update_layout(**_layout(theme, (title or label) + suffix))
    fig.update_xaxes(title_text="x [µm]")
    fig.update_yaxes(title_text="y [µm]")
    _equal_aspect(fig, mf)
    return fig


def structure_map(mf: MeshField, *, theme: str = "light", nx: int = 500,
                  show_mesh: bool = False, title: str = "Structure"):
    """Materials (fixed colour per material, labelled on the regions) and
    contacts (thick labelled lines). ``show_mesh`` draws triangle edges."""
    go = _go()
    ink = INK[theme]
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    ny = max(2, int(round(nx * (ymax - ymin) / max(xmax - xmin, 1e-12))))
    x, y = np.linspace(xmin, xmax, nx), np.linspace(ymin, ymax, ny)
    cells = F.cells_on_grid(mf, x, y)
    mats = np.asarray(mf.material_ids)
    present = [Material(int(m)) for m in np.unique(mats)]
    index = {m: k for k, m in enumerate(present)}
    z = np.full(cells.shape, np.nan)
    names = np.full(cells.shape, "", dtype=object)
    inside = cells >= 0
    mat_at = np.where(inside, mats[np.clip(cells, 0, None)], -1)
    for m in present:
        sel = mat_at == int(m)
        z[sel] = index[m]
        names[sel] = MATERIAL_NAMES.get(m, m.name)
    n = len(present)
    scale = []
    for k, m in enumerate(present):
        c = material_color(m, theme)
        scale += [[k / n, c], [(k + 1) / n, c]]
    fig = go.Figure(go.Heatmap(
        x=x, y=y, z=z, customdata=names, zmin=-0.5 if n == 1 else 0,
        zmax=n - 0.5 if n == 1 else n, colorscale=scale if n > 1 else
        [[0, material_color(present[0], theme)], [1, material_color(present[0], theme)]],
        showscale=False, hovertemplate="%{customdata}<extra></extra>"))
    if n > 1:
        fig.data[0].update(z=z + 0.5)            # centre each band on its colour
    ex, ey = _segments_xy(F.material_edges(mf))
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip",
                             line=dict(color=ink["surface"], width=1.5),
                             showlegend=False))
    if show_mesh:
        pts = F.points_um(mf)
        tris = F.triangles(mf)
        segs = np.concatenate([pts[tris[:, [0, 1]]], pts[tris[:, [1, 2]]],
                               pts[tris[:, [2, 0]]]])
        mx, my = _segments_xy(segs)
        fig.add_trace(go.Scatter(x=mx, y=my, mode="lines", hoverinfo="skip",
                                 line=dict(color=ink["surface"], width=0.4),
                                 opacity=0.6, showlegend=False))
    for m, (lx, ly) in F.material_labels(mf, min_thickness_frac=0.04).items():
        fig.add_annotation(x=lx, y=ly, text=MATERIAL_NAMES.get(m, m.name),
                           showarrow=False, font=dict(color="#ffffff", size=11))
    pts = F.points_um(mf)
    for c in mf.contacts:
        p = pts[np.asarray(c.boundary_nodes, dtype=int)]
        if len(p) == 0:
            continue
        horizontal = np.ptp(p[:, 0]) >= np.ptp(p[:, 1])
        p = p[np.argsort(p[:, 0] if horizontal else p[:, 1])]
        fig.add_trace(go.Scatter(
            x=p[:, 0], y=p[:, 1], mode="lines", name=c.name,
            line=dict(color=ink["primary"], width=5), showlegend=False,
            hovertemplate=f"contact {c.name} ({c.contact_type})<extra></extra>"))
        # End ticks, so neighbouring contacts read as separate.
        end_symbol = "line-ns" if horizontal else "line-ew"
        fig.add_trace(go.Scatter(
            x=p[[0, -1], 0], y=p[[0, -1], 1], mode="markers", hoverinfo="skip",
            marker=dict(symbol=end_symbol, size=16,
                        line=dict(color=ink["primary"], width=2)),
            showlegend=False))
        mid = p[len(p) // 2]
        top = mid[1] >= (ymin + ymax) / 2
        fig.add_annotation(x=mid[0], y=mid[1], text=c.name, showarrow=False,
                           yshift=12 if top else -12,
                           font=dict(color=ink["primary"], size=11))
    fig.update_layout(**_layout(theme, title))
    fig.update_xaxes(title_text="x [µm]")
    fig.update_yaxes(title_text="y [µm]")
    _equal_aspect(fig, mf)
    return fig


# =============================================================================
# 1-D charts
# =============================================================================
def doping_profile(mf: MeshField, x_um: float, *, theme: str = "light",
                   floor: float = 1e13, title: Optional[str] = None):
    """Concentration of each tracked species (and any untracked doping)
    against depth below the semiconductor top at x = x_um; junction
    depths marked."""
    go = _go()
    ink = INK[theme]
    species = mf.species_names()
    fields = {s: mf.get_species(s) for s in species}
    fields["__nd"] = mf.Nd
    fields["__na"] = mf.Na
    cut = F.vertical_cut(mf, x_um, fields)
    y = cut["y_um"]
    ok = ~np.isnan(cut["__nd"])
    if not ok.any():
        raise ValueError(f"x = {x_um} µm does not cross a semiconductor")
    depth_nm = (y[ok].max() - y) * 1e3
    from opentcad.process.doping.pearson_iv import dopant_kind
    sp_nd = sum((cut[s] for s in species if dopant_kind(s) == "donor"),
                np.zeros_like(y))
    sp_na = sum((cut[s] for s in species if dopant_kind(s) == "acceptor"),
                np.zeros_like(y))
    fig = go.Figure()
    lines = [(s.capitalize(), cut[s], species_color(s, theme, species), "solid")
             for s in species]
    for label, total, part in (("background Nd", cut["__nd"], sp_nd),
                               ("background Na", cut["__na"], sp_na)):
        rest = total - part
        if np.nanmax(rest) > floor:
            lines.append((label, rest, ink["muted"], "dash"))
    for label, vals, color, dash in lines:
        v = np.where(vals > floor, vals, np.nan)
        fig.add_trace(go.Scatter(x=depth_nm[ok], y=v[ok], mode="lines", name=label,
                                 line=dict(color=color, width=2, dash=dash),
                                 hovertemplate=f"{label}: %{{y:.2e}} cm⁻³<extra></extra>"))
    net = cut["__nd"][ok] - cut["__na"][ok]
    flips = np.flatnonzero(np.diff(np.sign(net)) != 0)
    for k in flips:
        t = net[k] / (net[k] - net[k + 1])
        xj = depth_nm[ok][k] + t * (depth_nm[ok][k + 1] - depth_nm[ok][k])
        fig.add_vline(x=xj, line=dict(color=ink["secondary"], width=1, dash="dot"),
                      annotation_text=f"xj {xj:.0f} nm",
                      annotation_font=dict(color=ink["secondary"], size=11))
    fig.update_layout(**_layout(theme, title or f"Doping at x = {x_um:g} µm",
                                height=360), hovermode="x unified")
    fig.update_xaxes(title_text="depth below surface [nm]", rangemode="tozero")
    fig.update_yaxes(title_text="concentration [cm⁻³]", type="log",
                     exponentformat="power")
    return fig


def iv_figures(v: Sequence[float], i: Sequence[float], *, theme: str = "light",
               x_label: str = "V [V]", y_label: str = "I [A/cm]",
               title: str = "", vth: Optional[float] = None):
    """Two figures for one sweep: linear current, and |current| on a log
    axis. Separate charts rather than one chart with two y-axes."""
    go = _go()
    ink = INK[theme]
    v = np.asarray(v, dtype=float)
    i = np.asarray(i, dtype=float)
    color = CATEGORICAL[theme][0]
    name, unit = (y_label.split(" [", 1) + [""])[:2]
    log_label = f"|{name}|" + (f" [{unit}" if unit else "")
    figs = []
    for log in (False, True):
        y = np.abs(i) if log else i
        fig = go.Figure(go.Scatter(
            x=v, y=y, mode="lines", line=dict(color=color, width=2),
            name=y_label, hovertemplate=f"%{{x:.3f}} V · %{{y:.3e}}<extra></extra>"))
        if vth is not None:
            fig.add_vline(x=vth, line=dict(color=ink["secondary"], width=1, dash="dot"),
                          annotation_text=f"Vth {vth:.3f} V",
                          annotation_font=dict(color=ink["secondary"], size=11))
        sub = "log |I|" if log else "linear"
        fig.update_layout(**_layout(theme, f"{title} — {sub}" if title else sub,
                                    height=320), hovermode="x unified",
                          showlegend=False)
        fig.update_xaxes(title_text=x_label)
        fig.update_yaxes(title_text=log_label if log else y_label,
                         type="log" if log else "linear",
                         exponentformat="power" if log else "e")
        figs.append(fig)
    return figs[0], figs[1]


def metric_figure(xs: Sequence[float], ys: Sequence[Optional[float]], *,
                  theme: str = "light", x_label: str = "", y_label: str = "",
                  title: str = ""):
    """One sweep metric against the swept value (points joined by a line;
    missing values leave a gap)."""
    go = _go()
    ink = INK[theme]
    y = [np.nan if v is None else float(v) for v in ys]
    fig = go.Figure(go.Scatter(
        x=list(xs), y=y, mode="lines+markers",
        line=dict(color=CATEGORICAL[theme][0], width=2),
        marker=dict(size=8, color=CATEGORICAL[theme][0],
                    line=dict(color=ink["surface"], width=2)),
        hovertemplate=f"{x_label} %{{x}}<br>{y_label} %{{y:.4g}}<extra></extra>"))
    fig.update_layout(**_layout(theme, title or y_label, height=300),
                      showlegend=False)
    fig.update_xaxes(title_text=x_label)
    fig.update_yaxes(title_text=y_label)
    return fig
