"""
Routing Agent — 唯一的 LLM 呼叫，整合所有資料輸出多日行程 JSON。
"""
import json
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from loguru import logger

from ..core.llm import get_llm

ITINERARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一位專業的旅遊規劃師。請根據以下資訊，規劃一份完整的多日旅遊行程。\n\n"
        "規則（必須遵守）：\n"
        "1. 所有景點活動安排在 07:00–21:00 之間\n"
        "2. 午後（12:00–15:00）降雨風險高時，優先安排 venue=indoor 的室內地點\n"
        "3. 依照交通方式調整每段移動時間與景點密度\n"
        "4. 多日行程每天都要有住宿安排（最後一天除外）\n"
        "5. **餐廳與景點請優先從「推薦景點／餐廳」清單中挑選**，不要自行虛構不存在的店家\n"
        "6. **若有多個途經城市，請依城市順序把總天數合理分配**，"
        "每個城市停留 1 天以上，景點挑該城市清單中的（poi 的 city 欄位標示所屬城市）\n"
        "7. 每個 stop 請加上 city 欄位標示所在城市\n"
        "8. 遵守使用者偏好（見下方偏好設定）\n"
        "9. 輸出**純 JSON**，不要加 markdown 或說明文字\n\n"
        "輸出格式：\n"
        '{{"theme": "主題", "transport": "交通方式", "total_days": 天數, '
        '"itinerary": ['
        '{{"day": 1, "date": "YYYY-MM-DD", "city": "當天主要城市", "stops": ['
        '{{"time": "HH:MM", "place": "名稱", "city": "城市", "type": "餐廳/景點/住宿/加油站/補給", "note": "備註"}}'
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

    raw = await chain.ainvoke({
        "theme": theme,
        "transport": transport,
        "transport_note": transport_note,
        "origin": origin,
        "cities": " → ".join(cities),
        "start_date": start_date,
        "days": days,
        "preferences_note": preferences_note,
        "weather_by_city": json.dumps(weather_by_city, ensure_ascii=False, indent=2),
        "poi_list": json.dumps(poi_list, ensure_ascii=False, indent=2),
        "lodging_info": json.dumps(lodging_info, ensure_ascii=False, indent=2),
    })

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
    """JSON 被截斷時，砍到最後一個完整 stop 並補上閉合括號。"""
    start = text.find("{")
    if start < 0:
        return None
    snippet = text[start:]
    # 逐步往回砍，找出可被補齊成合法 JSON 的最長前綴
    for end in range(len(snippet), 0, -1):
        chunk = snippet[:end]
        # 補上缺少的 ] 與 }
        opens = chunk.count("{") - chunk.count("}")
        brackets = chunk.count("[") - chunk.count("]")
        if opens < 0 or brackets < 0:
            continue
        candidate = chunk.rstrip().rstrip(",")
        candidate += "]" * brackets + "}" * opens
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
