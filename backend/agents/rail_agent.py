"""
Rail Agent — TDX 運輸資料流通服務 台鐵（TRA）查詢，無 LLM。

TDX（https://tdx.transportdata.tw/）為交通部整合公共運輸資料的官方平台
（前身 PTX 已於 2022 年底停止服務）。本模組使用台鐵 v3 API：

- 車站基本資料（/v3/Rail/TRA/Station）
- 指定日期起訖站時刻表（/v3/Rail/TRA/DailyTrainTimetable/OD/{起}/to/{訖}/{日期}）
- 起訖站票價（/v3/Rail/TRA/ODFare/...）
- 車站即時到離站看板含誤點分鐘數（/v3/Rail/TRA/StationLiveBoard，約 2 分鐘延遲）

認證：OAuth2 client credentials，token 有效約 1 天，模組內快取自動換發。
TDX 已不開放匿名呼叫（實測回 401），未設定 TDX_CLIENT_ID/SECRET 或呼叫失敗時
fallback 到 mock 資料，與 weather_agent 慣例一致。
"""
import asyncio
import time
from datetime import date, datetime
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ..core.config import settings

TDX_TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_API_BASE = "https://tdx.transportdata.tw/api/basic"

DIRECTION_LABELS = {0: "順行（南下）", 1: "逆行（北上）"}
# ODFare 的 TrainType 車種代碼（同費率車種會在輸出時合併，個別代碼標錯不影響結果）
FARE_TRAIN_TYPE_LABELS = {
    0: "不分車種", 1: "太魯閣", 2: "普悠瑪", 3: "自強", 4: "莒光",
    5: "復興", 6: "區間", 7: "普快", 10: "區間快", 11: "自強(3000)",
}

# 車站清單一天內不會變動，快取避免每次查詢都重抓 240+ 站
_STATIONS_TTL_S = 24 * 3600

_network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)

_client: httpx.AsyncClient | None = None
_token: dict = {"access_token": "", "expires_at": 0.0}
_stations_cache: dict = {"stations": None, "fetched_at": 0.0}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15)
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ── 認證 ────────────────────────────────────────────────────────────────

def _has_credentials() -> bool:
    return bool(settings.tdx_client_id and settings.tdx_client_secret)


async def _get_access_token() -> str:
    """取得（快取的）TDX access token；未設定金鑰時回傳空字串（呼叫端應先檢查）。"""
    if not _has_credentials():
        return ""
    # 提前 2 分鐘視為過期，避免在邊界上拿到剛失效的 token
    if _token["access_token"] and time.time() < _token["expires_at"] - 120:
        return _token["access_token"]

    resp = await _get_client().post(
        TDX_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.tdx_client_id,
            "client_secret": settings.tdx_client_secret,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    _token["access_token"] = payload["access_token"]
    _token["expires_at"] = time.time() + payload.get("expires_in", 86400)
    return _token["access_token"]


@_network_retry
async def _tdx_get(path: str, params: dict | None = None) -> dict | list:
    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = await _get_client().get(
        f"{TDX_API_BASE}{path}",
        params={"$format": "JSON", **(params or {})},
        headers=headers,
    )
    if resp.status_code == 401 and token:
        # token 可能被伺服器端提前撤銷，清掉快取換發一次再試
        _token["access_token"] = ""
        token = await _get_access_token()
        resp = await _get_client().get(
            f"{TDX_API_BASE}{path}",
            params={"$format": "JSON", **(params or {})},
            headers={"Authorization": f"Bearer {token}"},
        )
    resp.raise_for_status()
    return resp.json()


# ── 車站基本資料與名稱比對 ──────────────────────────────────────────────

def normalize_station_name(name: str) -> str:
    """去掉『車站/火車站/站』字尾、台→臺，例『台北車站』→『臺北』。"""
    n = name.strip().replace("台", "臺")
    for suffix in ("火車站", "車站", "站"):
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)]
            break
    return n


def match_station(name: str, stations: list[dict]) -> dict | None:
    """名稱 → 車站 dict；先精確比對，再唯一子字串比對，模糊多筆時回 None 由呼叫端給建議。"""
    n = normalize_station_name(name)
    for st in stations:
        if st["name"] == n:
            return st
    partial = [st for st in stations if n and n in st["name"]]
    if len(partial) == 1:
        return partial[0]
    return None


