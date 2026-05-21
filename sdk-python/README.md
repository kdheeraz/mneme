# mneme-python

Python SDK for [Mneme](../) — memory for LLM agents.

## Install (local dev)

```bash
pip install -e ./sdk-python
```

## Use

```python
from mneme import Mneme

m = Mneme(api_key="mneme_sk_...", base_url="http://localhost:8000")

m.add(
    "User prefers PyTorch over TensorFlow",
    agent_id="research-bot",
    user_id="user_42",
    kind="semantic",
)

result = m.search(
    "which framework does the user like?",
    agent_id="research-bot",
    user_id="user_42",
)
for hit in result["hits"]:
    print(hit["final_score"], hit["memory"]["content"])
```
