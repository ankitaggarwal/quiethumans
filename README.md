# quiethumans

A search engine that discovers interesting indie creators by crawling their personal
websites — focused on people who *build real things* on their own domain, not on
follower counts or job titles.

It crawls personal sites, uses a self-hosted LLM to classify and extract structured
profiles, curates the results (keeping only people who make distinctive things), and
serves them through semantic search.

## How it works

```
10 sources → crawl queue → [classify → crawl → extract → save] → Postgres
                                                                    │
                                              curate (approve/reject) ── MCP / review UI
                                                                    │
                                          approved people + creations → Qdrant → search
```

1. **Discovery** — pull candidate URLs from curated directories, webrings, Hacker News,
   Reddit, and GitHub lists into a Postgres queue.
2. **Crawl** — classify whether a URL is a real personal site (cheap heuristics first, LLM
   for edge cases), then crawl the useful pages (about, projects, now, blog).
3. **Extract** — score the pages and extract a structured profile (name, hook, projects,
   interests), plus the person's *creations* filtered for genuine creative work.
4. **Curate** — the pipeline makes no keep/reject decision; everyone is saved as
   `pending_review`. Approval happens afterwards via a token-gated MCP server or a review
   UI. Approving indexes the person and their creations into the vector store.
5. **Retrieve** — semantic search over approved people and their creations, so a query
   returns the right person *and* the specific work that matched.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design rationale and [SCHEMA.md](SCHEMA.md)
for the data model.

## Stack

- **Backend:** Python + FastAPI
- **Frontend:** React + Vite
- **Database:** PostgreSQL (SQLite supported for local development)
- **Vector search:** Qdrant (cosine, 768-dim embeddings)
- **LLM + embeddings:** a self-hosted, OpenAI-compatible endpoint

## Layout

```
backend/
  config.py       settings and secrets (from environment)
  discovery.py    source crawlers + queue replenishment
  crawler.py      URL filtering, personal-site classification, page crawling
  process.py      LLM client, page scoring, profile extraction, GitHub enrichment
  projects.py     extraction of a person's genuine creations
  database.py     Postgres/SQLite CRUD, queue, Qdrant indexing, event log
  mcp_server.py   token-gated MCP server for curation + text edits
  pipeline.py     orchestrator / CLI entry point
  api.py          FastAPI server (search, discover, review; serves the frontend; mounts /mcp)
frontend/         React app + static review/crawl pages
```

## Running locally

Requires Python 3.12+ and Node 20+.

**Backend**
```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in your values

# Local dev can use SQLite — set DATABASE_URL=sqlite:///quiethumans.db in .env
.venv/bin/python -m pipeline --url https://example.com   # process a single URL
.venv/bin/python -m pipeline --continuous                # crawl continuously
.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000     # API (+ built frontend, + /mcp)
```

**Frontend**
```bash
cd frontend
npm install
npm run dev      # dev server on :5173, proxies /api to the backend on :8000
npm run build    # production build
```

## Configuration

All configuration comes from the environment; see [`backend/.env.example`](backend/.env.example)
for the full list (`DATABASE_URL`, `QDRANT_URL/KEY/COLLECTION`, `LOCAL_LLM_URL/KEY/MODEL`,
`GITHUB_TOKEN`, `MCP_TOKEN`). The MCP server is disabled unless `MCP_TOKEN` is set.

## License

MIT — see [LICENSE](LICENSE).
