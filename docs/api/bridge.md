# Mesh-to-mesh interpolation

Moving doping fields between separate meshes.

This page is generated from the docstrings by `tools/gen_api_docs.py`.

Import from `opentcad.bridge.field_interpolator`: `interpolate_doping_field`.

## interpolate_doping_field

```python
opentcad.bridge.field_interpolator.interpolate_doping_field(
    src_points: np.ndarray,
    src_nd: np.ndarray,
    src_na: np.ndarray,
    dst_points: np.ndarray,
    junction_proximity_um: float = 0.03,
    rbf_neighbors: int = 20,
    rbf_smoothing: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]
```

Interpolate Nd, Na from source mesh to destination mesh.

**Parameters**

- `src_points`: Source coordinates [um], shape (N, 2) or (N, 3)
- `src_nd`: Donor concentration [cm^-3], shape (N,)
- `src_na`: Acceptor concentration [cm^-3], shape (N,)
- `dst_points`: Destination coordinates [um], shape (M, 2) or (M, 3)
- `junction_proximity_um`: Switch to NN within this radius of junction [um]
- `rbf_neighbors`: RBF neighbor count (speed vs accuracy tradeoff)
- `rbf_smoothing`: RBF smoothing (0=exact, small positive for noisy data)

**Returns**

(dst_nd, dst_na) at destination nodes [cm^-3]

[source](https://github.com/abhineet-agarwal/opentcad/blob/main/opentcad/bridge/field_interpolator.py#L17)
