"""
opentcad.viz.palette — colours for OpenTCAD figures, light and dark.

The categorical slots, the blue sequential ramp, the gray diverging
midpoint and the chart ink/surface tokens are the validated reference
palette of the data-viz method we follow. The red arm of the diverging
scale is derived here: each step has the same OKLCH lightness and chroma
as the blue step it mirrors, at the reference red's hue (24.9°), so the
two arms read as equal magnitudes. ``oklch`` lets tests re-check that.

Colour by job:
  * categorical — identity (materials, dopant species, separate curves);
    fixed slot per entity, never cycled.
  * sequential  — magnitude (carrier density, |field|, a swept value).
  * diverging   — sign (net doping: p-type blue, n-type red; gray = ~0).
"""
from __future__ import annotations

import numpy as np

from opentcad.geometry.formats import Material

CATEGORICAL = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "dark":  ["#3987e5", "#d95926", "#199e70", "#c98500",
              "#d55181", "#008300", "#9085e9", "#e66767"],
}

BLUE = {100: "#cde2fb", 150: "#b7d3f6", 200: "#9ec5f4", 250: "#86b6ef",
        300: "#6da7ec", 350: "#5598e7", 400: "#3987e5", 450: "#2a78d6",
        500: "#256abf", 550: "#1c5cab", 600: "#184f95", 650: "#104281",
        700: "#0d366b"}

#: Red arm of the diverging scale, lightness/chroma-matched to BLUE.
RED = {200: "#f1aea8", 300: "#e4857e", 400: "#d75853", 500: "#b13f3c",
       600: "#892b2a"}

NEUTRAL = {"light": "#f0efec", "dark": "#383835"}

INK = {
    "light": {"surface": "#fcfcfb", "page": "#f9f9f7", "primary": "#0b0b0b",
              "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)"},
    "dark":  {"surface": "#1a1a19", "page": "#0d0d0d", "primary": "#f0efec",
              "secondary": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
              "axis": "#383835", "border": "rgba(255,255,255,0.10)"},
}

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

#: Fixed slot per material (colour follows the material in every figure).
MATERIAL_SLOT = {
    Material.SI: 0, Material.SIO2: 1, Material.SI3N4: 2, Material.POLY_SI: 3,
    Material.AL: 4, Material.SIGE: 5, Material.PHOTORESIST: 6, Material.GAN: 7,
}

#: Fixed slot per dopant species; unknown species continue after these.
SPECIES_ORDER = ["boron", "arsenic", "phosphorus"]


def _mode(theme: str) -> str:
    if theme not in ("light", "dark"):
        raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
    return theme


def material_color(material: Material, theme: str = "light") -> str:
    """Fill colour for a material; materials past the 8 slots share muted ink."""
    slot = MATERIAL_SLOT.get(Material(material))
    if slot is None:
        return INK[_mode(theme)]["muted"]
    return CATEGORICAL[_mode(theme)][slot]


def species_color(species: str, theme: str = "light",
                  known: list[str] | None = None) -> str:
    """Line colour for a dopant species, fixed per species."""
    order = SPECIES_ORDER + sorted(s for s in (known or [])
                                   if s not in SPECIES_ORDER)
    slots = CATEGORICAL[_mode(theme)]
    idx = order.index(species) if species in order else len(order)
    return slots[idx] if idx < len(slots) else INK[theme]["muted"]


def diverging_colorscale(theme: str = "light") -> list:
    """Plotly colorscale for signed data: p/negative = blue, n/positive =
    red, gray at zero. In dark mode the arms brighten away from the
    (dark) midpoint so near-zero recedes into the surface."""
    steps = [600, 500, 400, 300, 200]
    if _mode(theme) == "dark":
        steps = steps[::-1]
    neg = [BLUE[s] for s in steps]
    pos = [RED[s] for s in steps[::-1]]
    colors = neg + [NEUTRAL[theme]] + pos
    n = len(colors) - 1
    return [[i / n, c] for i, c in enumerate(colors)]


def sequential_colorscale(theme: str = "light") -> list:
    """Plotly colorscale for magnitude: light→dark blue on a light surface,
    dark→light on a dark one."""
    steps = [100, 200, 300, 400, 500, 600, 700]
    colors = [BLUE[s] for s in steps]
    if _mode(theme) == "dark":
        colors = colors[::-1]
    n = len(colors) - 1
    return [[i / n, c] for i, c in enumerate(colors)]


# ---- colour science (for tests and future palette work) -----------------------
_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def oklch(hex_color: str) -> tuple[float, float, float]:
    """(L, C, h°) of an sRGB hex colour in OKLCH."""
    h = hex_color.lstrip("#")
    rgb = np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    L, a, b = _M2 @ np.cbrt(_M1 @ lin)
    return float(L), float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)) % 360)
