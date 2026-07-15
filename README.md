# MotoTrip Agent 山林騎旅全能管家

機車旅遊 AI 規劃系統。支援多日行程、多交通方式、住宿防雷 RAG 分析、海拔氣溫修正。  
LLM 後端可一鍵切換：**NVIDIA NIM 雲端**（開發期推薦）或 **Ollama 本機**（隱私優先）。

---

## 功能一覽

| 功能 | 說明 |
|------|------|
| 多日行程規劃 | 1–10 天，按 Day 分組，含住宿安排 |
| 多交通方式 | 機車、重機、自行車、汽車、大眾運輸，各自調整行程節奏 |
| 旅遊主題引擎 | 米其林吃貨、雙人浪漫、硬派跑山、秘境攝影，或自訂主題 |
| 住宿防雷 RAG | 檢索真實評論，輸出潔癖指數 + 機車友善指數 + 停車場分析；資料庫查無資料時自動即時抓 Google 評論補上 |
| 天氣騎乘建議 | CWA 全台 22 縣市鄉鎮 7 天預報，依「行程實際日期」逐日解析，海拔每 100m 降 0.6°C 修正 |
| 真實路線規劃 | 串接 OSRM 算出每日實際騎乘距離/時間/道路路線，取代 LLM 憑印象猜測 |
| 沿線加油站預警 | 依真實路線用 Google Places 查詢沿途加油站，無油站路段過長時主動警示 |
| 預算估算 | 依真實里程換算油錢、依用餐預算等級估算餐飲費，提供每日明細 |
| 台鐵查詢（TDX） | 車站查詢、起訖站時刻表與各車種票價、車站即時到離站看板含誤點資訊（約 2 分鐘延遲）；大眾運輸行程自動把各段真實班次餵給 LLM，transfer 引用實際車次 |
| 行程匯出 | HTML 報告 / JSON / GPX（給導航機/地圖 App）/ ICS（行事曆） |
| 對話式行程微調 | 生成後用一句話描述想怎麼改，AI 局部重排並重新計算路線與預算 |

---

## 各 API 依賴（免費額度即可）

| 服務 | 用途 | 是否必要 |
|------|------|---------|
| CWA 開放資料 | 天氣預報 | 建議（無 key 時用 mock 資料） |
| Google Places API | 景點/餐廳/民宿評論/加油站查詢 | 建議 |
| OSRM（`router.project-osrm.org`） | 真實路線/距離/時間 | 免 key，預設用官方公用 demo server；正式環境建議自架服務並改 `OSRM_BASE_URL` |
| TDX 運輸資料流通服務 | 台鐵時刻表/票價/即時動態 | 建議（無 key 時用 mock 資料）；交通部官方平台，前身 PTX 已於 2022 年底停止服務 |

---

## 環境需求

- Python 3.11+
- LLM 後端擇一：
  - **NVIDIA NIM**（推薦）：申請 API Key，無需本機 GPU
  - **Ollama**：本機安裝，支援 gemma3:1b 等模型

---

## 快速啟動（Docker Compose，推薦）

```bash
cd mototrip-agent
cp .env.example .env        # 填入 NVIDIA_API_KEY / CWA_API_KEY 等
docker compose up -d --build
```

- 前端：http://localhost:8501
- 後端 API：http://localhost:8000
- 向量資料庫與 geocode 快取持久化在 `./data`（掛載 volume）

匯入範例評論（RAG 防雷功能需要，容器內執行）：

```bash
docker compose exec backend python -m scripts.ingest_sample_reviews
```

關閉：`docker compose down`

### 選用：本機 Ollama 後端

```bash
# .env 改成 LLM_BACKEND=ollama，然後啟用 ollama profile
docker compose --profile ollama up -d --build
docker compose exec ollama ollama pull gemma3:1b
docker compose exec ollama ollama pull nomic-embed-text
```

---

## 本機開發啟動（不使用 Docker）

### 1. 安裝依賴

```bash
cd mototrip-agent
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env，填入以下 key
```

