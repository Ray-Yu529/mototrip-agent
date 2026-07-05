"""
Routing Agent — 唯一的 LLM 呼叫，整合所有資料輸出多日行程 JSON。

備註：曾嘗試改用 LangChain with_structured_output() 取代下方的 JSON 修補邏輯，
但實測目前預設的 NVIDIA 模型（google/diffusiongemma-26b-a4b-it）不支援工具呼叫，
with_structured_output 會靜默回傳 None（無例外、無法 fallback），故保留手動解析
＋截斷修補的做法，這是目前唯一能穩定拿到結果的方式。
"""
import json
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from loguru import logger

from ..core.llm import get_llm, invoke_chain

ITINERARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一位專業的旅遊規劃師。請根據以下資訊，規劃一份完整的多日旅遊行程。\n\n"
        "規則（必須遵守）：\n"
        "1. 所有景點活動安排在 07:00–21:00 之間\n"
        "1b. **三餐不可遺漏**：每個完整旅遊日都要排午餐（約 12:00–13:00）與晚餐"
        "（約 18:00–19:00，type=餐廳），晚餐必須安排在入住住宿之前；多日行程隔天可視情況加早餐\n"
        "2. **各城市天氣是依「日期」分別提供的（key 為 YYYY-MM-DD）**，"
        "請依每個 stop 實際所在日期讀取對應天氣，"
        "該日午後（12:00–15:00）降雨風險高（rain_risk_pct 高）時，優先安排 venue=indoor 的室內地點\n"
        "3. 依照交通方式調整每段移動時間與景點密度\n"
        "4. 多日行程每天都要有住宿安排（最後一天除外）\n"
        "5. **餐廳與景點請優先從「推薦景點／餐廳」清單中挑選**，不要自行虛構不存在的店家\n"
        "6. **若有多個途經城市，請依城市順序把總天數合理分配**，"
        "每個城市停留 1 天以上，景點挑該城市清單中的（poi 的 city 欄位標示所屬城市）\n"
        "7. 每個 stop 請加上 city 欄位標示所在城市\n"
        "8. 遵守使用者偏好（見下方偏好設定）\n"
        "9. **transfer 欄位**：描述「從上一站移動到本站」的方式，須符合交通方式：\n"
        "   - 大眾運輸：寫出**具體班次/路線**（例：「搭台鐵區間車至○○站，轉○○客運往△△，約50分鐘」）\n"
        "   - 機車/重機/自行車：寫主要路線與預估時間（例：「台14甲線往合歡山，約40分鐘」）\n"
        "   - 汽車：寫主要道路與預估車程\n"
        "   每天第一站的 transfer 寫「行程起點」即可\n"
        "10. **parking 欄位**：交通方式為汽車/機車/重機時，為每個停留點建議停車地點"
        "（停車場名稱或路邊收費資訊；重機請註明是否有機車格）；大眾運輸/自行車則填空字串\n"
        "11. **options 欄位**：僅「餐廳」與「景點」類型需要，從清單中挑 2–3 個同性質候選（依清單可用數量），"
        "讓使用者自行選擇；每個候選含 place/note/rating。place 欄位放你最推薦的那一個（即 options 的第一個）\n"
        "12. 輸出**純 JSON**，不要加 markdown 或說明文字\n\n"
        "輸出格式：\n"
        '{{"theme": "主題", "transport": "交通方式", "total_days": 天數, '
        '"itinerary": ['
        '{{"day": 1, "date": "YYYY-MM-DD", "city": "當天主要城市", "stops": ['
        '{{"time": "HH:MM", "place": "名稱", "city": "城市", "type": "餐廳/景點/住宿/加油站/補給", '
        '"note": "備註", "transfer": "從上一站到這裡的移動方式", "parking": "停車建議（開車/騎車時填，否則空字串）", '
        '"options": [{{"place": "候選名稱", "note": "特色備註", "rating": 4.5}}]}}'
        ']}}, ...'
        '], "survival_tips": ["小提醒1", "小提醒2"]}}'
    )),
    ("human", (
        "旅遊主題：{theme}\n"
        "交通方式：{transport}（{transport_note}）\n"
        "出發地：{origin}\n"
        "途經城市（依序）：{cities}\n"
        "出發日期：{start_date}，共 {days} 天\n"
        "偏好設定：{preferences_note}\n\n"
        "各城市天氣：\n{weather_by_city}\n\n"
        "推薦景點／餐廳（含 city 城市 + venue 室內外標記）：\n{poi_list}\n\n"
        "住宿防雷分析：\n{lodging_info}"
    )),
])


