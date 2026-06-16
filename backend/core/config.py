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
