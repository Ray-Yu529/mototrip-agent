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

    theme_choice = st.selectbox(
        "旅遊主題",
        options=["michelin", "couple", "hardcore", "photo", "custom"],
        format_func=lambda x: {
            "michelin": "🍜 米其林必比登吃貨之旅",
            "couple":   "💑 雙人浪漫微旅行",
            "hardcore": "🏔 硬派跑山刷彎",
            "photo":    "📷 秘境攝影打卡",
            "custom":   "✏️ 自訂主題…",
        }[x],
    )
    if theme_choice == "custom":
        theme = st.text_input(
            "輸入自訂主題",
            value="鐵道七日環台之旅",
            help="例如：鐵道環島、老屋咖啡巡禮、離島跳島",
        ).strip() or "自由行"
    else:
        theme = theme_choice

    origin = st.text_input("出發地點", value="台中市")
    destination = st.text_input("目的地", value="仁愛鄉")
    waypoints_raw = st.text_input(
        "途經城市（多目的地，選填）",
        value="",
        placeholder="台北,宜蘭,花蓮,台東（用逗號分隔）",
        help="填了就走多城市/環島模式，天數自動分配到各城市；留空則只規劃單一目的地",
    )
    waypoints = [c.strip() for c in waypoints_raw.replace("，", ",").split(",") if c.strip()]

    altitude_m = st.slider("目的地海拔（公尺）", 0, 3400, 1000, step=100)
    trip_date = st.date_input("出發日期", value=date.today() + timedelta(days=1))

    col_days, col_transport = st.columns(2)
    with col_days:
        days = st.number_input("旅遊天數", min_value=1, max_value=10, value=1, step=1)
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

    st.subheader("篩選偏好")
    cuisines = st.multiselect(
        "餐廳類型",
        options=["小吃麵食", "火鍋", "咖啡廳", "特色料理", "素食", "夜市"],
        default=["特色料理"],
    )
    attraction_types = st.multiselect(
        "景點類型",
        options=["自然風景", "文化古蹟", "打卡熱點", "溫泉"],
        default=["自然風景"],
    )
    venue_pref_label = st.radio(
        "室內 / 室外",
        options=["依天氣自動", "偏好室內", "偏好室外"],
        horizontal=True,
        help="「依天氣自動」：午後降雨機率高時自動改室內",
    )
    venue_pref = {"依天氣自動": "auto", "偏好室內": "indoor",
                  "偏好室外": "outdoor"}[venue_pref_label]

    min_rating = st.slider("最低評分", 0.0, 5.0, 4.0, step=0.1)

    budget_label = st.select_slider(
        "用餐預算",
        options=["不限", "$", "$$", "$$$", "$$$$"],
        value="不限",
    )
    budget_map = {"不限": (None, None), "$": (0, 1), "$$": (1, 2),
                  "$$$": (2, 3), "$$$$": (3, 4)}
    min_price, max_price = budget_map[budget_label]

    with st.expander("進階：手動加景點 (JSON)"):
        poi_raw = st.text_area(
            "會與自動查詢合併",
            height=80,
            placeholder='[{"name":"清境農場","type":"景點","rating":4.5}]',
        )

    generate_btn = st.button("生成行程", use_container_width=True)

REPORT_EMOJI = {"餐廳": "🍜", "景點": "📍", "住宿": "🏠", "加油站": "⛽", "補給": "🏪"}


