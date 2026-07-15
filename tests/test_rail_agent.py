"""rail_agent 純邏輯測試：站名比對、時刻表/票價/即時看板解析（不需 API key 或網路）。"""
from backend.agents.rail_agent import (
    normalize_station_name,
    match_station,
    suggest_stations,
    parse_od_trains,
    parse_od_fares,
    parse_liveboard,
    find_station_for_city,
    select_leg_trains,
    _parse_stations,
    _duration_min,
    _MOCK_STATIONS,
)


# ── 站名正規化與比對 ─────────────────────────────────────────────────────

def test_normalize_station_name():
    assert normalize_station_name("台北車站") == "臺北"
    assert normalize_station_name("臺北火車站") == "臺北"
    assert normalize_station_name("台中") == "臺中"
    assert normalize_station_name(" 花蓮 ") == "花蓮"
    # 單字「站」不會被剝成空字串
    assert normalize_station_name("站") == "站"


def test_match_station_exact_and_alias():
    assert match_station("臺北", _MOCK_STATIONS)["id"] == "1000"
    assert match_station("台北", _MOCK_STATIONS)["id"] == "1000"       # 台→臺
    assert match_station("台北車站", _MOCK_STATIONS)["id"] == "1000"   # 去字尾
    assert match_station("高雄", _MOCK_STATIONS)["id"] == "4400"


def test_match_station_unique_substring():
    # 「瑞芳」是唯一含「瑞」的 mock 車站 → 子字串唯一命中
    assert match_station("瑞", _MOCK_STATIONS)["id"] == "7360"


def test_match_station_not_found_gives_suggestions():
    assert match_station("不存在站", _MOCK_STATIONS) is None
    assert match_station("", _MOCK_STATIONS) is None
    # 「臺」開頭有多站（臺北/臺中/臺南/臺東）→ 模糊不猜，回 None 由建議清單處理
    assert match_station("臺", _MOCK_STATIONS) is None
    sugg = suggest_stations("臺", _MOCK_STATIONS)
    assert "臺北" in sugg and len(sugg) <= 5


# ── 車站清單解析 ─────────────────────────────────────────────────────────

def test_parse_stations_v3_wrapper_and_bare_list():
    payload = {"Stations": [{
        "StationID": "1000",
        "StationName": {"Zh_tw": "臺北", "En": "Taipei"},
        "StationPosition": {"PositionLat": 25.04, "PositionLon": 121.51},
    }]}
    parsed = _parse_stations(payload)
    assert parsed == [{"id": "1000", "name": "臺北", "name_en": "Taipei",
                       "lat": 25.04, "lon": 121.51}]
    # v2 式裸陣列也能解析
    assert _parse_stations(payload["Stations"])[0]["id"] == "1000"
    # 缺 ID 或名稱的髒資料會被濾掉
    assert _parse_stations({"Stations": [{"StationID": "", "StationName": {}}]}) == []


# ── 時刻表解析 ───────────────────────────────────────────────────────────

def _tt(train_no: str, ttype: str, dep: str, arr: str, bike: int = 0) -> dict:
    return {
        "TrainInfo": {
            "TrainNo": train_no, "Direction": 0, "BikeFlag": bike,
            "TrainTypeName": {"Zh_tw": ttype},
        },
        "StopTimes": [
            {"StopSequence": 1, "StationID": "1000",
             "ArrivalTime": dep, "DepartureTime": dep},
            {"StopSequence": 2, "StationID": "7000",
             "ArrivalTime": arr, "DepartureTime": arr},
        ],
    }


def test_parse_od_trains_sorted_and_duration():
    payload = {"TrainTimetables": [
        _tt("426", "莒光", "10:35", "14:02"),
        _tt("402", "自強(3000)", "06:20", "08:25", bike=1),
    ]}
    trains = parse_od_trains(payload)
    assert [t["train_no"] for t in trains] == ["402", "426"]  # 依出發時間排序
    assert trains[0]["duration_min"] == 125
    assert trains[0]["bike_allowed"] is True
    assert trains[1]["duration_min"] == 207
    assert trains[0]["direction"] == "順行（南下）"


def test_parse_od_trains_overnight_and_dirty_data():
    payload = {"TrainTimetables": [
        _tt("501", "區間", "23:50", "00:40"),          # 跨日
        {"TrainInfo": {"TrainNo": "X"}, "StopTimes": []},  # 缺停靠站 → 跳過
    ]}
    trains = parse_od_trains(payload)
    assert len(trains) == 1
    assert trains[0]["duration_min"] == 50


def test_duration_min_invalid():
    assert _duration_min("", "08:00") is None
    assert _duration_min("ab:cd", "08:00") is None


# ── 票價解析 ─────────────────────────────────────────────────────────────

def _od(direction: int, train_type: int, adult: int, child: int, dist: float) -> dict:
    return {
        "Direction": direction, "TrainType": train_type, "TravelDistance": dist,
        "Fares": [
            {"TicketType": 1, "FareClass": 1, "Price": adult},
            {"TicketType": 1, "FareClass": 3, "Price": child},
            {"TicketType": 3, "FareClass": 1, "Price": adult - 10},  # 電子票證 → 不列入
        ],
    }


