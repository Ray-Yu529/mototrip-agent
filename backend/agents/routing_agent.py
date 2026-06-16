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
        "2. 午後（12:00–15:00）降雨風險高時，安排室內活動或休息\n"
        "3. 依照交通方式調整每段移動時間與景點密度\n"
        "4. 多日行程每天都要有住宿安排（最後一天除外）\n"
        "5. 輸出**純 JSON**，不要加 markdown 或說明文字\n\n"
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
        "出發日期：{start_date}，共 {days} 天\n\n"
        "天氣資訊（目的地）：\n{weather_info}\n\n"
        "推薦景點／餐廳：\n{poi_list}\n\n"
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
        "weather_info": json.dumps(weather_info, ensure_ascii=False, indent=2),
        "poi_list": json.dumps(poi_list, ensure_ascii=False, indent=2),
        "lodging_info": json.dumps(lodging_info, ensure_ascii=False, indent=2),
    })

    return _parse_json_safe(raw)


def _parse_json_safe(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning(f"Routing LLM 輸出非 JSON: {raw[:200]}")
    return {"error": "行程生成失敗，請重試", "raw": raw[:500]}
