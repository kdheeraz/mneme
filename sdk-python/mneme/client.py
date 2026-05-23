"""Thin synchronous client for the Mneme memory API.

Designed to be Mem0-style ergonomic:

    m = Mneme(api_key="mneme_sk_...", base_url="http://localhost:8000")
    m.add("User prefers PyTorch", agent_id="research-bot", user_id="user_42")
    hits = m.search("which framework does the user prefer?", agent_id="research-bot")
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any
import httpx


class Mneme:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8000", timeout: float = 30.0):
        if not api_key:
            raise ValueError("api_key is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    # -------- memories --------

    def add(
        self,
        content: str,
        *,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        kind: str = "semantic",
        scope: str = "private",
        meta: Optional[Dict[str, Any]] = None,
        importance: float = 0.5,
    ) -> Dict[str, Any]:
        r = self._client.post("/v1/memories", json={
            "content": content,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "kind": kind,
            "scope": scope,
            "meta": meta or {},
            "importance": importance,
        })
        r.raise_for_status()
        return r.json()

    def ingest(
        self,
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        text: Optional[str] = None,
        context: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: str = "private",
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Auto-extract atomic memories from a conversation using the agent's LLM."""
        r = self._client.post("/v1/memories/ingest", json={
            "messages": messages,
            "text": text,
            "context": context,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "scope": scope,
            "persist": persist,
        })
        r.raise_for_status()
        return r.json()

    def search(
        self,
        query: str,
        *,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 10,
        mode: str = "hybrid",            # "hybrid" | "vector" | "lexical"
        recency_weight: float = 0.15,
        rrf_k: int = 60,
        candidates: int = 30,
        rerank: bool = False,            # cross-encoder rerank (needs reranker on agent)
        rerank_top_k: int = 30,
        rewrite: bool = False,           # LLM query expansion (needs LLM on agent)
        use_graph: bool = False,         # graph-augmented retrieval (needs graph on agent)
        cross_agent: bool = False,
    ) -> Dict[str, Any]:
        r = self._client.post("/v1/memories/search", json={
            "query": query,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "kind": kind,
            "limit": limit,
            "mode": mode,
            "recency_weight": recency_weight,
            "rrf_k": rrf_k,
            "candidates": candidates,
            "rerank": rerank,
            "rerank_top_k": rerank_top_k,
            "rewrite": rewrite,
            "use_graph": use_graph,
            "cross_agent": cross_agent,
        })
        r.raise_for_status()
        return r.json()

    def list(self, **filters) -> List[Dict[str, Any]]:
        r = self._client.get("/v1/memories", params={k: v for k, v in filters.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def get(self, memory_id: str) -> Dict[str, Any]:
        r = self._client.get(f"/v1/memories/{memory_id}")
        r.raise_for_status()
        return r.json()

    def update(self, memory_id: str, **patch) -> Dict[str, Any]:
        r = self._client.patch(f"/v1/memories/{memory_id}", json={k: v for k, v in patch.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def delete(self, memory_id: str) -> None:
        r = self._client.delete(f"/v1/memories/{memory_id}")
        r.raise_for_status()

    # -------- observability --------

    def traces(self, **filters) -> List[Dict[str, Any]]:
        r = self._client.get("/v1/traces", params={k: v for k, v in filters.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def trace(self, trace_id: str) -> Dict[str, Any]:
        r = self._client.get(f"/v1/traces/{trace_id}")
        r.raise_for_status()
        return r.json()

    def stats(self) -> Dict[str, Any]:
        r = self._client.get("/v1/stats")
        r.raise_for_status()
        return r.json()

    # -------- graph memory --------

    def graph(self, *, agent_id: Optional[str] = None, limit: int = 300) -> Dict[str, Any]:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        r = self._client.get("/v1/graph", params=params)
        r.raise_for_status()
        return r.json()

    def rebuild_graph(self, *, agent_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"agent_id": agent_id} if agent_id else {}
        r = self._client.post("/v1/graph/rebuild", params=params)
        r.raise_for_status()
        return r.json()

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