def test_parse_od_fares_short_direction_and_grouping():
    payload = {"ODFares": [
        # 順行（短程 194km）：自強級三車種同價 → 合併一列；區間較便宜
        _od(0, 3, 583, 292, 194.3),    # 自強
        _od(0, 1, 583, 292, 194.3),    # 太魯閣（同價 → 併入自強那列）
        _od(0, 6, 376, 188, 194.3),    # 區間
        # 逆行（環島繞遠路 900km）→ 整組捨棄
        _od(1, 3, 1676, 838, 900.1),
    ]}
    fares = parse_od_fares(payload)
    assert len(fares) == 2
    assert fares[0]["adult"] == 583                      # 票價由高至低
    assert set(fares[0]["train_types"]) == {"自強", "太魯閣"}
    assert fares[1] == {"train_types": ["區間"], "adult": 376, "child": 188}
    # 繞遠路方向的 1676 不應出現
    assert all(f["adult"] < 1000 for f in fares)


def test_parse_od_fares_empty():
    assert parse_od_fares({}) == []


# ── 行程整合：城市 → 車站、班次抽樣 ─────────────────────────────────────

def test_find_station_for_city():
    assert find_station_for_city("台中市", _MOCK_STATIONS)["id"] == "3300"  # 去「市」
    assert find_station_for_city("花蓮", _MOCK_STATIONS)["id"] == "7000"    # 直接命中
    assert find_station_for_city("宜蘭縣", _MOCK_STATIONS)["id"] == "7190"  # 去「縣」
    assert find_station_for_city("仁愛鄉", _MOCK_STATIONS) is None          # 山區無台鐵
    assert find_station_for_city("南投縣", _MOCK_STATIONS) is None


def _train(dep: str) -> dict:
    return {"train_no": dep.replace(":", ""), "departure": dep, "arrival": "23:59"}


def test_select_leg_trains_spread_and_filter():
    trains = [_train(f"{h:02d}:00") for h in range(5, 22)]  # 05:00–21:00 每小時一班
    picked = select_leg_trains(trains, limit=5)
    assert len(picked) == 5
    assert picked[0]["departure"] == "06:00"        # 05:00 摸黑班次被濾掉
    assert picked[-1]["departure"] == "21:00"       # 首尾保留，中間等距
    deps = [t["departure"] for t in picked]
    assert deps == sorted(deps)

    # 班次數不足 limit 時全數保留
    few = [_train("08:00"), _train("14:00")]
    assert select_leg_trains(few, limit=5) == few

    # 全部都是清晨班次時不至於回空
    early = [_train("04:30"), _train("05:10")]
    assert select_leg_trains(early, limit=5) == early


# ── 即時看板解析 ─────────────────────────────────────────────────────────

def test_parse_liveboard_delay_and_sort():
    # 欄位名以 TDX 實際回傳為準（ScheduleArrivalTime，無 d）
    payload = {"StationLiveBoards": [
        {"TrainNo": "4028", "Direction": 1, "DelayTime": 6,
         "TrainTypeName": {"Zh_tw": "區間"},
         "EndingStationName": {"Zh_tw": "基隆"}, "Platform": "1",
         "ScheduleArrivalTime": "13:18:00", "ScheduleDepartureTime": "13:20:00"},
        {"TrainNo": "152", "Direction": 0, "DelayTime": 0,
         "TrainTypeName": {"Zh_tw": "自強(3000)"},
         "EndingStationName": {"Zh_tw": "屏東"}, "Platform": "2",
         "ScheduleArrivalTime": "13:10:00", "ScheduleDepartureTime": "13:12:00"},
    ]}
    boards = parse_liveboard(payload)
    assert [b["train_no"] for b in boards] == ["152", "4028"]  # 依到站時間排序
    assert boards[0]["status"] == "準點"
    assert boards[1]["status"] == "晚 6 分"
    assert boards[1]["delay_min"] == 6
    assert boards[0]["scheduled_arrival"] == "13:10"  # HH:MM:SS → HH:MM
    assert boards[0]["platform"] == "2"


def test_parse_liveboard_accepts_scheduled_spelling():
    # 容錯：文件舊拼法 ScheduledArrivalTime 也接受
    boards = parse_liveboard({"StationLiveBoards": [
        {"TrainNo": "1", "DelayTime": 0,
         "ScheduledArrivalTime": "09:00:00", "ScheduledDepartureTime": "09:02:00"},
    ]})
    assert boards[0]["scheduled_arrival"] == "09:00"
    assert boards[0]["scheduled_departure"] == "09:02"


def test_parse_liveboard_tolerates_missing_fields():
    boards = parse_liveboard({"StationLiveBoards": [{"TrainNo": "999", "DelayTime": None}]})
    assert boards[0]["delay_min"] == 0
    assert boards[0]["status"] == "準點"
    assert parse_liveboard([]) == []
