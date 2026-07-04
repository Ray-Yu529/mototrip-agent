from backend.agents.gas_agent import _haversine_km, _sample_points


def test_haversine_km_known_distance():
    # 台北車站 → 台中車站，實際約 140km 直線距離
    taipei = (25.0478, 121.5170)
    taichung = (24.1367, 120.6844)
    dist = _haversine_km(taipei, taichung)
    assert 130 < dist < 150


def test_haversine_km_zero_for_same_point():
    p = (24.0, 121.0)
    assert _haversine_km(p, p) == 0


def test_sample_points_covers_full_route():
    # 簡單直線幾何：10 個點，緯度遞增（geometry 格式為 [lon, lat]）
    geometry = [[121.0, 24.0 + i * 0.01] for i in range(10)]
    samples = _sample_points(geometry)
    assert len(samples) >= 2
    # 第一個抽樣點應接近起點，最後一個應接近終點（抽樣點落在頂點上，非線性內插，容許 1 個間距的誤差）
    assert samples[0][2] == 0.0
    assert abs(samples[-1][0] - geometry[-1][1]) <= 0.011


def test_sample_points_empty_geometry():
    assert _sample_points([]) == []
    assert _sample_points([[121.0, 24.0]]) == []
