"""Razorpay subscription billing.

Plan tiers are defined here; their Razorpay plan_ids are created on demand and cached
in the `razorpay_plans` table. Subscriptions are created server-side and authorized by
the customer via Razorpay Checkout on the frontend. Webhooks keep tenant status in sync.
"""
from __future__ import annotations
from typing import Optional, Dict
import razorpay
from sqlalchemy.orm import Session

from .config import settings
from .models import RazorpayPlan, Tenant


# Amounts in paise (₹1 = 100 paise). Free has no Razorpay plan.
PLAN_DEFS: Dict[str, dict] = {
    "free": {"name": "Free",  "amount": 0,      "limits": {"agents": 1,   "memories": 100}},
    "pro":  {"name": "Pro",   "amount": 99_900, "limits": {"agents": 10,  "memories": 100_000}},
    "team": {"name": "Team",  "amount": 499_900,"limits": {"agents": 100, "memories": 2_000_000}},
}


def limits_for(plan: Optional[str]) -> Dict[str, int]:
    """Resource caps for a tenant's plan. Unknown/None plans fall back to free.
    A resource absent from the dict means 'no cap' (unlimited)."""
    spec = PLAN_DEFS.get(plan or "free") or PLAN_DEFS["free"]
    return spec.get("limits", {})


class BillingNotConfigured(Exception):
    pass


def _client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise BillingNotConfigured("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def ensure_plan(db: Session, key: str) -> str:
    """Return the Razorpay plan_id for a tier, creating it in Razorpay if needed."""
    if key not in PLAN_DEFS or key == "free":
        raise ValueError(f"no billable plan '{key}'")
    cached = db.query(RazorpayPlan).filter(RazorpayPlan.key == key).first()
    if cached:
        return cached.razorpay_plan_id

    spec = PLAN_DEFS[key]
    client = _client()
    plan = client.plan.create({
        "period": "monthly",
        "interval": 1,
        "item": {
            "name": f"Mneme {spec['name']}",
            "amount": spec["amount"],
            "currency": "INR",
            "description": f"Mneme {spec['name']} plan — monthly",
        },
    })
    db.add(RazorpayPlan(key=key, razorpay_plan_id=plan["id"], amount=spec["amount"]))
    db.commit()
    return plan["id"]


def create_subscription(db: Session, tenant: Tenant, key: str, total_count: int = 12) -> dict:
    """Create a Razorpay subscription for `tenant` on plan `key`. Returns checkout details."""
    plan_id = ensure_plan(db, key)
    client = _client()
    sub = client.subscription.create({
        "plan_id": plan_id,
        "total_count": total_count,         # number of monthly cycles
        "customer_notify": 1,
        "notes": {"tenant_id": str(tenant.id), "plan": key},
    })
    tenant.razorpay_subscription_id = sub["id"]
    tenant.subscription_status = sub.get("status", "created")
    db.commit()
    return {
        "subscription_id": sub["id"],
        "key_id": settings.razorpay_key_id,
        "plan": key,
        "amount": PLAN_DEFS[key]["amount"],
        "short_url": sub.get("short_url"),
        "status": sub.get("status"),
    }


def verify_webhook(body: bytes, signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return False
    try:
        razorpay.Utility().verify_webhook_signature(
            body.decode("utf-8"), signature, settings.razorpay_webhook_secret
        )
        return True
    except Exception:
        return False


# subscription.status → our coarse status
_ACTIVE = {"active", "authenticated"}
_DEAD = {"halted", "cancelled", "completed", "expired"}


def apply_webhook_event(db: Session, event: dict) -> Optional[str]:
    """Update the tenant's plan/status from a Razorpay webhook payload. Returns the event type."""
    etype = event.get("event", "")
    payload = event.get("payload", {})
    sub = (payload.get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id")
    if not sub_id:
        return etype

    tenant = db.query(Tenant).filter(Tenant.razorpay_subscription_id == sub_id).first()
    if not tenant:
        return etype

    status = sub.get("status")
    if status:
        tenant.subscription_status = status

    plan_key = (sub.get("notes") or {}).get("plan")
    if status in _ACTIVE and plan_key:
        tenant.plan = plan_key
    elif status in _DEAD:
        tenant.plan = "free"

    db.commit()
    return etype
