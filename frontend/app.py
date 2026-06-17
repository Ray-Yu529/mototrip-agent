"""
MotoTrip Agent — Streamlit 前端
執行：streamlit run frontend/app.py
"""
import streamlit as st
import pydeck as pdk
import httpx
import hmac
import json
from datetime import date, timedelta

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="MotoTrip Agent 山林騎旅管家",
    page_icon="🏍",
    layout="wide",
)


# ── 登入閘門 ─────────────────────────────────────────────────────────────
def check_password() -> bool:
    """以 st.secrets 的 APP_PASSWORD 做簡單登入驗證。"""
    # 未設定密碼時直接放行（本機開發）
    if "APP_PASSWORD" not in st.secrets:
        return True

    def password_entered():
        if hmac.compare_digest(
            st.session_state.get("pw", ""), st.secrets["APP_PASSWORD"]
        ):
            st.session_state["authenticated"] = True
            del st.session_state["pw"]  # 不保留明文密碼
        else:
            st.session_state["authenticated"] = False

    if st.session_state.get("authenticated"):
        return True

    # 登入畫面
    st.title("MotoTrip Agent")
    st.caption("山林騎旅全能管家 · 請輸入通行碼")
    st.text_input("通行碼", type="password", key="pw", on_change=password_entered)
    if st.session_state.get("authenticated") is False:
        st.error("通行碼錯誤，請再試一次")
    return False


