"""
LLM / Embedding 工廠。
透過 .env 的 LLM_BACKEND 切換後端：
  - "ollama"  （預設）本機推論，隱私最高
  - "nvidia"  NVIDIA NIM 雲端 API，速度快，開發期推薦
"""
from functools import lru_cache
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from .config import settings


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    if settings.llm_backend == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        extra: dict = {}
        if settings.llm_enable_thinking:
            extra["chat_template_kwargs"] = {"enable_thinking": True}
        return ChatNVIDIA(
            api_key=settings.nvidia_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            model_kwargs=extra,
        )
    # 預設 Ollama
    from langchain_ollama import ChatOllama
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        num_predict=settings.llm_max_tokens,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    if settings.llm_backend == "nvidia":
        from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
        return NVIDIAEmbeddings(
            api_key=settings.nvidia_api_key,
            model="baai/bge-m3",  # 多語言，支援繁體中文評論
        )
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.embed_model,
    )
