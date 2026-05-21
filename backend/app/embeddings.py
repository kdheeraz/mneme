"""Embedding providers. Dispatched per-agent — each agent picks its own provider/model.
Falls back to the tenant/global default if no agent is bound."""
import hashlib
import math
from typing import List, Optional

import httpx
import numpy as np

from .config import settings
from .models import Agent
from .auth_user import decrypt_secret


# -------- providers --------

def _fake_embed(text: str, dim: int) -> List[float]:
    out = np.zeros(dim, dtype=np.float32)
    base = text.lower().strip()
    tokens = base.split()
    chunks_needed = math.ceil(dim * 4 / 32)
    raw = b""
    for i in range(chunks_needed):
        raw += hashlib.sha256(f"{i}:{base}".encode()).digest()
    arr = np.frombuffer(raw[: dim * 4], dtype=np.uint32).astype(np.float32)
    arr = (arr / np.float32(2**32)) - 0.5
    out[: arr.shape[0]] = arr
    out[0] += min(len(tokens), 50) / 100.0
    out[1] += min(len(base), 500) / 1000.0
    n = float(np.linalg.norm(out))
    if n > 0:
        out = out / n
    return out.tolist()


def _openai_embed(text: str, model: str, api_key: str, base_url: Optional[str] = None) -> List[float]:
    from openai import OpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    resp = client.embeddings.create(model=model, input=text)
    return resp.data[0].embedding


def _ollama_embed(text: str, model: str, base_url: str) -> List[float]:
    """Calls Ollama's /api/embeddings endpoint. base_url example: http://host.docker.internal:11434"""
    url = base_url.rstrip("/") + "/api/embeddings"
    r = httpx.post(url, json={"model": model, "prompt": text}, timeout=60.0)
    r.raise_for_status()
    data = r.json()
    vec = data.get("embedding")
    if not vec:
        raise ValueError(f"Ollama returned no embedding: {data}")
    return vec


# -------- dispatch --------

DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"


def embed_for_agent(text: str, agent: Optional[Agent], tenant_dim: int) -> List[float]:
    provider = (agent.embedding_provider if agent else settings.embedding_provider) or "fake"
    model = (agent.embedding_model if agent else settings.embedding_model) or "text-embedding-3-small"
    api_key = decrypt_secret(agent.embedding_api_key_enc) if agent else settings.openai_api_key
    base_url = (agent.embedding_base_url if agent else None) or None

    if provider == "openai":
        if not api_key:
            raise ValueError("openai embedding selected but no API key configured")
        vec = _openai_embed(text, model, api_key, base_url=base_url)
    elif provider == "ollama":
        url = base_url or DEFAULT_OLLAMA_URL
        vec = _ollama_embed(text, model, url)
    else:
        return _fake_embed(text, tenant_dim)

    if len(vec) != tenant_dim:
        raise ValueError(
            f"Embedding dim mismatch: {provider}/{model} returned {len(vec)}, "
            f"tenant expects {tenant_dim}. Set MNEME_EMBEDDING_DIM and `make reset`, "
            f"or pick a model that matches."
        )
    return vec


def embed(text: str) -> List[float]:
    return _fake_embed(text, settings.embedding_dim)