| 變數 | 說明 | 取得方式 |
|------|------|---------|
| `LLM_BACKEND` | `nvidia` 或 `ollama` | 直接填 |
| `NVIDIA_API_KEY` | nvapi-... | [build.nvidia.com](https://build.nvidia.com) 免費註冊 |
| `CWA_API_KEY` | CWA-... | [opendata.cwa.gov.tw](https://opendata.cwa.gov.tw) 免費申請 |
| `GOOGLE_PLACES_API_KEY` | AIzaSy... | Google Cloud Console（選填）|
| `TDX_CLIENT_ID` / `TDX_CLIENT_SECRET` | 台鐵查詢用 | [tdx.transportdata.tw](https://tdx.transportdata.tw/) 免費註冊 → 會員中心 → API 金鑰（選填）|
| `OSRM_BASE_URL` | 預設官方 demo server | 選填，正式環境建議自架 |
| `FUEL_PRICE_PER_LITER` | 預算估算用油價，預設 32 | 選填 |
| `CORS_ORIGINS` | 允許的前端來源，逗號分隔 | 選填，預設本機 Streamlit |

#### NVIDIA NIM 模式（預設）

```env
LLM_BACKEND=nvidia
NVIDIA_API_KEY=nvapi-...
LLM_MODEL=google/diffusiongemma-26b-a4b-it
LLM_TEMPERATURE=1.0
```

#### Ollama 本機模式

```env
LLM_BACKEND=ollama
LLM_MODEL=gemma3:1b
```

```bash
# 先拉模型
ollama pull gemma3:1b
ollama pull nomic-embed-text
```

### 3. 匯入範例評論（RAG 防雷功能需要）

```bash
# 使用內建 mock 評論（3 間示範民宿）
python -m scripts.ingest_sample_reviews

# 或從 Google Maps 抓真實評論（需填 GOOGLE_PLACES_API_KEY）
python -m scripts.ingest_google_reviews --names "清境農場" "廬山溫泉" "合歡山松雪樓"
```

### 4. 啟動後端（Terminal A）

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### 5. 啟動前端（Terminal B）

```bash
streamlit run frontend/app.py
```

開啟瀏覽器：**http://localhost:8501**

---

## API 快速驗證

```bash
# 健康檢查
curl http://localhost:8000/health

# 天氣（仁愛鄉 1500m）
curl "http://localhost:8000/weather/advice?location=仁愛鄉&altitude_m=1500"

# 住宿防雷（需先匯入評論）
curl "http://localhost:8000/lodging/analyze?lodging_name=合歡山雲端小屋"

# 台鐵：車站關鍵字查詢 / 起訖站時刻表+票價 / 車站即時看板（誤點資訊）
curl "http://localhost:8000/rail/stations?keyword=竹"
curl "http://localhost:8000/rail/timetable?origin=台北&destination=花蓮&date=2026-07-20"
curl "http://localhost:8000/rail/liveboard?station=台中"

# 行程生成（2 天重機跑山）
curl -X POST http://localhost:8000/itinerary/generate \
  -H "Content-Type: application/json" \
  -d '{"theme":"hardcore","origin":"台中市","destination":"仁愛鄉","start_date":"2026-06-20","days":2,"transport":"重機","altitude_m":1500}'

# 對話式行程微調（{...} 內帶入 /itinerary/generate 回傳的完整物件）
curl -X POST http://localhost:8000/itinerary/adjust \
  -H "Content-Type: application/json" \
  -d '{"itinerary": {...}, "instruction": "Day 2 不要去清境農場，換成鄰近景點"}'

# 匯出 GPX / ICS（同樣帶入完整行程物件）
curl -X POST http://localhost:8000/itinerary/export/gpx -H "Content-Type: application/json" -d '{"itinerary": {...}}'
curl -X POST http://localhost:8000/itinerary/export/ics -H "Content-Type: application/json" -d '{"itinerary": {...}}'
```

---

## 執行測試

```bash
pip install pytest
pytest tests/ -v
```

測試涵蓋天氣逐日解析、全 22 縣市對照表、加油站抽樣/距離計算、預算估算、GPX/ICS 輸出格式、座標模糊比對、台鐵站名比對與時刻表/票價/即時看板解析等純邏輯模組（不需要 API key 或網路）。

---

## 專案結構

```
mototrip-agent/
├── backend/
│   ├── main.py                 # FastAPI 入口（lifespan、CORS）
│   ├── data/
│   │   └── cwa_locations.json  # 全台 22 縣市 + 349 鄉鎮 對照表（掃描自 CWA API）
│   ├── core/
│   │   ├── config.py           # pydantic-settings（LLM 後端切換、OSRM、預算參數）
│   │   ├── llm.py              # LLM / Embedding 工廠（Ollama / NVIDIA）
│   │   ├── geocode.py          # Nominatim geocoding + POI 座標優先/模糊比對
│   │   ├── routing.py          # OSRM 真實路線（距離/時間/道路幾何）
│   │   ├── export.py           # GPX / ICS 行程匯出
│   │   └── google_reviews.py   # Google Places 評論查詢（script 與 rag_agent 共用）
│   ├── agents/
│   │   ├── weather_agent.py    # CWA API + 海拔溫差 + 逐日期解析（無 LLM）
│   │   ├── poi_agent.py        # Google Places 景點/餐廳查詢，async 平行送出（無 LLM）
│   │   ├── gas_agent.py        # 沿線加油站查詢與無油站路段警示（無 LLM）
│   │   ├── budget_agent.py     # 油錢/餐飲預算估算（無 LLM）
│   │   ├── rail_agent.py       # TDX 台鐵時刻表/票價/即時看板（無 LLM）
│   │   ├── rag_agent.py        # ChromaDB 檢索 + LLM 評分，查無資料時自動補抓評論
│   │   └── routing_agent.py    # 多日行程整合（LLM 呼叫 ×1）+ 對話式微調（LLM 呼叫 ×1）
│   └── routers/
│       ├── weather.py
│       ├── lodging.py
│       ├── rail.py             # /stations /timetable /liveboard
│       └── itinerary.py        # /generate /adjust /export/gpx /export/ics
├── frontend/
│   └── app.py                  # Streamlit UI（白底黑字極簡風）
├── scripts/
│   ├── ingest_sample_reviews.py   # mock 評論注入
│   └── ingest_google_reviews.py   # Google Places API 真實評論
├── tests/                      # pytest 單元測試（純邏輯，免 API key）
├── data/
│   └── chroma_db/              # 向量資料庫（.gitignore 排除）
├── .env.example
└── requirements.txt
```

---

## 系統架構

```
使用者請求
    │
    ├─ Weather Agent ──▶ CWA 全台鄉鎮預報 API + 海拔公式 + 逐日期解析   （無 LLM）
    │
    ├─ POI Agent ──────▶ Google Places 平行查詢景點/餐廳                （無 LLM）
    │
    ├─ RAG Agent ──────▶ ChromaDB 語意檢索（查無資料時自動補抓 Google 評論）
    │                         └──▶ LLM ×1：潔癖 / 機車友善指數 JSON
    │
    ├─ Routing Agent（LLM）──▶ 整合天氣 + RAG + POI
    │                              └──▶ LLM ×1：多日行程 JSON
    │
    ├─ Routing（OSRM）──▶ 每日站點串成真實道路距離/時間/路線幾何        （無 LLM）
    ├─ Gas Agent ───────▶ 沿真實路線查詢加油站、無油站路段警示          （無 LLM）
    ├─ Budget Agent ────▶ 依真實里程 + 用餐預算估算費用                 （無 LLM）
    └─ Rail Agent ──────▶ TDX 台鐵時刻表/票價/即時誤點；大眾運輸行程時    （無 LLM）
                          各段真實班次餵給 Routing Agent 引用實際車次

使用者事後微調（選用）
    └─ Routing Agent（adjust）──▶ 既有行程 + 一句話指令
                                        └──▶ LLM ×1：修改後的行程 JSON
```

**單次生成 LLM 最多呼叫 2 次**（RAG 分析 + 行程生成），確保 CPU / 低規格環境也能流暢運作；
對話式微調為選用功能，每次額外呼叫 1 次 LLM。

---

## LLM 後端切換

只需修改 `.env` 一行，無需改程式碼：

```env
# 雲端（快速，適合開發）
LLM_BACKEND=nvidia

# 本機（隱私，適合部署）
LLM_BACKEND=ollama
```
