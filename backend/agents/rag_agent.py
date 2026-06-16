"""
RAG Agent — retrieves lodging reviews from ChromaDB,
then calls LLM once to score cleanliness + moto-friendliness.
"""
import json
import re
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import chromadb
from chromadb.config import Settings as ChromaSettings

from ..core.config import settings
from ..core.llm import get_llm, get_embeddings

_chroma_client: chromadb.ClientAPI | None = None


def _get_chroma_collection() -> chromadb.Collection:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


def add_reviews(lodging_name: str, reviews: list[str]) -> int:
    """Embed and store reviews. Returns number of docs added."""
    collection = _get_chroma_collection()
    embeddings = get_embeddings()

    docs, ids, metas = [], [], []
    for i, text in enumerate(reviews):
        docs.append(text)
        ids.append(f"{lodging_name}_{i}")
        metas.append({"lodging": lodging_name})

    vectors = embeddings.embed_documents(docs)
    collection.upsert(documents=docs, embeddings=vectors, ids=ids, metadatas=metas)
    logger.info(f"Stored {len(docs)} reviews for '{lodging_name}'")
    return len(docs)


async def analyze_lodging(lodging_name: str, top_k: int = 8) -> dict:
    """
    Retrieve top-k relevant reviews for a lodging and ask LLM to score it.
    Returns JSON with: cleanliness_score, moto_score, summary, red_flags.
    """
    collection = _get_chroma_collection()

    # 尚未匯入任何評論
    if collection.count() == 0:
        return {"error": f"評論資料庫是空的，請先執行 scripts/ingest_sample_reviews.py"}

    embeddings = get_embeddings()

    query = "停車場 機車 重機 清潔 霉味 衛生 床鋪 環境"
    query_vec = embeddings.embed_query(query)

    # 只篩此民宿的資料量
    lodging_count = len(
        collection.get(where={"lodging": lodging_name})["ids"]
    )
    if lodging_count == 0:
        return {"error": f"找不到『{lodging_name}』的評論，請先匯入或確認名稱正確"}

    results = collection.query(
        query_embeddings=[query_vec],
        n_results=min(top_k, lodging_count),
        where={"lodging": lodging_name},
    )

    if not results["documents"] or not results["documents"][0]:
        return {"error": f"找不到『{lodging_name}』的評論資料，請先執行 /ingest"}

    retrieved = "\n---\n".join(results["documents"][0])

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "你是一位嚴格的衛生檢察員，同時也是重機旅遊老手。"
            "請根據以下住宿評論，輸出**純 JSON**（不要加 markdown code block），格式如下：\n"
            '{{"cleanliness_score": 0-100, "moto_score": 0-100, '
            '"parking_detail": "停車場描述（室內/室外/碎石/水泥/無停車場）", '
            '"red_flags": ["雷點1", "雷點2"], '
            '"summary": "一句話總結"}}'
        )),
        ("human", "住宿名稱：{name}\n\n評論：\n{reviews}"),
    ])

    chain = prompt | get_llm() | StrOutputParser()
    raw = await chain.ainvoke({"name": lodging_name, "reviews": retrieved})

    return _parse_json_safe(raw, lodging_name)


def _parse_json_safe(raw: str, lodging_name: str) -> dict:
    """Extract JSON from LLM output, tolerating extra text."""
    # Strip markdown fences if model adds them anyway
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: find first { ... }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning(f"LLM returned non-JSON for '{lodging_name}': {raw[:200]}")
    return {"error": "LLM 輸出格式異常，請重試", "raw": raw[:500]}