def suggest_stations(name: str, stations: list[dict], limit: int = 5) -> list[str]:
    """比對失敗時給候選站名（子字串命中優先）。"""
    n = normalize_station_name(name)
    hits = [st["name"] for st in stations if n and (n in st["name"] or st["name"] in n)]
    return hits[:limit]


def _parse_stations(data: dict | list) -> list[dict]:
    """TDX v3 回傳 {"Stations": [...]}；容忍 v2 式的裸陣列。"""
    raw = data.get("Stations", []) if isinstance(data, dict) else data
    out = []
    for s in raw:
        out.append({
            "id": s.get("StationID", ""),
            "name": s.get("StationName", {}).get("Zh_tw", ""),
            "name_en": s.get("StationName", {}).get("En", ""),
            "lat": s.get("StationPosition", {}).get("PositionLat"),
            "lon": s.get("StationPosition", {}).get("PositionLon"),
        })
    return [s for s in out if s["id"] and s["name"]]


async def get_stations() -> list[dict]:
    """全台台鐵車站清單（模組內快取 24h）；無金鑰或 TDX 失敗時回 mock 主要車站。"""
    now = time.time()
    if _stations_cache["stations"] and now - _stations_cache["fetched_at"] < _STATIONS_TTL_S:
        return _stations_cache["stations"]
    if not _has_credentials():
        logger.warning("TDX 金鑰未設定，使用內建主要車站清單")
        return _MOCK_STATIONS
    try:
        data = await _tdx_get("/v3/Rail/TRA/Station")
        stations = _parse_stations(data)
        if not stations:
            raise ValueError("TDX 車站清單為空")
        _stations_cache["stations"] = stations
        _stations_cache["fetched_at"] = now
        return stations
    except Exception as exc:
        logger.error(f"TDX 車站清單取得失敗: {exc}，改用內建主要車站清單")
        return _MOCK_STATIONS


async def search_stations(keyword: str) -> dict:
    """關鍵字查車站（前端下拉/確認用）。"""
    stations = await get_stations()
    n = normalize_station_name(keyword)
    hits = [st for st in stations if n in st["name"] or (st["name_en"] and keyword.lower() in st["name_en"].lower())]
    return {"keyword": keyword, "stations": hits[:20]}


# ── 時刻表 + 票價 ───────────────────────────────────────────────────────

