"""
MotoTrip Agent — Streamlit 前端
執行：streamlit run frontend/app.py
"""
import streamlit as st
import httpx
import json
from datetime import date, timedelta

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="MotoTrip Agent 山林騎旅管家",
    page_icon="🏍",
    layout="wide",
)

# ── 全域樣式（白底黑字極簡學術風）──────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #ffffff; }
    h1, h2, h3 { color: #111111; font-family: 'Noto Sans TC', sans-serif; }
    .stButton > button {
        background-color: #111111;
        color: #ffffff;
        border-radius: 4px;
        border: none;
        padding: 0.5rem 1.5rem;
    }
    .stButton > button:hover { background-color: #333333; }
    .metric-card {
        background: #f8f8f8;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 1rem;
        text-align: center;
    }
    .score-high { color: #2e7d32; font-size: 2rem; font-weight: bold; }
    .score-mid  { color: #f57c00; font-size: 2rem; font-weight: bold; }
    .score-low  { color: #c62828; font-size: 2rem; font-weight: bold; }
    .red-flag { color: #c62828; }
    .tip-box {
        background: #f5f5f5;
        border-left: 3px solid #111;
        padding: 0.8rem 1rem;
        margin: 0.4rem 0;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# ── 標題區 ──────────────────────────────────────────────────────────────
st.title("MotoTrip Agent")
st.caption("山林騎旅全能管家 · 地端 AI 驅動 · 隱私第一")
st.divider()

# ── Sidebar：行程參數 ────────────────────────────────────────────────────
with st.sidebar:
    st.header("行程設定")

    theme = st.selectbox(
        "旅遊主題",
        options=["michelin", "couple", "hardcore", "photo"],
        format_func=lambda x: {
            "michelin": "🍜 米其林必比登吃貨之旅",
            "couple":   "💑 雙人浪漫微旅行",
            "hardcore": "🏔 硬派跑山刷彎",
            "photo":    "📷 秘境攝影打卡",
        }[x],
    )

    origin = st.text_input("出發地點", value="台中市")
    destination = st.text_input("目的地", value="仁愛鄉")
    altitude_m = st.slider("目的地海拔（公尺）", 0, 3400, 1000, step=100)
    trip_date = st.date_input("出發日期", value=date.today() + timedelta(days=1))

    col_days, col_transport = st.columns(2)
    with col_days:
        days = st.number_input("旅遊天數", min_value=1, max_value=7, value=1, step=1)
    with col_transport:
        transport = st.selectbox(
            "交通方式",
            options=["機車", "重機", "自行車", "汽車", "大眾運輸"],
        )

    st.subheader("住宿防雷")
    lodging_name = st.text_input(
        "民宿名稱（留空跳過）",
        value="合歡山雲端小屋",
        help="需先執行 scripts/ingest_sample_reviews.py",
    )

    st.subheader("景點清單（選填）")
    poi_raw = st.text_area(
        "JSON 格式，留空使用示範資料",
        height=100,
        placeholder='[{"name":"清境農場","type":"景點","rating":4.5}]',
    )

    generate_btn = st.button("生成行程", use_container_width=True)

# ── 主內容區：分頁 ───────────────────────────────────────────────────────
tab_itinerary, tab_weather, tab_lodging = st.tabs(
    ["行程規劃", "天氣 & 騎乘建議", "住宿防雷分析"]
)

# ── Tab 1：行程規劃 ──────────────────────────────────────────────────────
with tab_itinerary:
    if generate_btn:
        try:
            poi_list = json.loads(poi_raw) if poi_raw.strip() else [
                {"name": "清境農場", "type": "景點", "rating": 4.5},
                {"name": "彩虹瀑布", "type": "景點", "rating": 4.2},
                {"name": "廬山溫泉老街小吃", "type": "餐廳", "rating": 4.3},
            ]
        except json.JSONDecodeError:
            st.error("景點 JSON 格式錯誤，請確認格式")
            st.stop()

        with st.spinner("Routing Agent 規劃中，約需 30–90 秒..."):
            try:
                resp = httpx.post(
                    f"{API_BASE}/itinerary/generate",
                    json={
                        "theme": theme,
                        "origin": origin,
                        "destination": destination,
                        "start_date": str(trip_date),
                        "days": int(days),
                        "transport": transport,
                        "altitude_m": altitude_m,
                        "lodging_name": lodging_name,
                        "poi_list": poi_list,
                    },
                    timeout=180,
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.ConnectError:
                st.error("無法連接 FastAPI（請確認 uvicorn 已啟動）")
                st.stop()
            except httpx.HTTPStatusError as e:
                st.error(f"API 錯誤：{e.response.text}")
                st.stop()

        total_days = data.get("total_days", 1)
        st.subheader(
            f"{data.get('theme', '行程')} · {data.get('transport', '')} · {total_days} 天"
        )

        TYPE_EMOJI = {
            "餐廳": "🍜", "景點": "📍", "住宿": "🏠",
            "加油站": "⛽", "補給": "🏪",
        }

        itinerary = data.get("itinerary", [])
        if itinerary:
            for day_data in itinerary:
                day_num = day_data.get("day", "")
                day_date = day_data.get("date", "")
                st.markdown(f"#### Day {day_num}　{day_date}")
                for stop in day_data.get("stops", []):
                    col_time, col_info = st.columns([1, 5])
                    with col_time:
                        st.markdown(f"**{stop.get('time', '')}**")
                    with col_info:
                        emoji = TYPE_EMOJI.get(stop.get("type", ""), "▸")
                        st.markdown(f"{emoji} **{stop.get('place', '')}**")
                        if stop.get("note"):
                            st.caption(stop["note"])
                st.divider()
        else:
            st.warning("未能解析行程，顯示原始輸出：")
            st.json(data)

        tips = data.get("survival_tips", [])
        if tips:
            st.subheader("機車生存守則")
            for tip in tips:
                st.markdown(f'<div class="tip-box">▸ {tip}</div>', unsafe_allow_html=True)
    else:
        st.info("在左側填入行程參數後，點擊「生成行程」")

# ── Tab 2：天氣 ──────────────────────────────────────────────────────────
with tab_weather:
    if st.button("查詢騎乘建議", key="weather_btn"):
        with st.spinner(f"查詢 {destination} 天氣中..."):
            try:
                resp = httpx.get(
                    f"{API_BASE}/weather/advice",
                    params={"location": destination, "altitude_m": altitude_m},
                    timeout=15,
                )
                resp.raise_for_status()
                w = resp.json()
            except httpx.ConnectError:
                st.error("無法連接 FastAPI")
                st.stop()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("最佳騎乘時段", w.get("best_riding_window", "—"))
        with col2:
            rain = w.get("rain_risk_pct", 0)
            color = "🟢" if rain < 30 else "🟡" if rain < 60 else "🔴"
            st.metric("降雨機率", f"{color} {rain}%")
        with col3:
            st.metric("海拔修正氣溫", w.get("temp_range", "—"))

        st.subheader("穿搭建議")
        st.markdown(
            f'<div class="tip-box">{w.get("clothing_tip", "")}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("點擊上方按鈕查詢天氣")

# ── Tab 3：住宿防雷 ──────────────────────────────────────────────────────
with tab_lodging:
    analyze_name = st.text_input(
        "輸入民宿名稱", value="合歡山雲端小屋", key="analyze_input"
    )
    if st.button("開始防雷分析", key="rag_btn"):
        with st.spinner("RAG + LLM 分析評論中，約需 30–60 秒..."):
            try:
                resp = httpx.get(
                    f"{API_BASE}/lodging/analyze",
                    params={"lodging_name": analyze_name},
                    timeout=120,
                )
                resp.raise_for_status()
                r = resp.json()
            except httpx.ConnectError:
                st.error("無法連接 FastAPI")
                st.stop()
            except httpx.HTTPStatusError as e:
                st.error(f"找不到此民宿評論：{e.response.text}")
                st.stop()

        def score_html(score: int) -> str:
            cls = "score-high" if score >= 75 else "score-mid" if score >= 50 else "score-low"
            return f'<span class="{cls}">{score}</span>'

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("#### 潔癖指數")
            st.markdown(
                f'<div class="metric-card">{score_html(r.get("cleanliness_score", 0))}<br>/100</div>',
                unsafe_allow_html=True,
            )
        with col_b:
            st.markdown("#### 機車友善指數")
            st.markdown(
                f'<div class="metric-card">{score_html(r.get("moto_score", 0))}<br>/100</div>',
                unsafe_allow_html=True,
            )

        st.markdown(f"**停車場分析：** {r.get('parking_detail', '—')}")
        st.markdown(f"**總評：** {r.get('summary', '—')}")

        red_flags = r.get("red_flags", [])
        if red_flags:
            st.markdown("**雷點清單：**")
            for flag in red_flags:
                st.markdown(
                    f'<span class="red-flag">⚠ {flag}</span>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("點擊「開始防雷分析」，系統將從評論資料庫中檢索並分析")
