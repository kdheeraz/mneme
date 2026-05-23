# Mneme — Licensing & Plans (open-core)

Mneme is **open-core**: the full memory engine is free to self-host. Revenue comes
from a paid layer on top — a Business/Enterprise license, support, and an optional
managed cloud. The free tier drives adoption and trust; the paid layer is the money.

## Tiers

| | **Community** (self-host) | **Business** (self-host + license) | **Enterprise** | **Managed Cloud** |
|---|---|---|---|---|
| Price | Free | from ~$XXX/yr (per instance) | Custom | Free → Pro/Team (usage) |
| Accounts / instance | up to **3** | **Unlimited** | Unlimited | n/a (per-tenant plans) |
| Core memory engine | ✅ all of it | ✅ | ✅ | ✅ |
| Hybrid search, graph, reconciliation | ✅ | ✅ | ✅ | ✅ |
| Python / JS SDKs, REST | ✅ | ✅ | ✅ | ✅ |
| Operator admin console | ✅ | ✅ | ✅ | ✅ |
| SSO / SAML | — | ✅ *(roadmap)* | ✅ | ✅ |
| Audit logs, RBAC / teams | — | ✅ *(roadmap)* | ✅ | ✅ |
| Support | community | **business SLA** | dedicated / air-gapped | included |
| Runs on your infra (data never leaves) | ✅ | ✅ | ✅ | ❌ (we host) |

> The **Pro/Team** plans in `billing.py` are for the **managed cloud** (multi-tenant,
> Razorpay-billed per workspace). The **Community/Business/Enterprise** tiers here are
> for **self-hosted** instances, gated by a license key. Don't confuse the two.

## Why these gates
The free tier stays genuinely useful (full core, up to 3 accounts) so teams adopt it.
The paid gates are things **organizations** need at scale and will pay for:
- **Unlimited accounts** — once a team grows past a few users.
- **SSO/SAML, audit logs, RBAC** — security/compliance must-haves (roadmap).
- **Support + SLA** — the real driver: enterprises won't run critical infra unsupported.

## How licensing works
- A license is an **EdDSA-signed JWT**, verified **offline** against a public key
  embedded in `backend/app/license.py`. **No phone-home** — works air-gapped.
- Claims: `sub` (customer), `tier`, `features`, `exp`, optional `max_users`.
- Missing / invalid / expired key → the instance silently runs in **Community** mode
  (never breaks; just capped). See `get_license()`.

### Install a license (customer)
Set one of:
```bash
MNEME_LICENSE_KEY="<token>"          # env var (recommended)
# or
MNEME_LICENSE_FILE=/etc/mneme/license.key
```
Restart the API. Verify in the dashboard **Admin → License**, or:
```bash
curl https://your-host/v1/license
```

### Issue a license (vendor only)
The private signing key lives **only with you** (`backend/.license_signing_key.pem`,
git-ignored — never commit or ship it). The public key is baked into the app.
```bash
cd backend
python tools/issue_license.py --customer "Acme Inc" --tier business \
    --days 365 --features all --max-users 0      # 0 = unlimited
# prints the token → send to the customer
```
Rotating the keypair: generate a new Ed25519 keypair, replace `LICENSE_PUBLIC_KEY`
in `backend/app/license.py`, and re-issue licenses.

## What's enforced today vs. roadmap
- **Enforced now:** Community account cap (`community_max_users`, default 3) on signup;
  license tier/features surfaced via `/v1/license` and the admin badge.
- **Roadmap (the features that justify Business):** SSO/SAML, audit logs, RBAC/teams.
  Build these against `license.has_feature(...)` when a customer asks — don't pre-build.

## Selling motion (the money plan)
1. **Community** gets them in the door (free, self-host, data stays put).
2. They grow past 3 users **or** need SSO/audit/compliance **or** want someone on the
   hook → **Business** license + **support contract**. Support is the easiest first sale
   (a contract, not code).
3. Don't want to self-host at all → **Managed Cloud** (the Pro/Team plans).
