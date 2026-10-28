# Deploying the Research Desk (free tier)

Target from the plan: the backend and data on an **Oracle Cloud Always Free** VM, the Next.js UI on **Vercel**. Nothing here has been deployed yet; these are the steps, checked locally with the same Docker image.

## 1. Backend on an Oracle Always Free VM

Use an Ampere A1 shape (up to 4 OCPUs / 24 GB RAM free). The embedding and reranker models need about 2 GB of RAM, and the index grows with the corpus.

```bash
# on the VM (Ubuntu): Docker + compose plugin
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
git clone <your repo> ai-research-desk && cd ai-research-desk
cp .env.example .env     # set SEC_USER_AGENT, LLM_API_KEY, and CORS_ORIGINS=https://<your-app>.vercel.app
```

Build the data on the VM (or copy `data/` over with `rsync`):

```bash
docker compose --profile app run --rm api desk ingest --tickers sp100 --since 2024-01-01
docker compose --profile app run --rm api desk facts --tickers sp100
docker compose --profile app run --rm api desk risk-graph --tickers sp100 --since 2022-01-01
docker compose --profile app up -d api      # serves on port 8011
curl localhost:8011/api/health
```

The first search embeds the whole corpus into `data/qdrant` (CPU-bound: about 46 min per 13K chunks on a laptop), so warm it once before sharing the URL: `curl "localhost:8011/api/search?q=revenue&k=1"`.

**HTTPS.** Browsers block a Vercel (https) page from calling a plain-http API. Put Caddy in front, which gets a free Let's Encrypt certificate:

```
# /etc/caddy/Caddyfile
api.<your-domain> {
    reverse_proxy localhost:8011
}
```

Open ports 80 and 443 in both the OCI security list and the VM firewall (`sudo iptables` / `ufw`). Don't expose 8011 directly.

## 2. Front end on Vercel

- Import the repo, and set **Root Directory** to `frontend`.
- Environment variable: `NEXT_PUBLIC_API_URL=https://api.<your-domain>`.
- Back on the VM, set `CORS_ORIGINS` in `.env` to the Vercel URL, then `docker compose --profile app up -d api`.

## 3. Before making it public

- **Rate limits.** `POST /api/research` spends LLM quota (~5 calls per report) and has no auth. Add an API key or a per-IP limit before sharing the URL, or the free-tier quota will run out.
- **Secrets.** `.env` stays on the VM only. It is git-ignored and excluded from the Docker image (`.dockerignore`).
- **Disclaimer.** The UI already states "research only, not investment advice"; keep it.
