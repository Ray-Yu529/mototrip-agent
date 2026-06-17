# MotoTrip Agent 山林騎旅全能管家

機車旅遊 AI 規劃系統。支援多日行程、多交通方式、住宿防雷 RAG 分析、海拔氣溫修正。  
LLM 後端可一鍵切換：**NVIDIA NIM 雲端**（開發期推薦）或 **Ollama 本機**（隱私優先）。

---

## 功能一覽

| 功能 | 說明 |
|------|------|
| 多日行程規劃 | 1–7 天，按 Day 分組，含住宿安排 |
| 多交通方式 | 機車、重機、自行車、汽車、大眾運輸，各自調整行程節奏 |
| 旅遊主題引擎 | 米其林吃貨、雙人浪漫、硬派跑山、秘境攝影 |
| 住宿防雷 RAG | 檢索真實評論，輸出潔癖指數 + 機車友善指數 + 停車場分析 |
| 天氣騎乘建議 | CWA 鄉鎮層級預報，海拔每 100m 降 0.6°C 修正，推算最佳騎乘時段 |
| 加油站 / 補給預警 | Routing Agent 自動在行程中插入補給點 |

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

# 行程生成（2 天重機跑山）
curl -X POST http://localhost:8000/itinerary/generate \
  -H "Content-Type: application/json" \
  -d '{"theme":"hardcore","origin":"台中市","destination":"仁愛鄉","start_date":"2026-06-20","days":2,"transport":"重機","altitude_m":1500}'
```

---

## 專案結構

```
mototrip-agent/
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── core/
│   │   ├── config.py           # pydantic-settings（LLM 後端切換）
│   │   └── llm.py              # LLM / Embedding 工廠（Ollama / NVIDIA）
│   ├── agents/
│   │   ├── weather_agent.py    # CWA API + 海拔溫差（無 LLM）
│   │   ├── rag_agent.py        # ChromaDB 檢索 + LLM 評分
│   │   └── routing_agent.py    # 多日行程整合（LLM 呼叫 ×1）
│   └── routers/
│       ├── weather.py
│       ├── lodging.py
│       └── itinerary.py
├── frontend/
│   └── app.py                  # Streamlit UI（白底黑字極簡風）
├── scripts/
│   ├── ingest_sample_reviews.py   # mock 評論注入
│   └── ingest_google_reviews.py   # Google Places API 真實評論
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
    ├─ Weather Agent ──▶ CWA 鄉鎮預報 API + 海拔公式       （無 LLM）
    │
    ├─ RAG Agent ──────▶ ChromaDB 語意檢索
    │                         └──▶ LLM ×1：潔癖 / 機車友善指數 JSON
    │
    └─ Routing Agent ──▶ 整合天氣 + RAG + POI
                              └──▶ LLM ×1：多日行程 JSON
```

**LLM 最多呼叫 2 次**（RAG 分析 + 行程生成），確保 CPU / 低規格環境也能流暢運作。

---

## LLM 後端切換

只需修改 `.env` 一行，無需改程式碼：

```env
# 雲端（快速，適合開發）
LLM_BACKEND=nvidia

# 本機（隱私，適合部署）
LLM_BACKEND=ollama
```
