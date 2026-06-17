@echo off
REM ── MotoTrip Agent 對外 demo 一鍵啟動 ──────────────────────────
REM 同時啟動 FastAPI、Streamlit，並用 Cloudflare Tunnel 對外公開
REM 需先安裝 cloudflared： winget install --id Cloudflare.cloudflared
chcp 65001 >nul
REM 預設使用 miniconda 的 python，可依環境調整
set PY=%USERPROFILE%\miniconda3\python.exe
if not exist "%PY%" set PY=python

echo [1/3] 啟動 FastAPI 後端 (localhost:8000)...
start "MotoTrip API" %PY% -m uvicorn backend.main:app --port 8000

timeout /t 3 >nul

echo [2/3] 啟動 Streamlit 前端 (localhost:8501)...
start "MotoTrip UI" %PY% -m streamlit run frontend/app.py --server.port 8501 --server.headless true

timeout /t 5 >nul

echo [3/3] 開啟 Cloudflare Tunnel（公開網址會顯示在下方）...
cloudflared tunnel --url http://localhost:8501