async def generate_itinerary(
    theme: str,
    origin: str,
    destination: str,
    cities: list[str],
    weather_by_city: dict,
    start_date: str,
    days: int,
    transport: str,
    transport_note: str,
    weather_info: dict,
    poi_list: list[dict],
    lodging_info: dict,
    preferences_note: str = "無特別偏好",
) -> dict:
    chain = ITINERARY_PROMPT | get_llm() | StrOutputParser()

    try:
        raw = await invoke_chain(chain, {
            "theme": theme,
            "transport": transport,
            "transport_note": transport_note,
            "origin": origin,
            "cities": " → ".join(cities),
            "start_date": start_date,
            "days": days,
            "preferences_note": preferences_note,
            "weather_by_city": json.dumps(weather_by_city, ensure_ascii=False, separators=(",", ":")),
            "poi_list": json.dumps(poi_list, ensure_ascii=False, separators=(",", ":")),
            "lodging_info": json.dumps(lodging_info, ensure_ascii=False, separators=(",", ":")),
        })
    except Exception as exc:
        logger.error(f"行程生成 LLM 呼叫失敗（已重試）: {exc}")
        return {"error": f"行程生成失敗，LLM 服務暫時無法連線：{exc}"}

    return _parse_json_safe(raw)


ADJUST_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一位專業的旅遊規劃師。使用者已經有一份完整的多日行程（JSON），"
        "現在要根據他的修改指令調整行程。\n\n"
        "規則：\n"
        "1. 盡量只修改使用者要求的部分，其餘天數/stops 維持原樣不要無故更動\n"
        "2. 修改後仍要遵守：三餐不遺漏、時間在 07:00–21:00、"
        "每天都有住宿安排（最後一天除外）、stop 需含 city/type/transfer/parking/options 等既有欄位\n"
        "3. 若使用者要求移除某個景點/餐廳，需視情況補上鄰近的替代選項或調整時間銜接\n"
        "4. 輸出**純 JSON**，格式與輸入的原始行程 JSON 完全相同（同樣的 key 結構），不要加 markdown\n"
    )),
    ("human", (
        "原始行程 JSON：\n{itinerary_json}\n\n"
        "修改指令：{instruction}"
    )),
])


async def adjust_itinerary(itinerary: dict, instruction: str) -> dict:
    """對話式行程微調：既有行程 + 一句話指令 → 修改後的行程 JSON（額外 1 次 LLM 呼叫）。"""
    chain = ADJUST_PROMPT | get_llm() | StrOutputParser()
    try:
        raw = await invoke_chain(chain, {
            "itinerary_json": json.dumps(itinerary, ensure_ascii=False, separators=(",", ":")),
            "instruction": instruction,
        })
    except Exception as exc:
        logger.error(f"行程微調 LLM 呼叫失敗（已重試）: {exc}")
        return {"error": f"行程微調失敗，LLM 服務暫時無法連線：{exc}"}
    return _parse_json_safe(raw)


def _parse_json_safe(raw: str) -> dict:
    logger.debug(f"LLM 原始輸出（前 300 字）: {raw[:300]}")

    # 1. 剝掉 DiffusionGemma 的 <think>...</think> 思考區塊
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)

    # 2. 剝掉 markdown code fence
    cleaned = re.sub(r"```(?:json)?|```", "", cleaned).strip()

    # 3. 收斂模型偶爾輸出的雙大括號 {{ }}
    if cleaned.startswith("{{"):
        cleaned = cleaned[1:]
    if cleaned.endswith("}}"):
        cleaned = cleaned[:-1]

    # 4. 直接 parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 5. 找最外層的 { ... }
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 6. JSON 被截斷（max_tokens 不足）時，嘗試補回未閉合的括號
    repaired = _try_repair_truncated(cleaned)
    if repaired is not None:
        return repaired

    logger.warning(f"Routing LLM 輸出非 JSON，完整內容: {raw}")
    return {"error": "行程生成失敗，請重試（可能因內容過長被截斷）", "raw": raw[:500]}


def _try_repair_truncated(text: str) -> dict | None:
    """
    JSON 被截斷時，砍到最後一個完整巢狀結構並補上閉合括號。

    用堆疊追蹤目前開啟的括號「順序」，收尾時依「後開先關」補上正確的
    }/] 序列 —— 若只是統計數量後「先補完所有 ] 再補所有 }」
    （曾經的實作方式），像本專案 itinerary（物件）包 stops（陣列）包
    stop（物件）這種混合巢狀，補出來的括號順序會是錯的，導致 json.loads
    直接失敗、白白重試。同時略過字串內容中的括號字元，避免 note 等欄位
    剛好含有 {}[] 時誤判結構邊界。
    只在字元為 `}` 或 `]`（可能的完整結構收尾點）嘗試候選，
    比起「每個字元位置都嘗試」大幅減少候選數與逐位重新掃描的開銷。
    """
    start = text.find("{")
    if start < 0:
        return None
    snippet = text[start:]

    stack: list[str] = []          # 依開啟順序記錄尚待補上的收尾字元
    cut_points: list[tuple[int, list[str]]] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(snippet):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            cut_points.append((i + 1, list(stack)))

    for end, remaining in reversed(cut_points):
        candidate = snippet[:end].rstrip().rstrip(",")
        candidate += "".join(reversed(remaining))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
