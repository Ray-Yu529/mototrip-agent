# MotoTrip Agent 山林騎旅全能管家

地端 LLM 驅動的機車旅遊規劃系統，全程隱私、零雲端依賴。

---

## 環境需求

- Python 3.11+
- [Ollama](https://ollama.com) 已安裝並執行中

---

## 快速啟動（3 個終端機）

### 1. 安裝依賴

```bash
cd mototrip-agent
pip install -r requirements.txt
```

### 2. 拉取模型（只需做一次）

```bash
ollama pull gemma4:2b-instruct-q4_K_M
ollama pull nomic-embed-text
```

### 3. 設定環境變數

```bash
cp .env.example .env
# 填入 CWA_API_KEY（可留空，會用 mock 資料）
```

### 4. 匯入範例評論

```bash
python -m scripts.ingest_sample_reviews
```

### 5. 啟動 FastAPI 後端（Terminal A）

```bash
uvicorn backend.main:app --reload --port 8000
```

### 6. 啟動 Streamlit 前端（Terminal B）

```bash
streamlit run frontend/app.py
```

開啟瀏覽器：http://localhost:8501

---

## 驗證流程

啟動後先確認 API 健康：
```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"mototrip-agent"}
```

測試天氣（mock 模式）：
```bash
curl "http://localhost:8000/weather/advice?location=仁愛鄉&altitude_m=1000"
```

測試防雷分析：
```bash
curl "http://localhost:8000/lodging/analyze?lodging_name=合歡山雲端小屋"
```

---

## 專案結構

```
mototrip-agent/
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── core/
│   │   ├── config.py           # pydantic-settings 設定
│   │   └── llm.py              # Ollama LLM / Embedding 單例
│   ├── agents/
│   │   ├── weather_agent.py    # 氣象 + 海拔溫差（純邏輯）
│   │   ├── rag_agent.py        # ChromaDB 檢索 + LLM 評分
│   │   └── routing_agent.py    # 行程整合（唯一 LLM 呼叫）
│   └── routers/
│       ├── weather.py
│       ├── lodging.py
│       └── itinerary.py
├── frontend/
│   └── app.py                  # Streamlit UI
├── scripts/
│   └── ingest_sample_reviews.py
├── data/
│   ├── reviews/                # 原始評論暫存
│   └── chroma_db/              # 向量資料庫（自動生成）
├── .env.example
└── requirements.txt
```

---

## LLM 呼叫架構（最小化原則）

```
使用者請求
    │
    ├─ Weather Agent ──▶ CWA API + 海拔公式 （無 LLM）
    │
    ├─ RAG Agent ──────▶ ChromaDB 檢索 ──▶ LLM (1 次)：評分 JSON
    │
    └─ Routing Agent ──▶ 整合所有資料 ──▶ LLM (1 次)：行程 JSON
                                              ↑
                                        唯一重 LLM 呼叫
```

CPU 推論約 30–90 秒出結果，UI 顯示 spinner 等待。
