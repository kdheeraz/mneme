"""Auto-extract atomic memories from a conversation using the agent's LLM.

The LLM is asked to produce a strict JSON object with a `memories` array,
each item having `content` and `kind`. We sanitize/parse robustly because
small models occasionally wrap the JSON in markdown or add preamble."""
from __future__ import annotations
from typing import List, Dict, Any, Tuple

from .models import Agent
from .llm import chat
from .jsonutil import parse_json_lenient


SYSTEM = (
    "You are a memory-extraction system. From the conversation, extract atomic memories "
    "worth remembering for future interactions with this user/agent.\n\n"
    "Rules:\n"
    "1. Each memory must be a single self-contained sentence. No pronouns referring to "
    "   outside context. If the conversation says 'I like X', write 'User likes X'.\n"
    "2. Record the resulting CURRENT STATE, not transitional language. When the user describes "
    "   a change to a single-valued attribute (employer, home city, job title, relationship, "
    "   diet, etc.), capture the NEW value as a present-tense fact so it cleanly replaces the "
    "   old one. Examples: 'I accepted an offer at Netflix, so I'm leaving Acme' -> 'User works "
    "   at Netflix' (NOT 'User accepted an offer' or 'User is leaving Acme'); 'we're relocating "
    "   to Lisbon' -> 'User lives in Lisbon'; 'I've gone back to eating meat' -> 'User eats meat'. "
    "   If a change has no stated new value, phrase the end state ('User no longer works at Acme').\n"
    "3. Classify each memory's kind:\n"
    "   - 'semantic': stable facts (preferences, attributes, relationships, opinions).\n"
    "   - 'episodic': specific events that occurred (dated actions, decisions, meetings).\n"
    "   - 'procedural': how-to rules, behavioral instructions, conventions to follow.\n"
    "4. Skip chit-chat, greetings, and anything not worth long-term recall.\n"
    "5. Output STRICT JSON, no preamble, no markdown fences. Schema:\n"
    '   {"memories":[{"content":"...","kind":"semantic|episodic|procedural"}, ...]}\n'
    "6. If there is nothing worth extracting, output: {\"memories\":[]}"
)


def _format_conversation(messages: List[Dict[str, str]] | None, text: str | None) -> str:
    if messages:
        lines = []
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)
    return text or ""


def extract_memories(
    agent: Agent,
    messages: List[Dict[str, str]] | None,
    text: str | None,
    extra_context: str | None = None,
) -> Tuple[List[Dict[str, str]], str]:
    """Returns (memories, raw_llm_response).
    `memories` is a list of {content, kind} dicts (kind always one of the 3 enums).
    Raises if the agent has no LLM, or if parsing fails."""
    if not agent or (agent.llm_provider or "none") == "none":
        raise ValueError("agent has no LLM configured for extraction")

    transcript = _format_conversation(messages, text)
    if not transcript.strip():
        return [], ""

    user_prompt = transcript
    if extra_context:
        user_prompt = f"Context: {extra_context}\n\nConversation:\n{transcript}"

    raw = chat(
        agent,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1000,
        json_mode=True,
    )
    parsed = parse_json_lenient(raw)
    raw_mems = parsed.get("memories") or []

    valid_kinds = {"semantic", "episodic", "procedural"}
    out: List[Dict[str, str]] = []
    for m in raw_mems:
        c = (m.get("content") or "").strip()
        k = (m.get("kind") or "semantic").strip().lower()
        if not c:
            continue
        if k not in valid_kinds:
            k = "semantic"
        out.append({"content": c, "kind": k})
    return out, raw
