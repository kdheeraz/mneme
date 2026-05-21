"""Cross-encoder reranker dispatch (Cohere / Voyage / Jina).

The reranker takes a query + N candidate docs and returns relevance scores.
We use it AFTER the RRF blend on the top-K candidates."""
from typing import List, Tuple, Optional
import httpx

from .models import Agent
from .auth_user import decrypt_secret


class RerankUnavailable(Exception):
    pass


def _cohere(query: str, docs: List[str], model: str, api_key: str) -> List[Tuple[int, float]]:
    r = httpx.post(
        "https://api.cohere.com/v2/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "query": query, "documents": docs},
        timeout=30.0,
    )
    r.raise_for_status()
    return [(item["index"], float(item["relevance_score"])) for item in r.json()["results"]]


def _voyage(query: str, docs: List[str], model: str, api_key: str) -> List[Tuple[int, float]]:
    r = httpx.post(
        "https://api.voyageai.com/v1/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "query": query, "documents": docs},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json().get("data") or r.json().get("results") or []
    return [(item["index"], float(item["relevance_score"])) for item in data]


def _jina(query: str, docs: List[str], model: str, api_key: str) -> List[Tuple[int, float]]:
    r = httpx.post(
        "https://api.jina.ai/v1/rerank",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "query": query, "documents": docs},
        timeout=30.0,
    )
    r.raise_for_status()
    return [(item["index"], float(item["relevance_score"])) for item in r.json()["results"]]


def rerank(agent: Optional[Agent], query: str, docs: List[str]) -> List[Tuple[int, float]]:
    """Returns [(original_index, relevance_score), ...] sorted by score desc.
    Raises RerankUnavailable if agent has no reranker configured."""
    if not agent or agent.rerank_provider in (None, "", "none"):
        raise RerankUnavailable("agent has no reranker configured")
    api_key = decrypt_secret(agent.rerank_api_key_enc)
    if not api_key:
        raise RerankUnavailable(f"{agent.rerank_provider} selected but no API key set")
    model = agent.rerank_model or "rerank-english-v3.0"

    if agent.rerank_provider == "cohere":
        return _cohere(query, docs, model, api_key)
    if agent.rerank_provider == "voyage":
        return _voyage(query, docs, model, api_key)
    if agent.rerank_provider == "jina":
        return _jina(query, docs, model, api_key)
    raise RerankUnavailable(f"unknown rerank provider: {agent.rerank_provider}")
