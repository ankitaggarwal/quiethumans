"""API server for Discover Interesting Humans: data queries, curation UI, and static hosting."""

import re
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from database import IS_SQLITE
from database import get_connection_optional as get_db
from database import search_people as semantic_search, get_index_stats
from database import (
    get_pending_reviews, approve_person, reject_person, get_review_stats
)
from database import get_recent_events

STATIC_DIR = Path(__file__).parent / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"

app = FastAPI(
    title="Discover Interesting Humans",
    description="Discover interesting humans by what they build",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Stats(BaseModel):
    total_people: int
    with_work_summary: int
    indexed_for_search: int = 0



@app.get("/api/stats")
async def get_statistics(response: Response):
    """Return approval and indexing statistics."""
    response.headers["Cache-Control"] = "public, max-age=10"

    with get_db() as conn:
        if not conn:
            return Stats(total_people=0, with_work_summary=0, indexed_for_search=0)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM people WHERE status = 'approved'")
        total = cur.fetchone()[0]

        cur.execute("""SELECT COUNT(*) FROM people
            WHERE status = 'approved'
              AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)""")
        with_work = cur.fetchone()[0]

    indexed = 0
    try:
        index_stats = get_index_stats()
        if not index_stats.get("error"):
            indexed = index_stats.get("total_vectors", 0)
    except Exception:
        pass

    return Stats(total_people=total, with_work_summary=with_work, indexed_for_search=indexed)


@app.get("/api/crawl/stats")
async def crawl_stats():
    """Get comprehensive crawl queue and people statistics."""
    try:
        with get_db() as conn:
            if not conn:
                return {"error": "Database not connected"}

            cur = conn.cursor()

            cur.execute("""
                SELECT status, COUNT(*) FROM crawl_queue GROUP BY status
            """)
            queue = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute("""
                SELECT source, COUNT(*) FROM crawl_queue
                WHERE status = 'pending' GROUP BY source
                ORDER BY COUNT(*) DESC
            """)
            sources = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute("""
                SELECT status, COUNT(*) FROM people GROUP BY status
            """)
            people = {row[0]: row[1] for row in cur.fetchall()}

        return {
            "queue": {
                "pending": queue.get("pending", 0),
                "in_progress": queue.get("in_progress", 0),
                "crawled": queue.get("crawled", 0),
                "failed": queue.get("failed", 0),
            },
            "sources": sources,
            "people": {
                "total": sum(people.values()),
                "approved": people.get("approved", 0),
                "rejected": people.get("rejected", 0),
                "pending_review": people.get("pending_review", 0),
            }
        }
    except Exception as e:
        return {"error": str(e)}


class AddUrlsRequest(BaseModel):
    urls: list[str]
    source: str = "api"


@app.post("/api/queue/add")
async def add_urls_to_queue(request: AddUrlsRequest):
    """Add URLs to the crawl queue."""
    try:
        from database import add_to_queue
        added = add_to_queue(request.urls, request.source)
        return {"added": added, "total_submitted": len(request.urls)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/crawler/events")
async def crawler_events(limit: int = Query(20, ge=1, le=100)):
    """Get recent crawler events for live status updates."""
    try:
        events = get_recent_events(limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"error": str(e), "events": []}


# --- Review Queue ---

@app.get("/api/review/queue")
async def review_queue():
    """Get all people pending review."""
    try:
        pending = get_pending_reviews()
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/review/stats")
async def review_statistics():
    """Get review queue statistics."""
    try:
        stats = get_review_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


class ApproveRequest(BaseModel):
    score: int  # 1-10 interestingness score given by human


@app.post("/api/review/{person_id}/approve")
async def approve(person_id: int, request: ApproveRequest):
    """Approve a person with a human-given interestingness score."""
    try:
        if request.score < 1 or request.score > 10:
            return {"error": "Score must be between 1 and 10"}

        success = approve_person(person_id, request.score)
        if success:
            return {"status": "approved", "person_id": person_id, "score": request.score}
        else:
            return {"error": "Person not found"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/review/{person_id}/reject")
async def reject(person_id: int):
    """Reject a person - they won't appear in search results."""
    try:
        success = reject_person(person_id)
        if success:
            return {"status": "rejected", "person_id": person_id}
        else:
            return {"error": "Person not found"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/categories")
async def get_categories(response: Response):
    """Get list of categories with counts."""
    response.headers["Cache-Control"] = "public, max-age=60"
    with get_db() as conn:
        if not conn:
            return []

        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT category, COUNT(*) as count
            FROM people
            WHERE status = 'approved'
              AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)
              AND category IS NOT NULL
              AND category != 'other'
            GROUP BY category
            ORDER BY count DESC
        """)
        rows = cur.fetchall()

    return [{"name": row["category"], "count": row["count"]} for row in rows]


@app.get("/api/featured")
async def get_featured_person(response: Response):
    """Get person of the day — highest-scored approved person, rotates daily."""
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        today_seed = date.today().toordinal()

        with get_db() as conn:
            if not conn:
                return {"person": None}

            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM people
                WHERE status = 'approved'
                  AND interestingness_score IS NOT NULL
                  AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)
                ORDER BY interestingness_score DESC, id ASC
                LIMIT 50
            """)
            rows = cur.fetchall()

        if not rows:
            return {"person": None}

        pick = rows[today_seed % len(rows)]
        return {"person": _format_person(dict(pick))}
    except Exception as e:
        print(f"Featured person error: {e}")
        return {"person": None}


@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    semantic: bool = Query(True, description="Use semantic search")
):
    """Search for people by meaning (Qdrant) with keyword fallback."""
    results = []

    if semantic:
        try:
            # Over-fetch and deduplicate: a person may match via multiple points.
            all_matches = semantic_search(q, top_k=max(limit * 3, 30))
            if all_matches:
                matches = [m for m in all_matches if m.get("score", 0) >= 0.2]
                if not matches:
                    matches = all_matches[:5]  # Fallback to top 5 unfiltered

                # Deduplicate: keep best rank per person; track matched project if any.
                rank, matched_project = {}, {}
                for m in matches:
                    pid = m["id"]
                    if pid not in rank:
                        rank[pid] = len(rank)
                    proj = m.get("project")
                    if proj and proj.get("name") and pid not in matched_project:
                        matched_project[pid] = {
                            "name": proj.get("name"),
                            "url": proj.get("url"),
                            "summary": proj.get("summary"),
                        }
                person_ids = list(rank.keys())[:limit]

                with get_db() as conn:
                    if conn:
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        if IS_SQLITE:
                            in_clause = ",".join("%s" for _ in person_ids)
                            cur.execute(f"""
                                SELECT * FROM people WHERE id IN ({in_clause})
                                AND status = 'approved'
                                AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)
                            """, person_ids)
                        else:
                            cur.execute("""
                                SELECT * FROM people WHERE id = ANY(%s)
                                AND status = 'approved'
                                AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)
                            """, (person_ids,))
                        rows = cur.fetchall()

                        rows_sorted = sorted(rows, key=lambda r: rank.get(r["id"], 999))
                        results = []
                        for r in rows_sorted:
                            person = _format_person(dict(r))
                            person["matched_project"] = matched_project.get(r["id"])
                            results.append(person)
        except Exception as e:
            print(f"Semantic search failed: {e}")

    if not results:
        with get_db() as conn:
            if not conn:
                return []

            cur = conn.cursor(cursor_factory=RealDictCursor)
            pattern = f"%{q}%"
            cur.execute("""
                SELECT * FROM people
                WHERE status = 'approved'
                  AND (work_summary ILIKE %s OR one_liner ILIKE %s
                       OR name ILIKE %s OR current_focus ILIKE %s)
                LIMIT %s
            """, (pattern, pattern, pattern, pattern, limit))
            rows = cur.fetchall()
            results = [_format_person(dict(r)) for r in rows]

    return results


@app.get("/api/discover")
async def discover_random(
    response: Response,
    limit: int = Query(24, ge=1, le=50),
    offset: int = Query(0, ge=0),
    seed: int = Query(None, description="Random seed for consistent pagination"),
    category: str = Query(None, description="Filter by category")
):
    """Return a randomized page of approved people, optionally filtered by category."""
    response.headers["Cache-Control"] = "public, max-age=30"
    try:
        with get_db() as conn:
            if not conn:
                return {"people": [], "has_more": False, "total": 0}

            cur = conn.cursor(cursor_factory=RealDictCursor)

            where_clause = """
                WHERE status = 'approved'
                  AND (work_summary IS NOT NULL OR one_liner IS NOT NULL)
            """
            params = []
            if category:
                where_clause += " AND category = %s"
                params.append(category)

            # Use COUNT(*) AS count alias for consistent column naming across SQLite and Postgres.
            cur.execute(f"SELECT COUNT(*) AS count FROM people {where_clause}", params)
            total = cur.fetchone()["count"]

            if seed is not None and not IS_SQLITE:
                cur.execute("SELECT setseed(%s)", (seed / 2147483647,))

            cur.execute(f"""
                SELECT * FROM people
                {where_clause}
                ORDER BY RANDOM()
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = cur.fetchall()

        people = [_format_person(dict(p)) for p in rows]
        has_more = offset + len(people) < total

        return {
            "people": people,
            "has_more": has_more,
            "total": total,
            "offset": offset
        }
    except Exception as e:
        print(f"Discover error: {e}")
        return {"people": [], "has_more": False, "total": 0}


def _sanitize_content(text: str) -> str:
    """Replace explicit language with neutral alternatives."""
    if not text:
        return text

    replacements = [
        (r'\brape\b', 'abduction'),
        (r'\bRape\b', 'Abduction'),
        (r'\braped\b', 'abducted'),
        (r'\braping\b', 'abducting'),
        (r'\bkill\s+yourself\b', 'give up'),
        (r'\bsuicide\b', 'self-harm'),
        (r'\bmurder\b', 'crime'),
        (r'\bslut\b', '[removed]'),
        (r'\bwhore\b', '[removed]'),
    ]

    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def _format_person(p: dict) -> dict:
    """Extract and sanitize person fields for API response."""
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "homepage_url": p.get("homepage_url"),
        "now_page_url": p.get("now_page_url"),
        "hook": _sanitize_content(p.get("hook")),
        "work_summary": _sanitize_content(p.get("work_summary")),
        "one_liner": _sanitize_content(p.get("one_liner")),
        "unique_angle": _sanitize_content(p.get("unique_angle")),
        "current_focus": _sanitize_content(p.get("current_focus")),
        "category": p.get("category") or "other",
        "projects": p.get("projects") or [],
        "creative_interests": p.get("creative_interests") or [],
        "domains": p.get("domains") or [],
        "makes": p.get("makes") or [],
    }


# Mount MCP server before static file handler to prevent catch-all from blocking /mcp.
from mcp_server import build_mcp_app
_mcp_app = build_mcp_app()
if _mcp_app is not None:
    app.mount("/mcp", _mcp_app)

# Serve static files if available; fallback to index.html for client-side routing.
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/review")
    async def serve_review():
        """Serve the review queue UI."""
        return FileResponse(STATIC_DIR / "review.html")

    @app.get("/crawl")
    async def serve_crawl():
        """Serve the crawl status page."""
        return FileResponse(STATIC_DIR / "crawl.html")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {"message": "Discover Interesting Humans API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
