"""
LLM / Embedding 工廠。
透過 .env 的 LLM_BACKEND 切換後端：
  - "ollama"  本機推論，隱私最高
  - "nvidia"  NVIDIA NIM 雲端，速度快，開發期推薦
"""
from functools import lru_cache
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from .config import settings


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    if settings.llm_backend == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        llm = ChatNVIDIA(
            api_key=settings.nvidia_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        # chat_template_kwargs 須透過 bind 傳入 extra_body，不能放 model_kwargs
        if settings.llm_enable_thinking:
            return llm.bind(
                extra_body={"chat_template_kwargs": {"enable_thinking": True}}
            )
        return llm

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
        # baai/bge-m3 目前在 NVIDIA NIM 上會回傳 500（服務端問題，模型本身仍列在目錄中），
        # 實測 nvidia/nv-embedqa-e5-v5 正常，故換用；換模型會改變向量空間，
        # 既有已匯入的評論需要重跑 ingest script 才能用新模型重新產生向量。
        return NVIDIAEmbeddings(
            api_key=settings.nvidia_api_key,
            model="nvidia/nv-embedqa-e5-v5",
        )
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.embed_model,
    )
