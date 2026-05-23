"""Shared lenient JSON parsing for small-model outputs."""
import json
import re
from typing import Any, Dict

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def parse_json_lenient(raw: str) -> Dict[str, Any]:
    """Try strict JSON; fall back to the first {...} block. Raises ValueError if neither works."""
    s = _JSON_FENCE.sub("", raw or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from LLM response: {raw[:400]}")
