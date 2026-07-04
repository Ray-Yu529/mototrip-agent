from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # 後端切換：ollama | nvidia
    llm_backend: str = "ollama"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma3:1b"
    embed_model: str = "nomic-embed-text"

    # NVIDIA NIM
    nvidia_api_key: str = ""

    # External APIs
    cwa_api_key: str = ""        # 中央氣象署
    google_places_api_key: str = ""

    # 路線規劃（OSRM，預設用官方公用 demo server，僅供開發/展示）
    osrm_base_url: str = "https://router.project-osrm.org"

    # CORS 允許來源（逗號分隔），預設本機 Streamlit dev origin
    cors_origins: str = "http://localhost:8501"

    # 預算估算（新台幣）
    fuel_price_per_liter: float = 32.0
    meal_price_by_level: dict[int, int] = {0: 100, 1: 150, 2: 300, 3: 600, 4: 1200}

    # ChromaDB
    chroma_path: str = str(BASE_DIR / "data" / "chroma_db")
    chroma_collection: str = "lodging_reviews"

    # LLM generation params
    llm_temperature: float = 1.0   # DiffusionGemma 建議 1.0
    llm_max_tokens: int = 4096     # DiffusionGemma 思考模式需要較大 token 空間
    llm_enable_thinking: bool = True

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
