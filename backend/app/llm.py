"""LLM dispatch. Used (in the future) by auto-memory-extraction and consolidation.
Exposed now so that agents configured with an LLM provider can be tested
end-to-end from the dashboard."""
from typing import List, Dict, Optional
import httpx

from .models import Agent
from .auth_user import decrypt_secret
from .jsonutil import parse_json_lenient


DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"


MERGE_SYSTEM = (
    "You merge two near-duplicate memory facts into one canonical fact. "
    "Combine complementary detail, drop redundancy, keep it under 30 words as a single "
    'self-contained sentence. Return JSON only: {"merged": "<the merged fact>"}'
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
        max_tokens=300,
        json_mode=True,
    )
    try:
        out = (parse_json_lenient(text).get("merged") or "").strip()
    except Exception:
        out = ""
    return out or a  # fall back to A if parsing fails


REWRITE_SYSTEM = (
    "You rewrite a short search query into a richer retrieval query: add likely synonyms, "
    "related entities, and a paraphrase. Do NOT answer the question. Do NOT explain. "
    'Return JSON only: {"query": "<expanded query, one line, under 50 words>"}'
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
        max_tokens=300,
        json_mode=True,
    )
    try:
        expanded = (parse_json_lenient(text).get("query") or "").strip()
    except Exception:
        expanded = ""
    return expanded or query  # fall back to original if parsing fails


# Sensible per-provider default when an agent leaves llm_model blank. Bedrock model IDs
# carry the `anthropic.` provider prefix and are region/account-specific — override per agent.
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-4-7",
    "bedrock": "anthropic.claude-opus-4-7",
}

JSON_ONLY_DIRECTIVE = (
    "\nReturn ONLY raw, valid JSON. No markdown code fences, no commentary before or "
    "after the JSON."
)


def _default_model(provider: str) -> str:
    return DEFAULT_MODELS.get(provider, "gpt-4o-mini")


def _anthropic_client(agent: Agent, provider: str):
    """Build the right Anthropic SDK client. `bedrock` routes Claude through AWS Bedrock
    (AnthropicBedrock); `anthropic` hits the direct API. Same `.messages` surface for both."""
    import anthropic
    if provider == "bedrock":
        # Blank keys → AnthropicBedrock falls back to the container's ambient AWS creds.
        return anthropic.AnthropicBedrock(
            aws_region=agent.aws_region or "us-east-1",
            aws_access_key=decrypt_secret(agent.aws_access_key_enc) or None,
            aws_secret_key=decrypt_secret(agent.aws_secret_key_enc) or None,
        )
    api_key = decrypt_secret(agent.llm_api_key_enc)
    if not api_key:
        raise ValueError("anthropic selected but no API key configured")
    return anthropic.Anthropic(api_key=api_key)


def _anthropic_chat(client, model: str, messages: List[Dict[str, str]],
                    max_tokens: int, json_mode: bool) -> str:
    """Shared Messages API call for direct Anthropic + Bedrock.

    - json_mode: this SDK (0.40) predates structured outputs, so we enforce JSON with a
      system directive (Claude follows it reliably; callers also parse leniently).
    - prompt caching: the system prompt is sent as a `cache_control` block so a repeated
      prefix is cached. NOTE: caching only kicks in above the model's minimum cacheable
      prefix (~1024 tokens); the current maintenance prompts are smaller, so this is a
      no-op today (verify via usage.cache_read_input_tokens) but free to leave on and
      pays off if the system prompt grows.
    """
    system_text = ""
    turns: List[Dict[str, str]] = []
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n"
        else:
            turns.append({"role": m["role"], "content": m["content"]})
    if json_mode:
        system_text += JSON_ONLY_DIRECTIVE

    kwargs: Dict = {"model": model, "messages": turns, "max_tokens": max_tokens}
    if system_text.strip():
        kwargs["system"] = [{
            "type": "text",
            "text": system_text.strip(),
            "cache_control": {"type": "ephemeral"},
        }]
    resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


def chat(agent: Agent, messages: List[Dict[str, str]], max_tokens: int = 256, json_mode: bool = False) -> str:
    """Synchronous text completion. Returns the assistant's text.
    json_mode=True coaxes the model to emit valid JSON (grammar-constrained on Ollama,
    response_format on OpenAI, JSON-only system directive on Anthropic/Bedrock). Use for
    extraction; leave off for free text."""
    provider = agent.llm_provider or "none"
    model = agent.llm_model or _default_model(provider)
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
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, **extra
        )
        return resp.choices[0].message.content or ""

    if provider in ("anthropic", "bedrock"):
        client = _anthropic_client(agent, provider)
        return _anthropic_chat(client, model, messages, max_tokens, json_mode)

    if provider == "ollama":
        url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/") + "/api/chat"
        # api_key is sent as a Bearer token for Ollama's hosted cloud; None for a local server.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        # think=False disables reasoning models (Qwen3 etc.) so the budget goes to the
        # answer. format="json" grammar-constrains output to valid JSON for extraction.
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        r = httpx.post(url, json=payload, headers=headers, timeout=120.0)
        if r.status_code == 400:
            payload.pop("think", None)
            r = httpx.post(url, json=payload, headers=headers, timeout=120.0)
        r.raise_for_status()
        msg = r.json().get("message") or {}
        return msg.get("content") or msg.get("thinking") or ""

    raise ValueError(f"unknown LLM provider: {provider}")
