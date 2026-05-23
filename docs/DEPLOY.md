# Mneme — Deploy to Oracle Cloud (Always Free)

A $0 production deploy on one Oracle Cloud **Always Free** Arm VM. The heavy LLM runs on
**Ollama Cloud** (remote); the VM runs db + redis + api + web + a tiny local Ollama for
**embeddings only**. HTTPS is automatic via Caddy + a free DuckDNS subdomain.

> Not a managed SaaS — fine for a pilot / first design partner. Before charging, read
> "Before a paying client" at the bottom (backups, migrations, monitoring).

## 0. What you need
- An Oracle Cloud account (free; a card is required for identity verification, not charged).
- A free **DuckDNS** subdomain (https://www.duckdns.org).
- Your **Ollama Cloud** API key (set later, in the dashboard — never in a file).

## 1. Create the VM
1. Oracle Cloud → Compute → Instances → **Create instance**.
2. Image: **Ubuntu 22.04**. Shape: **VM.Standard.A1.Flex** (Ampere/Arm — the Always Free one). Give it ~2 OCPU / 12 GB (within the free 4 OCPU / 24 GB allowance).
3. Add your SSH public key. Create.
4. Note the **public IP**.

> The Always Free Arm shape can be capacity-constrained in busy regions — retry, or pick a
> different availability domain/region.

## 2. Open ports 80 + 443 (two layers!)
**a) Oracle Security List:** VCN → your subnet → Security List → add **Ingress** rules:
`0.0.0.0/0` TCP **80** and TCP **443**.

**b) The instance firewall** (Oracle Ubuntu images block by default):
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Point DuckDNS at the VM
On duckdns.org: create a subdomain (e.g. `mneme-acme`) and set its IP to your VM's public IP.
`mneme-acme.duckdns.org` should now resolve to the VM (`ping` it).

## 4. Install Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker   # run docker without sudo
```

## 5. Get the code + configure
```bash
git clone <your-repo-url> mneme && cd mneme
cp .env.example .env
# generate secrets:
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())"
nano .env   # paste secrets; set DOMAIN, PUBLIC_URL, POSTGRES_PASSWORD, ACME_EMAIL
```
Minimum to set in `.env`: `DOMAIN`, `PUBLIC_URL` (https://…), `POSTGRES_PASSWORD`,
`JWT_SECRET`, `FERNET_KEY`. Leave `EMBEDDING_DIM=768` and `SEED_ON_BOOT=false`.

## 6. Build + launch
```bash
docker compose -f docker-compose.prod.yml up -d --build       # builds arm64 natively on the VM
docker compose -f docker-compose.prod.yml exec ollama ollama pull nomic-embed-text   # ~274 MB, once
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy        # watch the cert get issued
```
Open **https://yourname.duckdns.org** — Caddy will have a valid Let's Encrypt cert.

## 7. Create your account + configure an agent
1. Dashboard → **Sign up** (real email + strong password — `SEED_ON_BOOT=false` means no demo account).
2. **Agents → New agent**, then:
   - **LLM**: provider `ollama`, base URL `https://ollama.com`, model `gemma4:31b` (or another from your Ollama Cloud plan), and paste your **Ollama Cloud key** in *LLM API key* (stored encrypted).
   - **Embedding**: provider `ollama`, base URL `http://ollama:11434`, model `nomic-embed-text`. *(That's the in-stack embedder — leave the key blank.)*
   - Save → **Test connection** (both should pass).
3. Create an API key for the agent and you're live — point your SDK at `https://yourname.duckdns.org`.

## 8. Updating later
```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```
⚠️ **No migrations yet.** `bootstrap` only `create_all`s *new* tables — it does **not** alter
existing ones. Any change to an existing table needs a manual `ALTER TABLE` (or you lose data
on a reset). Add **Alembic before you ship schema changes to a client** (see below).

---

## Before a paying client (do not skip)
- **Alembic migrations** — so you can ship updates without `ALTER`-by-hand or data loss.
- **Backups** — `pg_dump` on a cron to object storage (Oracle gives free buckets).
- **Rotate any key ever pasted into a chat/log.** Keys live only in `.env` + the encrypted DB.
- **Finish Razorpay** (webhook secret + one live charge) if billing.
- **Monitoring** — uptime ping + error logs; Redis is available for rate-limiting.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Cert not issued / site not HTTPS | Ports 80/443 not open at *both* layers (§2), or DNS not pointing at the VM yet |
| `Test connection` LLM fails | Wrong Ollama Cloud model tag (must be `name:tag`, e.g. `gemma4:31b`) or key not set |
| `Test connection` embedding fails | `nomic-embed-text` not pulled (§6), or base URL not `http://ollama:11434` |
| `Embedding dim mismatch` | `EMBEDDING_DIM` changed after first boot → needs a fresh DB |
| Arm shape "out of capacity" | Retry / different AD or region |
