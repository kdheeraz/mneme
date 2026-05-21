"""Populate demo memories under the demo user's tenant."""
from datetime import datetime, timedelta, timezone
import random

from app.db import session
from app.models import User, Tenant, Memory
from app.embeddings import embed_for_agent


DEMO_DATA = [
    ("research-bot", "user_42", "User is researching transformer architectures for time-series forecasting.", "semantic"),
    ("research-bot", "user_42", "User prefers PyTorch over TensorFlow.", "semantic"),
    ("research-bot", "user_42", "Paper: 'Attention Is All You Need' was discussed on 2024-05-10.", "episodic"),
    ("research-bot", "user_42", "When summarizing a paper, extract: problem, method, datasets, key results, limitations.", "procedural"),

    ("support-agent", "user_7", "Customer is on the Enterprise plan, renewal date Oct 12.", "semantic"),
    ("support-agent", "user_7", "Reported SSO issue on 2025-03-04, resolved by re-provisioning SAML cert.", "episodic"),
    ("support-agent", "user_7", "Prefers responses under 3 sentences.", "semantic"),
    ("support-agent", "user_19", "Customer churned from competitor X over data residency issues.", "semantic"),

    ("code-assistant", "user_42", "Project uses FastAPI + SQLAlchemy 2.0 + pgvector.", "semantic"),
    ("code-assistant", "user_42", "Team convention: prefer dependency injection over module-level singletons.", "procedural"),
    ("code-assistant", "user_42", "Last debugging session: traced a memory leak to an unclosed asyncpg pool.", "episodic"),

    ("sales-agent", "user_99", "Lead is from a fintech, 200 employees, evaluating us vs Pinecone.", "semantic"),
    ("sales-agent", "user_99", "Demo scheduled 2025-04-14 with VP of Engineering.", "episodic"),
    ("sales-agent", "user_99", "Decision driver: pricing model + on-prem option for EU.", "semantic"),

    # shared / cross-agent
    ("research-bot", None, "Company-wide policy: redact PII before writing to long-term memory.", "procedural"),
    ("support-agent", None, "Company-wide policy: redact PII before writing to long-term memory.", "procedural"),
]


def run():
    db = session()
    try:
        user = db.query(User).filter(User.email == "demo@mneme.dev").first()
        if not user:
            return
        tenant = db.query(Tenant).filter(Tenant.owner_user_id == user.id).first()
        if not tenant:
            return

        existing = db.query(Memory).filter(Memory.tenant_id == tenant.id).count()
        if existing > 0:
            print(f"[seed] {existing} memories already exist, skip")
            return

        now = datetime.now(timezone.utc)
        for i, (agent, user_id, content, kind) in enumerate(DEMO_DATA):
            created = now - timedelta(hours=random.uniform(0.5, 240))
            vec = embed_for_agent(content, None, tenant.embedding_dim)
            db.add(Memory(
                tenant_id=tenant.id,
                agent_id=agent,
                user_id=user_id,
                session_id=f"sess_{(i // 3) + 1}",
                content=content,
                kind=kind,
                meta={"source": "seed"},
                importance=round(random.uniform(0.4, 0.95), 2),
                embedding=vec,
                created_at=created,
                updated_at=created,
                last_accessed_at=created,
                access_count=random.randint(0, 12),
            ))
        db.commit()
        print(f"[seed] inserted {len(DEMO_DATA)} demo memories")
    finally:
        db.close()


if __name__ == "__main__":
    run()