def build_report_html(data: dict) -> str:
    """把行程資料組成可列印的獨立 HTML 報告（瀏覽器 Ctrl+P 可存成 PDF）。"""
    weather = data.get("weather", {})
    theme = data.get("theme", "行程")
    transport = data.get("transport", "")
    total_days = data.get("total_days", 1)

    w_line = ""
    if weather and not weather.get("error"):
        w_line = (
            f'<p class="meta">天氣：{weather.get("temp_range","")}　'
            f'降雨機率 {weather.get("rain_risk_pct","?")}%　'
            f'最佳時段 {weather.get("best_riding_window","")}</p>'
            f'<p class="meta">穿搭：{weather.get("clothing_tip","")}</p>'
        )

    days_html = []
    for day in data.get("itinerary", []):
        rows = []
        for s in day.get("stops", []):
            emoji = REPORT_EMOJI.get(s.get("type", ""), "▸")
            note = f'<div class="note">{s.get("note","")}</div>' if s.get("note") else ""
            rows.append(
                f'<tr><td class="time">{s.get("time","")}</td>'
                f'<td><b>{emoji} {s.get("place","")}</b>'
                f'<span class="tag">{s.get("type","")}</span>{note}</td></tr>'
            )
        days_html.append(
            f'<h2>Day {day.get("day","")} <span class="date">{day.get("date","")}</span></h2>'
            f'<table>{"".join(rows)}</table>'
        )

    tips = data.get("survival_tips", [])
    tips_html = ""
    if tips:
        lis = "".join(f"<li>{t}</li>" for t in tips)
        tips_html = f"<h2>生存守則</h2><ul>{lis}</ul>"

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>{theme} 行程報告</title>
<style>
  body {{ font-family: "Microsoft JhengHei","Noto Sans TC",sans-serif;
         max-width: 760px; margin: 2rem auto; color: #1a1a1a; padding: 0 1rem; }}
  h1 {{ border-bottom: 3px solid #111; padding-bottom: .4rem; }}
  h2 {{ margin-top: 1.6rem; border-left: 5px solid #111; padding-left: .6rem; }}
  .date {{ color: #888; font-size: .9rem; font-weight: normal; }}
  .meta {{ color: #555; margin: .2rem 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: .5rem; }}
  td {{ border-bottom: 1px solid #eee; padding: .5rem .4rem; vertical-align: top; }}
  .time {{ width: 60px; font-weight: 700; color: #c0392b; white-space: nowrap; }}
  .tag {{ background: #f0f0f0; border-radius: 10px; font-size: .72rem;
          padding: .05rem .5rem; margin-left: .5rem; color: #555; }}
  .note {{ color: #777; font-size: .85rem; margin-top: .2rem; }}
  ul {{ line-height: 1.8; }}
  footer {{ margin-top: 2rem; color: #aaa; font-size: .8rem;
            border-top: 1px solid #eee; padding-top: .6rem; }}
  @media print {{ body {{ margin: 0; }} }}
</style></head><body>
<h1>{theme}</h1>
<p class="meta">交通方式：{transport}　|　共 {total_days} 天</p>
{w_line}
{"".join(days_html)}
{tips_html}
<footer>由 MotoTrip Agent 山林騎旅全能管家生成 · 提示：用瀏覽器列印 (Ctrl+P) 可存成 PDF</footer>
</body></html>"""


# ── 主內容區：分頁 ───────────────────────────────────────────────────────
tab_itinerary, tab_weather, tab_lodging = st.tabs(
    ["行程規劃", "天氣 & 騎乘建議", "住宿防雷分析"]
)

# ── Tab 1：行程規劃 ──────────────────────────────────────────────────────
with tab_itinerary:
    if generate_btn:
        try:
            poi_list = json.loads(poi_raw) if poi_raw.strip() else []
        except json.JSONDecodeError:
            st.error("手動景點 JSON 格式錯誤，請確認格式")
            st.stop()

        with st.spinner("查詢景點 + 行程規劃中，約需 30–90 秒..."):
            try:
                resp = httpx.post(
                    f"{API_BASE}/itinerary/generate",
                    json={
                        "theme": theme,
                        "origin": origin,
                        "destination": destination,
                        "waypoints": waypoints,
                        "start_date": str(trip_date),
                        "days": int(days),
                        "transport": transport,
                        "altitude_m": altitude_m,
                        "lodging_name": lodging_name,
                        "preferences": {
                            "cuisines": cuisines,
                            "attraction_types": attraction_types,
                            "min_rating": min_rating,
                            "min_price": min_price,
                            "max_price": max_price,
                            "venue_pref": venue_pref,
                        },
                        "poi_list": poi_list,
                    },
                    timeout=180,
                )
                resp.raise_for_status()
                # 存進 session_state，下載按鈕觸發重跑時資料才不會消失
                st.session_state["itin_data"] = resp.json()
            except httpx.ConnectError:
                st.error("無法連接 FastAPI（請確認 uvicorn 已啟動）")
                st.stop()
            except httpx.HTTPStatusError as e:
                st.error(f"API 錯誤：{e.response.text}")
                st.stop()

    # ── 從 session_state 渲染（生成後與下載重跑都會走這裡）──────────────
    data = st.session_state.get("itin_data")
    if data:
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

        # ── 下載報告 ──────────────────────────────────────────
        if data.get("itinerary"):
            st.divider()
            report_html = build_report_html(data)
            theme_name = data.get("theme", "行程")
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "📄 下載行程報告 (HTML)",
                    data=report_html,
                    file_name=f"MotoTrip_{theme_name}.html",
                    mime="text/html",
                    use_container_width=True,
                    help="下載後用瀏覽器開啟，Ctrl+P 可另存為 PDF",
                )
            with col_dl2:
                st.download_button(
                    "🗂 下載原始資料 (JSON)",
                    data=json.dumps(data, ensure_ascii=False, indent=2),
                    file_name=f"MotoTrip_{theme_name}.json",
                    mime="application/json",
                    use_container_width=True,
                )
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
