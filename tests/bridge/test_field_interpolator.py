"""Tests for doping field interpolation. Key criterion: junction depth within 5%."""
import numpy as np
import pytest
from opentcad.bridge.field_interpolator import (
    _find_junction_nodes, _points_near_set, interpolate_doping_field)


def make_gaussian_1d(n_src=200, n_dst=500):
    y_src = np.linspace(0, 0.5, n_src)
    src_pts = np.column_stack([np.zeros(n_src), y_src])
    peak, sigma, Rp = 1e19, 0.05, 0.01
    Nd = peak * np.exp(-0.5 * ((y_src - Rp) / sigma) ** 2)
    Na = np.full(n_src, 1e15)
    y_dst = np.linspace(0, 0.5, n_dst)
    dst_pts = np.column_stack([np.zeros(n_dst), y_dst])
    y_j = Rp + sigma * np.sqrt(2 * np.log(peak / 1e15))
    return src_pts, Nd, Na, dst_pts, y_j


def find_junction_depth(pts, nd, na):
    net = nd - na
    y = pts[:, 1]
    sc = np.where(np.diff(np.sign(net)))[0]
    if len(sc) == 0: return None
    i = sc[0]
    return y[i] + (y[i+1]-y[i]) * (-net[i]) / (net[i+1]-net[i])


def test_junction_depth_preserved():
    """Phase 2 exit criterion: junction depth within 5% after interpolation."""
    src_pts, Nd, Na, dst_pts, y_j_true = make_gaussian_1d()
    dst_nd, dst_na = interpolate_doping_field(src_pts, Nd, Na, dst_pts)
    y_j_interp = find_junction_depth(dst_pts, dst_nd, dst_na)
    assert y_j_interp is not None
    err = abs(y_j_interp - y_j_true) / y_j_true
    assert err < 0.05, f"Junction depth error {err:.1%} > 5%: true={y_j_true:.4f}, got={y_j_interp:.4f}"

def test_no_negative_concentrations():
    src_pts, Nd, Na, dst_pts, _ = make_gaussian_1d()
    dst_nd, dst_na = interpolate_doping_field(src_pts, Nd, Na, dst_pts)
    assert np.all(dst_nd >= 0)
    assert np.all(dst_na >= 0)

def test_uniform_doping_preserved():
    n = 100
    y = np.linspace(0, 1, n)
    src = np.column_stack([np.zeros(n), y])
    dst = np.column_stack([np.zeros(200), np.linspace(0,1,200)])
    nd, na = interpolate_doping_field(src, np.full(n,1e16), np.full(n,1e15), dst)
    np.testing.assert_allclose(nd, 1e16, rtol=0.01)
    np.testing.assert_allclose(na, 1e15, rtol=0.01)

def test_empty_junction_nodes_uniform():
    n = 50
    pts = np.random.rand(n, 2)
    net = np.full(n, 1e16)
    jn = _find_junction_nodes(pts, net)
    assert len(jn) == 0

def test_points_near_empty_ref():
    query = np.array([[0.,0.],[1.,0.]])
    mask = _points_near_set(query, np.empty((0,2)), 1.0)
    assert not np.any(mask)
