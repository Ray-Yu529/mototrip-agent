FROM python:3.11-slim

# 系統相依（chromadb / httpx 編譯需求最小化）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先裝依賴以善用 layer cache
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 複製專案程式碼
COPY . .

# backend(8000) 與 frontend(8501) 共用此 image，實際指令由 compose 指定
EXPOSE 8000 8501
