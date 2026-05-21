"""LLM dispatch. Used (in the future) by auto-memory-extraction and consolidation.
Exposed now so that agents configured with an LLM provider can be tested
end-to-end from the dashboard."""
from typing import List, Dict, Optional
import httpx

from .models import Agent
from .auth_user import decrypt_secret


DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"


MERGE_SYSTEM = (
    "You merge near-duplicate memory facts into a single canonical statement. "
    "Combine any complementary detail; drop redundancy. Keep the merged fact under 30 words, "
    "as a single self-contained sentence. Return ONLY the merged fact — no preamble, no quotes."
)


def merge_memories(agent: Agent, a: str, b: str) -> str:
    """Use the agent's LLM to merge two near-duplicate memories into one canonical fact."""
    if not agent or (agent.llm_provider or "none") == "none":
        raise ValueError("agent has no LLM configured")
    text = chat(
        agent,
        [
            {"role": "system", "content": MERGE_SYSTEM},
            {"role": "user", "content": f"Fact A: {a}\nFact B: {b}"},
        ],
        max_tokens=120,
    )
    out = (text or "").strip().strip('"').strip("'")
    return out or a  # fall back to A if model returns empty


REWRITE_SYSTEM = (
    "You expand short user queries into richer retrieval queries. "
    "Add likely synonyms, common expansions, related entities, and 2–3 paraphrases. "
    "Do NOT answer the question. Do NOT add preamble. "
    "Return only the expanded query as a single line, under 60 words."
)


def rewrite_query(agent: Agent, query: str) -> str:
    """Use the agent's LLM to expand `query` for better retrieval recall.
    Raises if the agent has no LLM (caller should fall back to the original query)."""
    if not agent or (agent.llm_provider or "none") == "none":
        raise ValueError("agent has no LLM configured for rewrite")
    text = chat(
        agent,
        [
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": query},
        ],
        max_tokens=160,
    )
    return (text or query).strip()


def chat(agent: Agent, messages: List[Dict[str, str]], max_tokens: int = 256) -> str:
    """Synchronous text completion. Returns the assistant's text."""
    provider = agent.llm_provider or "none"
    model = agent.llm_model or "gpt-4o-mini"
    api_key = decrypt_secret(agent.llm_api_key_enc)
    base_url = agent.llm_base_url

    if provider == "none":
        raise ValueError("agent has no LLM configured")

    if provider == "openai":
        if not api_key:
            raise ValueError("openai selected but no API key configured")
        from openai import OpenAI
        kw = {"api_key": api_key}
        if base_url:
            kw["base_url"] = base_url
        client = OpenAI(**kw)
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""

    if provider == "anthropic":
        if not api_key:
            raise ValueError("anthropic selected but no API key configured")
        import anthropic  # only imported on demand
        client = anthropic.Anthropic(api_key=api_key)
        # Anthropic separates system from messages
        system = ""
        msgs = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                msgs.append(m)
        resp = client.messages.create(
            model=model, system=system or None, messages=msgs, max_tokens=max_tokens
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    if provider == "ollama":
        url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/") + "/api/chat"
        r = httpx.post(
            url,
            json={"model": model, "messages": messages, "stream": False,
                  "options": {"num_predict": max_tokens}},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("message") or {}).get("content", "")

    raise ValueError(f"unknown LLM provider: {provider}")
