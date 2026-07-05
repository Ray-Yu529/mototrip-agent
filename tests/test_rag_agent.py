from backend.agents.rag_agent import _resolve_lodging_name


def test_resolve_exact_match():
    names = ["合歡山雲端小屋", "清境農場民宿"]
    assert _resolve_lodging_name("合歡山雲端小屋", names) == "合歡山雲端小屋"


def test_resolve_substring_single_hit():
    names = ["合歡山雲端小屋", "清境農場民宿"]
    assert _resolve_lodging_name("雲端小屋", names) == "合歡山雲端小屋"


def test_resolve_substring_multiple_hits_picks_shortest():
    names = ["清境農場", "清境農場民宿A館"]
    assert _resolve_lodging_name("清境農場", names) == "清境農場"


def test_resolve_fuzzy_match_within_cutoff():
    names = ["合歡山雲端小屋"]
    assert _resolve_lodging_name("合歡山雲端小舍", names) == "合歡山雲端小屋"


def test_resolve_no_match_below_cutoff_returns_none():
    names = ["合歡山雲端小屋", "清境農場民宿"]
    assert _resolve_lodging_name("完全不相關的名字", names) is None


def test_resolve_empty_input_returns_none():
    assert _resolve_lodging_name("", ["合歡山雲端小屋"]) is None
    assert _resolve_lodging_name("   ", ["合歡山雲端小屋"]) is None


def test_resolve_empty_names_list_returns_none():
    assert _resolve_lodging_name("任何名字", []) is None
