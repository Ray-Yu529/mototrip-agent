from backend.core.export import build_gpx, build_ics

SAMPLE_ITINERARY = [{
    "day": 1,
    "date": "2026-07-10",
    "stops": [
        {"time": "09:00", "place": "清境農場", "type": "景點", "note": "看羊咩咩",
         "lat": 24.05, "lon": 121.15},
        {"time": "12:00", "place": "無座標小吃", "type": "餐廳", "note": "沒查到座標"},
    ],
    "route": {"distance_km": 12.3, "duration_min": 25,
              "geometry": [[121.15, 24.05], [121.16, 24.06]]},
}]


def test_build_gpx_includes_waypoints_with_coords_only():
    gpx = build_gpx(SAMPLE_ITINERARY, theme="測試行程")
    assert "<gpx" in gpx
    assert gpx.count("<wpt ") == 1  # 只有一個 stop 有座標
    assert "清境農場" in gpx
    assert "無座標小吃" not in gpx  # 沒座標的不會變成 waypoint


def test_build_gpx_includes_track_from_route_geometry():
    gpx = build_gpx(SAMPLE_ITINERARY, theme="測試行程")
    assert "<trk>" in gpx
    assert gpx.count("<trkpt ") == 2


def test_build_ics_creates_valid_vevent_per_stop():
    ics = build_ics(SAMPLE_ITINERARY, theme="測試行程")
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20260710T090000" in ics
    assert "DTEND:20260710T093000" in ics
    assert "清境農場" in ics


def test_build_ics_skips_stops_with_invalid_time():
    itinerary = [{"day": 1, "date": "2026-07-10",
                  "stops": [{"time": "", "place": "無時間"}]}]
    ics = build_ics(itinerary)
    assert "BEGIN:VEVENT" not in ics