def _duration_min(dep: str, arr: str) -> int | None:
    """HH:MM 車程分鐘數；跨日（如 23:50→00:40）自動 +24h。"""
    try:
        d = datetime.strptime(dep[:5], "%H:%M")
        a = datetime.strptime(arr[:5], "%H:%M")
    except ValueError:
        return None
    minutes = int((a - d).total_seconds() // 60)
    return minutes + 24 * 60 if minutes < 0 else minutes


def parse_od_trains(timetable_json: dict) -> list[dict]:
    """把 OD 每日時刻表 JSON 轉成班次清單，依出發時間排序。"""
    trains = []
    for tt in timetable_json.get("TrainTimetables", []):
        info = tt.get("TrainInfo", {})
        stops = tt.get("StopTimes", [])
        if len(stops) < 2:
            continue
        # OD 查詢的 StopTimes 依 StopSequence 排序後，首尾即起訖站
        stops = sorted(stops, key=lambda s: s.get("StopSequence", 0))
        dep = stops[0].get("DepartureTime", "")[:5]
        arr = stops[-1].get("ArrivalTime", "")[:5]
        trains.append({
            "train_no": info.get("TrainNo", ""),
            "train_type": info.get("TrainTypeName", {}).get("Zh_tw", ""),
            "direction": DIRECTION_LABELS.get(info.get("Direction"), ""),
            "departure": dep,
            "arrival": arr,
            "duration_min": _duration_min(dep, arr),
            "bike_allowed": bool(info.get("BikeFlag", 0)),
            "note": info.get("Note", "") or "",
        })
    trains.sort(key=lambda t: t["departure"])
    return trains


def parse_od_fares(fare_json: dict) -> list[dict]:
    """
    整理各車種的成人/孩童一般票（TicketType=1）單程票價。

    同一組起訖站 TDX 會回傳順行/逆行兩個環島方向的票價（繞遠路那個方向
    票價高數倍），取 TravelDistance 較短的方向；同費率車種合併成一列
    （如太魯閣/普悠瑪/自強同價）。票價由高至低排序。
    """
    ods = fare_json.get("ODFares", [])
    if not ods:
        return []

    by_dir: dict[int, list[dict]] = {}
    for od in ods:
        by_dir.setdefault(od.get("Direction", 0), []).append(od)
    if len(by_dir) > 1:
        ods = min(
            by_dir.values(),
            key=lambda entries: min(o.get("TravelDistance") or 1e9 for o in entries),
        )

    groups: dict[tuple, dict] = {}
    for od in ods:
        adult = child = None
        for f in od.get("Fares", []):
            if f.get("TicketType") != 1:
                continue
            if f.get("FareClass") == 1:
                adult = f.get("Price")
            elif f.get("FareClass") == 3:
                child = f.get("Price")
        if adult is None:
            continue
        label = FARE_TRAIN_TYPE_LABELS.get(od.get("TrainType"), f"車種{od.get('TrainType')}")
        g = groups.setdefault((adult, child), {"train_types": [], "adult": adult, "child": child})
        if label not in g["train_types"]:
            g["train_types"].append(label)
    return sorted(groups.values(), key=lambda g: g["adult"], reverse=True)


async def fetch_od_timetable(
    origin: str, destination: str, train_date: str | None = None
) -> dict:
    """起訖站時刻表 + 票價。站名比對失敗回 {"error", "suggestions"}。"""
    train_date = train_date or date.today().isoformat()
    stations = await get_stations()

    o = match_station(origin, stations)
    d = match_station(destination, stations)
    if o is None or d is None:
        missing = origin if o is None else destination
        return {
            "error": f"找不到車站「{missing}」",
            "suggestions": suggest_stations(missing, stations),
        }

    if not _has_credentials():
        logger.warning("TDX 金鑰未設定，時刻表使用 mock 資料")
        return _mock_timetable(o, d, train_date)

    try:
        tt_task = _tdx_get(
            f"/v3/Rail/TRA/DailyTrainTimetable/OD/{o['id']}/to/{d['id']}/{train_date}"
        )
        fare_task = _tdx_get(f"/v3/Rail/TRA/ODFare/{o['id']}/to/{d['id']}")
        tt_json, fare_json = await asyncio.gather(tt_task, fare_task, return_exceptions=True)
        if isinstance(tt_json, Exception):
            raise tt_json
        # 票價查詢失敗不影響時刻表主功能
        if isinstance(fare_json, Exception):
            logger.warning(f"TDX 票價查詢失敗: {fare_json}")
            fare_json = {}
    except Exception as exc:
        logger.error(f"TDX 時刻表查詢失敗（已重試 3 次）: {exc}，改用 mock 資料")
        return _mock_timetable(o, d, train_date)

    return {
        "origin": {"id": o["id"], "name": o["name"]},
        "destination": {"id": d["id"], "name": d["name"]},
        "date": train_date,
        "trains": parse_od_trains(tt_json if isinstance(tt_json, dict) else {}),
        "fares": parse_od_fares(fare_json if isinstance(fare_json, dict) else {}),
        "source": "tdx",
    }


# ── 車站即時看板（Liveboard，約 2 分鐘延遲）─────────────────────────────

def _delay_status(delay_min: int) -> str:
    return "準點" if delay_min <= 0 else f"晚 {delay_min} 分"


def parse_liveboard(liveboard_json: dict | list) -> list[dict]:
    """即時到離站看板 → 班次清單（含誤點分鐘數），依表定到站時間排序。"""
    raw = (
        liveboard_json.get("StationLiveBoards", [])
        if isinstance(liveboard_json, dict) else liveboard_json
    )
    boards = []
    for b in raw:
        delay = int(b.get("DelayTime", 0) or 0)
        boards.append({
            "train_no": b.get("TrainNo", ""),
            "train_type": b.get("TrainTypeName", {}).get("Zh_tw", ""),
            "direction": DIRECTION_LABELS.get(b.get("Direction"), ""),
            "ending_station": b.get("EndingStationName", {}).get("Zh_tw", ""),
            # TDX 實際欄位名是 ScheduleArrivalTime（無 d），保留 Scheduled 拼法容錯
            "scheduled_arrival": (b.get("ScheduleArrivalTime")
                                  or b.get("ScheduledArrivalTime") or "")[:5],
            "scheduled_departure": (b.get("ScheduleDepartureTime")
                                    or b.get("ScheduledDepartureTime") or "")[:5],
            "platform": b.get("Platform", "") or "",
            "delay_min": delay,
            "status": _delay_status(delay),
        })
    boards.sort(key=lambda x: x["scheduled_arrival"] or x["scheduled_departure"])
    return boards


async def fetch_station_liveboard(station: str) -> dict:
    """指定車站的即時到離站動態（TDX 資料約有 2 分鐘延遲）。"""
    stations = await get_stations()
    st = match_station(station, stations)
    if st is None:
        return {
            "error": f"找不到車站「{station}」",
            "suggestions": suggest_stations(station, stations),
        }

    if not _has_credentials():
        logger.warning("TDX 金鑰未設定，即時看板使用 mock 資料")
        return _mock_liveboard(st)

    try:
        data = await _tdx_get(
            "/v3/Rail/TRA/StationLiveBoard",
            params={"$filter": f"StationID eq '{st['id']}'"},
        )
    except Exception as exc:
        logger.error(f"TDX 即時看板查詢失敗（已重試 3 次）: {exc}，改用 mock 資料")
        return _mock_liveboard(st)

    return {
        "station": {"id": st["id"], "name": st["name"]},
        "updated_at": data.get("UpdateTime", "") if isinstance(data, dict) else "",
        "boards": parse_liveboard(data),
        "note": "即時動態約有 2 分鐘延遲",
        "source": "tdx",
    }


# ── 行程規劃整合（大眾運輸模式餵給 LLM 的真實班次）───────────────────────

CITY_SUFFIXES = ("縣", "市", "鄉", "鎮", "區")


def find_station_for_city(city: str, stations: list[dict]) -> dict | None:
    """
    行程的城市名 → 台鐵車站，例『台中市』→ 臺中站、『花蓮』→ 花蓮站。
    去掉縣市鄉鎮字尾後仍找不到（如仁愛鄉、南投縣無台鐵）回 None。
    """
    st = match_station(city, stations)
    if st:
        return st
    n = normalize_station_name(city)
    if n.endswith(CITY_SUFFIXES) and len(n) > 1:
        return match_station(n[:-1], stations)
    return None


def select_leg_trains(trains: list[dict], limit: int = 5) -> list[dict]:
    """
    從全日班次挑分散時段的代表班次控制 prompt 長度：
    以 06:00 後的班次為主（旅遊日不會摸黑趕車），等距抽樣至多 limit 班。
    """
    day = [t for t in trains if t.get("departure", "") >= "06:00"]
    if not day:
        day = trains
    if len(day) <= limit:
        return day
    step = (len(day) - 1) / (limit - 1)
    idxs = sorted({round(i * step) for i in range(limit)})
    return [day[i] for i in idxs]


async def fetch_leg_trains(
    origin_city: str, dest_city: str, train_date: str, limit: int = 5
) -> dict:
    """
    查一段城市間移動的台鐵班次摘要（給 routing LLM 引用真實車次用）。
    任一端無台鐵車站、或查無班次時回 {"leg", "note"}，讓 LLM 改建議客運。
    """
    leg_label = f"{origin_city}→{dest_city}"
    stations = await get_stations()
    o = find_station_for_city(origin_city, stations)
    d = find_station_for_city(dest_city, stations)
    if o is None or d is None or o["id"] == d["id"]:
        return {"leg": leg_label, "note": "無台鐵直達，請改用客運或其他方式"}

    result = await fetch_od_timetable(o["name"], d["name"], train_date)
    if "error" in result:
        return {"leg": leg_label, "note": "台鐵時刻查詢失敗，請用一般大眾運輸描述"}
    trains = select_leg_trains(result.get("trains", []), limit)
    if not trains:
        return {"leg": leg_label, "note": "該日查無台鐵直達班次，請改用客運或轉乘"}

    return {
        "leg": leg_label,
        "date": train_date,
        "from_station": o["name"],
        "to_station": d["name"],
        "trains": [
            {"車次": t["train_no"], "車種": t["train_type"],
             "開": t["departure"], "到": t["arrival"]}
            for t in trains
        ],
        "adult_fares": {
            "／".join(f["train_types"]): f["adult"] for f in result.get("fares", [])
        },
        "source": result.get("source", "tdx"),
    }


# ── Mock 資料（無金鑰且匿名呼叫失敗時的 fallback）───────────────────────

_MOCK_STATIONS: list[dict] = [
    {"id": "1000", "name": "臺北", "name_en": "Taipei", "lat": 25.0478, "lon": 121.5170},
    {"id": "1020", "name": "板橋", "name_en": "Banqiao", "lat": 25.0143, "lon": 121.4632},
    {"id": "1100", "name": "桃園", "name_en": "Taoyuan", "lat": 24.9892, "lon": 121.3133},
    {"id": "1210", "name": "新竹", "name_en": "Hsinchu", "lat": 24.8016, "lon": 120.9714},
    {"id": "3300", "name": "臺中", "name_en": "Taichung", "lat": 24.1369, "lon": 120.6851},
    {"id": "3360", "name": "彰化", "name_en": "Changhua", "lat": 24.0818, "lon": 120.5386},
    {"id": "3470", "name": "嘉義", "name_en": "Chiayi", "lat": 23.4792, "lon": 120.4413},
    {"id": "4220", "name": "臺南", "name_en": "Tainan", "lat": 22.9971, "lon": 120.2128},
    {"id": "4400", "name": "高雄", "name_en": "Kaohsiung", "lat": 22.6394, "lon": 120.3025},
    {"id": "5000", "name": "屏東", "name_en": "Pingtung", "lat": 22.6693, "lon": 120.4862},
    {"id": "6000", "name": "臺東", "name_en": "Taitung", "lat": 22.7937, "lon": 121.1233},
    {"id": "7000", "name": "花蓮", "name_en": "Hualien", "lat": 23.9933, "lon": 121.6011},
    {"id": "7190", "name": "宜蘭", "name_en": "Yilan", "lat": 24.7548, "lon": 121.7581},
    {"id": "7360", "name": "瑞芳", "name_en": "Ruifang", "lat": 25.1088, "lon": 121.8060},
]


def _mock_timetable(o: dict, d: dict, train_date: str) -> dict:
    return {
        "origin": {"id": o["id"], "name": o["name"]},
        "destination": {"id": d["id"], "name": d["name"]},
        "date": train_date,
        "trains": [
            {"train_no": "402", "train_type": "自強(3000)", "direction": DIRECTION_LABELS[0],
             "departure": "06:20", "arrival": "09:05", "duration_min": 165,
             "bike_allowed": False, "note": ""},
            {"train_no": "1150", "train_type": "區間快", "direction": DIRECTION_LABELS[0],
             "departure": "08:10", "arrival": "11:40", "duration_min": 210,
             "bike_allowed": True, "note": ""},
            {"train_no": "426", "train_type": "莒光", "direction": DIRECTION_LABELS[0],
             "departure": "10:35", "arrival": "14:02", "duration_min": 207,
             "bike_allowed": False, "note": ""},
        ],
        "fares": [
            {"train_types": ["自強(3000)", "普悠瑪", "太魯閣"], "adult": 583, "child": 292},
            {"train_types": ["莒光"], "adult": 450, "child": 225},
            {"train_types": ["區間", "區間快"], "adult": 376, "child": 188},
        ],
        "source": "mock",
        "note": "TDX 金鑰未設定或呼叫失敗，此為示範資料",
    }


def _mock_liveboard(st: dict) -> dict:
    return {
        "station": {"id": st["id"], "name": st["name"]},
        "updated_at": "",
        "boards": [
            {"train_no": "152", "train_type": "自強(3000)", "direction": DIRECTION_LABELS[0],
             "ending_station": "屏東", "scheduled_arrival": "13:10",
             "scheduled_departure": "13:12", "platform": "2",
             "delay_min": 0, "status": "準點"},
            {"train_no": "4028", "train_type": "區間", "direction": DIRECTION_LABELS[1],
             "ending_station": "基隆", "scheduled_arrival": "13:18",
             "scheduled_departure": "13:20", "platform": "1",
             "delay_min": 6, "status": "晚 6 分"},
        ],
        "note": "TDX 金鑰未設定或呼叫失敗，此為示範資料",
        "source": "mock",
    }