if not check_password():
    st.stop()

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

    /* ── 每日標題列 + 天氣晶片 ───────────────────────────── */
    .day-header {
        display: flex;
        align-items: center;
        gap: 0.8rem;
        margin: 1.5rem 0 0.8rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #111;
    }
    .day-badge {
        background: #111;
        color: #fff;
        font-weight: 700;
        font-size: 0.95rem;
        padding: 0.25rem 0.7rem;
        border-radius: 4px;
    }
    .day-date { color: #555; font-size: 0.9rem; }
    .weather-chip {
        margin-left: auto;
        background: #eef3f8;
        border: 1px solid #d4e0ec;
        border-radius: 16px;
        padding: 0.2rem 0.8rem;
        font-size: 0.82rem;
        color: #2c4a66;
    }

    /* ── 卡片時間軸 ───────────────────────────── */
    .timeline { position: relative; margin-left: 0.5rem; padding-left: 1.5rem;
                border-left: 2px solid #e3e3e3; }
    .tl-item { position: relative; margin-bottom: 1rem; }
    .tl-dot {
        position: absolute;
        left: -2.05rem;
        top: 0.55rem;
        width: 0.85rem;
        height: 0.85rem;
        border-radius: 50%;
        border: 3px solid #fff;
        box-shadow: 0 0 0 1px #ccc;
    }
    .stop-card {
        background: #ffffff;
        border: 1px solid #ececec;
        border-left: 4px solid #999;
        border-radius: 8px;
        padding: 0.7rem 1rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        transition: box-shadow 0.15s ease;
    }
    .stop-card:hover { box-shadow: 0 3px 12px rgba(0,0,0,0.12); }
    .stop-time {
        font-weight: 700; color: #111; font-size: 0.9rem;
        font-variant-numeric: tabular-nums;
    }
    .stop-place { font-weight: 600; color: #1a1a1a; font-size: 1.02rem; }
    .stop-note  { color: #666; font-size: 0.85rem; margin-top: 0.2rem; }
    .stop-tag {
        display: inline-block; font-size: 0.72rem; color: #fff;
        padding: 0.05rem 0.5rem; border-radius: 10px; margin-left: 0.4rem;
        vertical-align: middle;
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

        # 類型 → emoji / 顏色（HEX 給卡片、RGB 給地圖）
        TYPE_META = {
            "餐廳":   {"emoji": "🍜", "hex": "#f57c00", "rgb": [245, 124, 0]},
            "景點":   {"emoji": "📍", "hex": "#2e7d32", "rgb": [46, 125, 50]},
            "住宿":   {"emoji": "🏠", "hex": "#1565c0", "rgb": [21, 101, 192]},
            "加油站": {"emoji": "⛽", "hex": "#6a1b9a", "rgb": [106, 27, 154]},
            "補給":   {"emoji": "🏪", "hex": "#00838f", "rgb": [0, 131, 143]},
        }
        DEFAULT_META = {"emoji": "▸", "hex": "#757575", "rgb": [117, 117, 117]}

        def meta_of(stop_type: str) -> dict:
            return TYPE_META.get(stop_type, DEFAULT_META)

        itinerary = data.get("itinerary", [])
        weather = data.get("weather", {})

        if itinerary:
            # ── 路線地圖 ──────────────────────────────────────────
            map_points, path_coords = [], []
            for day_data in itinerary:
                for stop in day_data.get("stops", []):
                    if "lat" in stop and "lon" in stop:
                        m = meta_of(stop.get("type", ""))
                        map_points.append({
                            "lat": stop["lat"],
                            "lon": stop["lon"],
                            "place": stop.get("place", ""),
                            "label": f"D{day_data.get('day','')} {stop.get('time','')} {stop.get('place','')}",
                            "color": m["rgb"],
                        })
                        path_coords.append([stop["lon"], stop["lat"]])

            if map_points:
                avg_lat = sum(p["lat"] for p in map_points) / len(map_points)
                avg_lon = sum(p["lon"] for p in map_points) / len(map_points)

                scatter = pdk.Layer(
                    "ScatterplotLayer",
                    data=map_points,
                    get_position="[lon, lat]",
                    get_fill_color="color",
                    get_radius=600,
                    pickable=True,
                    opacity=0.85,
                )
                path = pdk.Layer(
                    "PathLayer",
                    data=[{"path": path_coords}],
                    get_path="path",
                    get_color=[17, 17, 17],
                    width_min_pixels=3,
                )
                st.pydeck_chart(pdk.Deck(
                    map_style="road",
                    initial_view_state=pdk.ViewState(
                        latitude=avg_lat, longitude=avg_lon, zoom=9, pitch=0,
                    ),
                    layers=[path, scatter],
                    tooltip={"text": "{label}"},
                ))
            else:
                st.info("地圖座標解析中或無資料，以下為文字行程。")

            # ── 卡片時間軸（按 Day 分組）──────────────────────────
            for day_data in itinerary:
                day_num = day_data.get("day", "")
                day_date = day_data.get("date", "")
                w_chip = ""
                if weather and not weather.get("error"):
                    w_chip = (
                        f'<span class="weather-chip">🌡 {weather.get("temp_range","")}'
                        f'　☔ {weather.get("rain_risk_pct","?")}%</span>'
                    )
                st.markdown(
                    f'<div class="day-header">'
                    f'<span class="day-badge">Day {day_num}</span>'
                    f'<span class="day-date">{day_date}</span>{w_chip}</div>',
                    unsafe_allow_html=True,
                )

                items_html = ['<div class="timeline">']
                for stop in day_data.get("stops", []):
                    m = meta_of(stop.get("type", ""))
                    note = (
                        f'<div class="stop-note">{stop["note"]}</div>'
                        if stop.get("note") else ""
                    )
                    tag = (
                        f'<span class="stop-tag" style="background:{m["hex"]}">'
                        f'{stop.get("type","")}</span>'
                        if stop.get("type") else ""
                    )
                    items_html.append(
                        f'<div class="tl-item">'
                        f'<span class="tl-dot" style="background:{m["hex"]}"></span>'
                        f'<div class="stop-card" style="border-left-color:{m["hex"]}">'
                        f'<span class="stop-time">{stop.get("time","")}</span>'
                        f'　<span class="stop-place">{m["emoji"]} {stop.get("place","")}</span>'
                        f'{tag}{note}'
                        f'</div></div>'
                    )
                items_html.append("</div>")
                st.markdown("".join(items_html), unsafe_allow_html=True)
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

        # 模糊比對提示：輸入簡稱對應到全名時告知
        matched_name = r.get("matched_name", "")
        if matched_name and matched_name != analyze_name.strip():
            st.info(f"🔍 已對應到：**{matched_name}**（{r.get('review_count', '?')} 則評論）")

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
