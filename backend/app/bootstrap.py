"""Runs once on container boot. Ensures tables exist + (optional) demo data."""
import time
import sys
from sqlalchemy.exc import OperationalError

from .db import Base, engine, session
from .models import User, Tenant, Agent, ApiKey, Memory
from .auth import new_api_key
from .auth_user import hash_password
from .config import settings


def wait_for_db(retries: int = 30, delay: float = 1.0):
    for i in range(retries):
        try:
            with engine.connect() as c:
                c.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            print(f"[bootstrap] waiting for db... ({i + 1}/{retries})", flush=True)
            time.sleep(delay)
    print("[bootstrap] db never came up", flush=True)
    sys.exit(1)


def ensure_demo_user():
    """Seed a demo user + tenant + agents so the dashboard has something to show
    immediately. Idempotent — runs only if no users exist."""
    db = session()
    try:
        if db.query(User).count() > 0:
            return

        user = User(
            email="demo@mneme.dev",
            password_hash=hash_password("demo1234"),
            name="Demo",
        )
        db.add(user)
        db.flush()

        tenant = Tenant(
            name="Demo Workspace",
            owner_user_id=user.id,
            embedding_dim=settings.embedding_dim,
            plan="pro",  # comp'd: demo ships 4 agents, above the free cap of 2
        )
        db.add(tenant)
        db.flush()

        agents_seed = [
            ("research-bot", "Research Bot", "Reads papers, summarizes, answers questions."),
            ("support-agent", "Support Agent", "Handles customer support tickets."),
            ("code-assistant", "Code Assistant", "Pair-programs with the user."),
            ("sales-agent", "Sales Agent", "Tracks leads and deal context."),
        ]
        for slug, name, desc in agents_seed:
            db.add(Agent(
                tenant_id=tenant.id, slug=slug, name=name, description=desc,
                embedding_provider="fake", embedding_model="text-embedding-3-small",
                llm_provider="none", llm_model="gpt-4o-mini",
            ))
        db.flush()

        # one tenant-wide key + one per-agent key
        tenant_key = ApiKey(tenant_id=tenant.id, key=new_api_key(), label="tenant-wide")
        db.add(tenant_key)
        for slug, *_ in agents_seed:
            db.add(ApiKey(tenant_id=tenant.id, agent_slug=slug, key=new_api_key(), label=f"{slug}-default"))
        db.commit()

        print(f"[bootstrap] demo user: demo@mneme.dev / demo1234", flush=True)
        print(f"[bootstrap] tenant-wide key: {tenant_key.key}", flush=True)
    finally:
        db.close()


def main():
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_boot:
        ensure_demo_user()
        try:
            from seed import run as seed_run  # type: ignore
            seed_run()
        except Exception as e:
            print(f"[bootstrap] seed skipped: {e}", flush=True)


if __name__ == "__main__":
    main()
