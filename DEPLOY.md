# Deploying quiethumans (DigitalOcean)

This is a simple Docker-based deploy you can reuse for other apps. Everything
runs in three small containers on one droplet:

| Container | What it does |
|-----------|--------------|
| `web`      | The FastAPI app — search API, the website, and `/mcp` |
| `pipeline` | The crawler, running continuously |
| `caddy`    | Reverse proxy that gives the site free automatic HTTPS |

The database (Postgres), vector search (Qdrant) and the LLM all live elsewhere
and are configured through `backend/.env`. They are **not** run on the droplet.

---

## One-time server setup

SSH into the droplet (`ssh root@YOUR_SERVER_IP`), then:

```bash
# 1. Install Docker (official convenience script)
curl -fsSL https://get.docker.com | sh

# 2. Add 2 GB of swap (this droplet only has ~1 GB RAM, so this prevents crashes)
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 3. Open the firewall for web traffic + SSH (if ufw is enabled)
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# 4. Get the code (public repo)
git clone https://github.com/ankitaggarwal/quiethumans.git
cd quiethumans
```

## Add the secrets (never committed to git)

Create `backend/.env` on the server with your real values:

```bash
nano backend/.env
```

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require
QDRANT_URL=https://your-qdrant-host
QDRANT_KEY=your-qdrant-key
QDRANT_COLLECTION=your-collection-name
LOCAL_LLM_URL=https://your-llm-host
LOCAL_LLM_KEY=your-llm-key
LOCAL_LLM_MODEL=gemma4:e4b
GITHUB_TOKEN=your-github-token
MCP_TOKEN=your-mcp-token
```

## Create the database tables (first deploy only)

The app makes its own tables on SQLite, but on Postgres you create them once:

```bash
# If psql isn't installed: apt-get install -y postgresql-client
psql "$DATABASE_URL" -f backend/schema.sql
```

## Point the domain at the server

In your DNS provider, add an **A record**: `YOUR_DOMAIN -> YOUR_SERVER_IP`.
Caddy will fetch the HTTPS certificate automatically once DNS has propagated.
(Set the matching domain in the `Caddyfile`.)

## Start everything

```bash
docker compose up -d --build
```

Check it's healthy:

```bash
docker compose ps         # all three should be "running"
docker compose logs -f    # follow logs (Ctrl-C to stop following)
```

Visit **https://YOUR_DOMAIN** — the site should load.

---

## Deploying updates later

Push your changes to GitHub, then on the server:

```bash
cd ~/quiethumans
./deploy.sh        # git pull + rebuild + restart
```

## Handy commands

```bash
docker compose ps                 # what's running
docker compose logs -f web        # API logs
docker compose logs -f pipeline   # crawler logs
docker compose restart web        # restart just the API
docker compose down               # stop everything
docker compose up -d              # start everything (no rebuild)
```
