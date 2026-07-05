import json
from backend.agents.routing_agent import _parse_json_safe, _try_repair_truncated


def test_parse_json_safe_plain_json():
    raw = '{"theme": "hardcore", "total_days": 2}'
    assert _parse_json_safe(raw) == {"theme": "hardcore", "total_days": 2}


def test_parse_json_safe_strips_think_block():
    raw = '<think>先想一下該怎麼排行程...</think>{"theme": "michelin"}'
    assert _parse_json_safe(raw) == {"theme": "michelin"}


def test_parse_json_safe_strips_markdown_fence():
    raw = '```json\n{"theme": "photo"}\n```'
    assert _parse_json_safe(raw) == {"theme": "photo"}


def test_parse_json_safe_extracts_outer_braces_amid_extra_text():
    raw = '這是為您規劃的行程：\n{"theme": "couple"}\n希望您滿意！'
    assert _parse_json_safe(raw) == {"theme": "couple"}


def test_parse_json_safe_repairs_truncated_output():
    # 模擬 max_tokens 不足時，JSON 在第二個 stop 中途被截斷
    raw = (
        '{"theme": "hardcore", "itinerary": [{"day": 1, "stops": ['
        '{"time": "09:00", "place": "清境農場"}, '
        '{"time": "12:00", "place": "廬'  # 被截斷
    )
    result = _parse_json_safe(raw)
    assert "error" not in result
    assert result["theme"] == "hardcore"
    assert len(result["itinerary"][0]["stops"]) == 1
    assert result["itinerary"][0]["stops"][0]["place"] == "清境農場"


def test_parse_json_safe_returns_error_for_non_json():
    raw = "抱歉，我無法完成這個請求。"
    result = _parse_json_safe(raw)
    assert "error" in result
    assert result["raw"].startswith("抱歉")


def test_try_repair_truncated_returns_none_without_opening_brace():
    assert _try_repair_truncated("not json at all") is None


def test_try_repair_truncated_handles_nested_arrays():
    raw = '{"a": [1, 2, {"b": 3}, {"c": 4'
    result = _try_repair_truncated(raw)
    assert result == {"a": [1, 2, {"b": 3}]}


def test_try_repair_truncated_prefers_longest_valid_prefix():
    # 完整的第一個 stop 應保留，第二個未完成的 stop 應被砍掉
    raw = json.dumps({"itinerary": [{"day": 1}, {"day": 2}]})[:-3]
    result = _try_repair_truncated(raw)
    assert result == {"itinerary": [{"day": 1}]}


def test_try_repair_truncated_closes_mixed_nesting_in_correct_order():
    # itinerary（物件）包 stops（陣列）包 stop（物件）的混合巢狀，
    # 補回的收尾括號必須是 ]}]}（後開先關），不能只是統計數量後
    # 先補完所有 ] 再補所有 }（那樣會產生 ]]}} 這種無效 JSON）
    raw = '{"itinerary": [{"day": 1, "stops": [{"place": "A"}], "extra": {"x": 1'
    result = _try_repair_truncated(raw)
    assert result == {"itinerary": [{"day": 1, "stops": [{"place": "A"}]}]}


def test_try_repair_truncated_ignores_brackets_inside_strings():
    # note 欄位內容剛好含有花括號字元時，不應被誤判為結構邊界
    raw = '{"itinerary": [{"day": 1, "note": "彎道多{注意}", "stops": [{"place": "A"}'
    result = _try_repair_truncated(raw)
    assert result["itinerary"][0]["note"] == "彎道多{注意}"
    assert result["itinerary"][0]["stops"] == [{"place": "A"}]
