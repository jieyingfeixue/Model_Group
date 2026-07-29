import numpy as np

from tools.build_target_db import _interp_gps_at


def test_interp_gps_at_returns_lat_lon_and_heading():
    ts = np.array([0.0, 10.0])
    lat = np.array([32.0, 34.0])
    lon = np.array([118.0, 120.0])
    ts_h = np.array([0.0, 10.0])
    hdg = np.array([350.0, 10.0])

    out = _interp_gps_at(5.0, ts, lat, lon, ts_h, hdg)

    assert out[0] == 33.0
    assert out[1] == 119.0
    assert min(abs(out[2]), abs(out[2] - 360.0)) < 1e-9
