from backend.core.geocode import _lookup_known_coord


def test_exact_match():
    known = {"清境農場": (24.05, 121.15)}
    assert _lookup_known_coord("清境農場", known) == (24.05, 121.15)


def test_fuzzy_match_when_llm_drops_suffix():
    # LLM 常把「紅河谷步道瀑布」簡寫成「紅河谷步道」
    known = {"紅河谷步道瀑布": (24.1, 121.2)}
    assert _lookup_known_coord("紅河谷步道", known) == (24.1, 121.2)


def test_fuzzy_match_when_google_name_has_seo_stuffing():
    known = {"木匣宴日式定食-南投仁愛清境美食/餐廳/簡餐/風味餐": (24.0, 121.1)}
    assert _lookup_known_coord("木匣宴日式定食", known) == (24.0, 121.1)


def test_no_match_returns_none():
    known = {"清境農場": (24.05, 121.15)}
    assert _lookup_known_coord("完全不相關的地名", known) is None


def test_multiple_fuzzy_hits_picks_shortest():
    # 兩個候選都是查詢字串的子字串時，取較短者（通常最貼近核心名稱）
    known = {"清境農場民宿A": (1.0, 1.0), "清境農場": (2.0, 2.0)}
    assert _lookup_known_coord("清境農場民宿A的房間", known) == (2.0, 2.0)
