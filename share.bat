@echo off
REM === MotoTrip Agent - public demo launcher ===
REM Starts FastAPI + Streamlit, then exposes via Cloudflare Tunnel.
REM Requires cloudflared: winget install --id Cloudflare.cloudflared

set PY=%USERPROFILE%\miniconda3\python.exe
if not exist "%PY%" set PY=python

echo [1/3] Starting FastAPI backend on localhost:8000 ...
start "MotoTrip API" "%PY%" -m uvicorn backend.main:app --port 8000

timeout /t 3 >nul

echo [2/3] Starting Streamlit frontend on localhost:8501 ...
start "MotoTrip UI" "%PY%" -m streamlit run frontend/app.py --server.port 8501 --server.headless true

timeout /t 6 >nul

echo [3/3] Opening Cloudflare Tunnel (public URL shown below) ...
cloudflared tunnel --url http://localhost:8501
