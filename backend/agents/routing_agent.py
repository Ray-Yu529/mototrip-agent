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
        "6. 遵守使用者偏好（見下方偏好設定）\n"
        "7. 輸出**純 JSON**，不要加 markdown 或說明文字\n\n"
        "輸出格式：\n"
        '{{"theme": "主題", "transport": "交通方式", "total_days": 天數, '
        '"itinerary": ['
        '{{"day": 1, "date": "YYYY-MM-DD", "stops": ['
        '{{"time": "HH:MM", "place": "名稱", "type": "餐廳/景點/住宿/加油站/補給", "note": "備註"}}'
        ']}}, ...'
        '], "survival_tips": ["小提醒1", "小提醒2"]}}'
    )),
    ("human", (
        "旅遊主題：{theme}\n"
        "交通方式：{transport}（{transport_note}）\n"
        "出發地：{origin} → 目的地：{destination}\n"
        "出發日期：{start_date}，共 {days} 天\n"
        "偏好設定：{preferences_note}\n\n"
        "天氣資訊（目的地）：\n{weather_info}\n\n"
        "推薦景點／餐廳（含 venue 室內外標記）：\n{poi_list}\n\n"
        "住宿防雷分析：\n{lodging_info}"
    )),
])


async def generate_itinerary(
    theme: str,
    origin: str,
    destination: str,
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
        "destination": destination,
        "start_date": start_date,
        "days": days,
        "preferences_note": preferences_note,
        "weather_info": json.dumps(weather_info, ensure_ascii=False, indent=2),
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

    # 3. 直接 parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 4. 找最外層的 { ... }
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"Routing LLM 輸出非 JSON，完整內容: {raw}")
    return {"error": "行程生成失敗，請重試", "raw": raw[:500]}
