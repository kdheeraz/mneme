"""End-to-end demo:
  1. log in as the seeded demo user
  2. grab a tenant-wide API key
  3. use the SDK to add memories and search

Run after `make up` + `make logs` (wait for "Application startup complete"):

    cd /Users/mac/projects/mneme
    pip install -e ./sdk-python httpx --quiet
    python examples/demo_agent.py
"""
import httpx
from mneme import Mneme

BASE = "http://localhost:8000"


def login_and_get_key() -> str:
    r = httpx.post(f"{BASE}/v1/auth/login", json={"email": "demo@mneme.dev", "password": "demo1234"})
    r.raise_for_status()
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    keys = httpx.get(f"{BASE}/v1/keys", headers=h).json()
    tenant_keys = [k for k in keys if not k["agent_slug"]]
    if tenant_keys:
        return tenant_keys[0]["key"]
    # else create one
    r = httpx.post(f"{BASE}/v1/keys", headers=h, json={"label": "demo-script"})
    r.raise_for_status()
    return r.json()["key"]


def main():
    key = login_and_get_key()
    print(f"using key: {key[:18]}...\n")

    m = Mneme(api_key=key, base_url=BASE)

    print("→ adding memories")
    m.add("User is interested in retrieval-augmented generation.",
          agent_id="research-bot", user_id="user_42")
    m.add("User finished a paper on long-context transformers last week.",
          agent_id="research-bot", user_id="user_42", kind="episodic")
    m.add("Prefer concise summaries with bullet points.",
          agent_id="research-bot", user_id="user_42", kind="procedural")

    print("\n→ searching: 'what does the user care about?'")
    res = m.search("what does the user care about in ML?",
                   agent_id="research-bot", user_id="user_42", limit=5)
    for h in res["hits"]:
        print(f"  [{h['final_score']:.3f}]  {h['memory']['content']}")
    print(f"\ntrace: http://localhost:3000/dashboard  (trace_id={res['trace_id']})")


if __name__ == "__main__":
    main()
