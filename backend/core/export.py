"""
行程匯出 — GPX（給導航/地圖 app 匯入）與 ICS（行事曆）。
純字串組裝，不依賴第三方套件，保持依賴精簡。
"""
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

GPX_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="MotoTrip Agent" '
    'xmlns="http://www.topografix.com/GPX/1/1">\n'
)


def build_gpx(itinerary: list[dict], theme: str = "行程") -> str:
    """
    把行程轉成 GPX：每個有座標的 stop 是一個 waypoint，
    每天若有真實路線幾何（routing.py 算出的 route.geometry）則額外輸出一條 track。
    """
    parts = [GPX_HEADER, f"  <metadata><name>{escape(theme)}</name></metadata>\n"]

    for day in itinerary:
        day_num = day.get("day", "")
        for stop in day.get("stops", []):
            lat, lon = stop.get("lat"), stop.get("lon")
            if lat is None or lon is None:
                continue
            name = escape(f"D{day_num} {stop.get('time', '')} {stop.get('place', '')}")
            desc = escape(stop.get("note", "") or stop.get("type", ""))
            parts.append(
                f'  <wpt lat="{lat}" lon="{lon}">\n'
                f"    <name>{name}</name>\n"
                f"    <desc>{desc}</desc>\n"
                f"  </wpt>\n"
            )

        geometry = day.get("route", {}).get("geometry")
        if geometry:
            parts.append(f'  <trk><name>{escape(f"Day {day_num}")}</name><trkseg>\n')
            for lon, lat in geometry:
                parts.append(f'    <trkpt lat="{lat}" lon="{lon}"></trkpt>\n')
            parts.append("  </trkseg></trk>\n")

    parts.append("</gpx>\n")
    return "".join(parts)


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def build_ics(itinerary: list[dict], theme: str = "行程") -> str:
    """把行程轉成 ICS 行事曆，每個 stop 是一個 30 分鐘的事件。"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MotoTrip Agent//itinerary//ZH-TW",
        "CALSCALE:GREGORIAN",
    ]
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for day in itinerary:
        day_date = day.get("date", "")
        for i, stop in enumerate(day.get("stops", [])):
            time_str = stop.get("time", "")
            try:
                start = datetime.strptime(f"{day_date} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            end = start + timedelta(minutes=30)
            uid = f"mototrip-{day.get('day', 0)}-{i}@mototrip-agent"
            summary = _ics_escape(f"{stop.get('type', '')} {stop.get('place', '')}")
            desc_bits = [b for b in (stop.get("transfer", ""), stop.get("note", ""),
                                     stop.get("parking", "")) if b]
            description = _ics_escape(" / ".join(desc_bits))
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
