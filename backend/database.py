"""Database layer with support for SQLite (dev) and Postgres (prod).

Manages people profiles, crawl queue, embeddings/search, and event logging.
"""

import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, unquote

import requests
import psycopg2
from psycopg2.extras import RealDictCursor

from config import (
    DATABASE_URL, LOCAL_LLM_URL, LOCAL_LLM_KEY,
    QDRANT_URL, QDRANT_KEY, QDRANT_COLLECTION,
)

# Connection backends: SQLite (dev) via "sqlite:///file.db", Postgres (prod) via psycopg2.
# SQL uses Postgres style; SQLite adapter translates compatible parts (%s, ILIKE, NOW(), FOR UPDATE).
# Postgres-specific constructs (INTERVAL, ANY, setseed) are conditional on IS_SQLITE.

import re as _re
import sqlite3

IS_SQLITE = DATABASE_URL.startswith("sqlite")


def parse_db_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": unquote(parsed.password) if parsed.password else None,
        "sslmode": "require",
    }


# SQLite local backend

sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))
sqlite3.register_converter("timestamp", lambda b: datetime.fromisoformat(b.decode()))


def _sqlite_path() -> str:
    return DATABASE_URL.split("://", 1)[1].lstrip("/") or "quiethumans.db"


def _translate(sql: str) -> str:
    """Rewrite the portable Postgres-isms to their SQLite equivalents."""
    sql = sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP")
    sql = sql.replace(" FOR UPDATE SKIP LOCKED", "").replace(" NULLS LAST", "")
    return _re.sub(r"\bILIKE\b", "LIKE", sql)


class _Cursor:
    """SQLite cursor wrapper that translates Postgres-style SQL."""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(_translate(sql), params)
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _Conn:
    """SQLite connection wrapper for psycopg2 compatibility."""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, cursor_factory=None):
        return _Cursor(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    homepage_url TEXT UNIQUE NOT NULL,
    now_page_url TEXT,
    name TEXT, hook TEXT, work_summary TEXT, one_liner TEXT,
    unique_angle TEXT, current_focus TEXT, category TEXT,
    projects TEXT, creative_interests TEXT, domains TEXT, makes TEXT,
    github_username TEXT, github_languages TEXT, github_top_repos TEXT,
    social_links TEXT,
    status TEXT DEFAULT 'pending_review',
    interestingness_score INTEGER,
    review_reason TEXT, review_highlights TEXT, review_red_flags TEXT,
    reviewed_by TEXT, reviewed_at timestamp, score_breakdown TEXT,
    crawled_at timestamp, updated_at timestamp,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS crawl_queue (
    url TEXT PRIMARY KEY,
    source TEXT,
    status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    last_attempt timestamp,
    error_message TEXT,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS crawler_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp timestamp DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL, url TEXT NOT NULL, message TEXT, details TEXT,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS staged_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    homepage_url TEXT,
    name TEXT, url TEXT, project_type TEXT, summary TEXT,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_staged_projects_person ON staged_projects(person_id);
"""
_SCHEMA_READY = False


def _connect_sqlite():
    global _SCHEMA_READY
    conn = sqlite3.connect(_sqlite_path(), detect_types=sqlite3.PARSE_DECLTYPES, timeout=30)
    conn.row_factory = sqlite3.Row  # rows behave as both dicts and tuples
    conn.execute("PRAGMA journal_mode=WAL")
    if not _SCHEMA_READY:
        conn.executescript(_SCHEMA)
        conn.commit()
        _SCHEMA_READY = True
    return _Conn(conn)


@contextmanager
def get_connection():
    if IS_SQLITE:
        conn = _connect_sqlite()
        try:
            yield conn
        finally:
            conn.close()
        return
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    params = parse_db_url(DATABASE_URL)
    # Retry a couple of times — a cloud Postgres can briefly refuse connections.
    for attempt in range(3):
        try:
            conn = psycopg2.connect(**params)
            try:
                yield conn
            finally:
                conn.close()
            return
        except psycopg2.OperationalError:
            if attempt < 2:
                import time
                time.sleep(attempt + 1)
                continue
            raise


@contextmanager
def get_connection_optional():
    if IS_SQLITE:
        conn = _connect_sqlite()
        try:
            yield conn
        finally:
            conn.close()
        return
    if not DATABASE_URL:
        yield None
        return
    conn = psycopg2.connect(**parse_db_url(DATABASE_URL))
    try:
        yield conn
    finally:
        conn.close()


def normalize_domain(url: str) -> str:
    """Canonical domain: strips scheme, www, port, path."""
    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc or parsed.path.split("/")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split(":")[0]
    except Exception:
        return url


# Embeddings and vector search via Qdrant.
# An embedding is a 768-dimensional vector capturing semantic meaning.
# Different "kind" prompts for documents vs. queries optimize vector quality.

EMBED_MODEL = "embeddinggemma"
EMBED_DIM = 768
_EMBED_URL = LOCAL_LLM_URL.rstrip("/") + "/v1/embeddings"


def _embed(text: str, kind: str = "document") -> Optional[list]:
    """Embed text to a 768-dim vector. Returns None on failure."""
    prompt = f"title: none | text: {text}" if kind == "document" else f"task: search result | query: {text}"
    try:
        resp = requests.post(
            _EMBED_URL,
            headers={"Authorization": f"Bearer {LOCAL_LLM_KEY}", "Content-Type": "application/json"},
            json={"model": EMBED_MODEL, "input": prompt},
            timeout=60,
        )
    except requests.RequestException as e:
        print(f"  Embedding request failed: {e}")
        return None
    if resp.status_code != 200:
        print(f"  EmbeddingGemma error {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json()["data"][0]["embedding"]


def _qdrant(method: str, path: str, **kwargs):
    headers = {"api-key": QDRANT_KEY, "Content-Type": "application/json"}
    return requests.request(method, QDRANT_URL.rstrip("/") + path, headers=headers, timeout=30, **kwargs).json()


def _col() -> str:
    from urllib.parse import quote
    return quote(QDRANT_COLLECTION, safe="")


def ensure_collection():
    """Create the Qdrant collection if missing."""
    if not QDRANT_KEY:
        return
    cols = _qdrant("GET", "/collections")
    existing = [c["name"] for c in cols.get("result", {}).get("collections", [])]
    if QDRANT_COLLECTION not in existing:
        result = _qdrant("PUT", f"/collections/{_col()}",
                         json={"vectors": {"size": EMBED_DIM, "distance": "Cosine"}})
        print(f"  Created Qdrant collection '{QDRANT_COLLECTION}': {result.get('status')}")


def upsert_person_embedding(person_id: int, text: str, metadata: dict):
    """Embed and store an approved person's profile in Qdrant."""
    if not text or len(text.strip()) < 10:
        return
    if not LOCAL_LLM_KEY or not QDRANT_KEY:
        return
    vector = _embed(text.strip(), kind="document")
    if not vector:
        print(f"  Embedding failed for person {person_id}")
        return
    result = _qdrant("PUT", f"/collections/{_col()}/points", json={
        "points": [{
            "id": person_id,
            "vector": vector,
            "payload": {
                "kind": "person",
                "person_id": person_id,
                "name": metadata.get("name"),
                "one_liner": metadata.get("one_liner"),
                "homepage_url": metadata.get("homepage_url"),
            },
        }],
        "wait": True,
    })
    if result.get("status") != "ok":
        print(f"  Qdrant upsert error for {person_id}: {result}")


def search_people(query: str, top_k: int = 10, filters: dict = None) -> list:
    """Semantic search: embed query and return best matching people."""
    if not LOCAL_LLM_KEY or not QDRANT_KEY:
        return []
    vector = _embed(query.strip(), kind="query")
    if not vector:
        return []
    result = _qdrant("POST", f"/collections/{_col()}/points/search",
                     json={"vector": vector, "limit": top_k, "with_payload": True})

    hits = []
    for h in result.get("result", []):
        pl = h.get("payload", {})
        # Person and project points both carry person_id; projects also carry project metadata.
        person_id = pl.get("person_id", h["id"])
        is_project = pl.get("kind") == "project"
        hits.append({
            "id": person_id,
            "score": h["score"],
            "kind": pl.get("kind", "person"),
            "name": pl.get("person_name") or pl.get("name"),
            "one_liner": pl.get("one_liner"),
            "homepage_url": pl.get("homepage_url"),
            "project": {
                "name": pl.get("project_name"),
                "url": pl.get("project_url"),
                "summary": pl.get("project_summary"),
                "type": pl.get("project_type"),
            } if is_project else None,
        })
    return hits


def delete_person_embedding(person_id: int):
    if not QDRANT_KEY:
        return
    _qdrant("POST", f"/collections/{_col()}/points/delete", json={"points": [person_id]})


def get_index_stats() -> dict:
    if not QDRANT_KEY:
        return {"error": "QDRANT_KEY not set"}
    try:
        result = _qdrant("GET", f"/collections/{_col()}")
        if "result" not in result:
            return {"error": result.get("status", "unknown error")}
        return {"total_vectors": result["result"].get("points_count", 0)}
    except Exception as e:
        return {"error": str(e)}


# Crawl queue management.
# URL states: pending, in_progress, crawled, failed.

def add_to_queue(urls: list[str], source: str = "nownownow") -> int:
    """Add URLs to queue, skipping duplicates. Returns count of newly added."""
    added = 0
    with get_connection() as conn:
        cur = conn.cursor()
        for url in urls:
            try:
                cur.execute(
                    "INSERT INTO crawl_queue (url, source, status) VALUES (%s, %s, 'pending') "
                    "ON CONFLICT (url) DO NOTHING", (url, source))
                if cur.rowcount > 0:
                    added += 1
            except Exception as e:
                print(f"Error adding {url} to queue: {e}")
        conn.commit()
    return added


def get_pending_urls(limit: int = 50) -> list[str]:
    """Atomically claim and mark URLs as in_progress to prevent duplicate work."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE crawl_queue SET status = 'in_progress', last_attempt = NOW()
            WHERE url IN (
                SELECT url FROM crawl_queue WHERE status = 'pending' AND attempts < 3
                ORDER BY priority DESC, created_at ASC LIMIT %s FOR UPDATE SKIP LOCKED
            ) RETURNING url
        """, (limit,))
        rows = cur.fetchall()
        conn.commit()
    return [r[0] for r in rows]


def mark_url_crawled(url: str, success: bool = True, error: str = None):
    status = "crawled" if success else "failed"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE crawl_queue SET status = %s, attempts = attempts + 1, last_attempt = %s, "
            "error_message = %s WHERE url = %s AND status = 'in_progress'",
            (status, datetime.utcnow(), error, url))
        conn.commit()


def get_queue_stats() -> dict:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM crawl_queue GROUP BY status")
        return {r[0]: r[1] for r in cur.fetchall()}


def reset_stale_in_progress(stale_minutes: int = 30) -> int:
    """Reset stalled in_progress URLs back to pending. Returns count reset."""
    with get_connection() as conn:
        cur = conn.cursor()
        if IS_SQLITE:
            cur.execute(
                "UPDATE crawl_queue SET status = 'pending' WHERE status = 'in_progress' "
                "AND last_attempt < datetime('now', ?)", (f"-{stale_minutes} minutes",))
        else:
            cur.execute(
                "UPDATE crawl_queue SET status = 'pending' WHERE status = 'in_progress' "
                "AND last_attempt < NOW() - INTERVAL '%s minutes'", (stale_minutes,))
        count = cur.rowcount
        conn.commit()
    return count


# People profile persistence.
# JSON fields are serialized to text; this list identifies them for deserialization.
_JSON_FIELDS = ["projects", "social_links", "github_languages", "github_top_repos",
                "creative_interests", "domains", "makes", "review_highlights", "review_red_flags"]


def check_duplicate_domain(homepage_url: str) -> Optional[dict]:
    """Check if person exists under same or www-variant domain."""
    domain = normalize_domain(homepage_url)
    if not domain:
        return None
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, homepage_url, name FROM people WHERE homepage_url = %s", (homepage_url,))
        exact = cur.fetchone()
        if exact:
            return dict(exact)
        cur.execute("SELECT id, homepage_url, name FROM people WHERE homepage_url ILIKE %s OR homepage_url ILIKE %s LIMIT 1",
                    (f"%://{domain}%", f"%://www.{domain}%"))
        similar = cur.fetchone()
        return dict(similar) if similar else None


def upsert_person(data: dict, skip_dedup: bool = False) -> int:
    """Insert or update person record. Returns person id."""
    data["updated_at"] = datetime.utcnow()
    for field in _JSON_FIELDS:
        if field in data and isinstance(data[field], (list, dict)):
            data[field] = json.dumps(data[field])
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM people WHERE homepage_url = %s", (data["homepage_url"],))
        existing = cur.fetchone()
        existing_url = data["homepage_url"]
        if not existing and not skip_dedup:
            dup = check_duplicate_domain(data["homepage_url"])
            if dup:
                existing = (dup["id"],)
                existing_url = dup["homepage_url"]
                print(f"  Dedup: {data['homepage_url']} matches existing {dup['homepage_url']}")
        if existing:
            person_id = existing[0]
            set_parts, values = [], []
            for key, value in data.items():
                if key != "homepage_url":
                    set_parts.append(f"{key} = %s")
                    values.append(value)
            values.append(existing_url)
            cur.execute(f"UPDATE people SET {', '.join(set_parts)} WHERE homepage_url = %s", values)
        else:
            data["crawled_at"] = datetime.utcnow()
            if not data.get("status"):
                data["status"] = "pending_review"
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            cur.execute(f"INSERT INTO people ({cols}) VALUES ({placeholders}) RETURNING id", list(data.values()))
            person_id = cur.fetchone()[0]
        conn.commit()
    return person_id


def _parse_json_fields(person: dict, fields: list) -> dict:
    for f in fields:
        if isinstance(person.get(f), str):
            try:
                person[f] = json.loads(person[f])
            except (json.JSONDecodeError, TypeError, ValueError):
                person[f] = []
    return person


def get_pending_reviews() -> list[dict]:
    """Fetch pending profiles, ordered by interestingness score."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, homepage_url, now_page_url, name, hook, work_summary, one_liner,
                   unique_angle, current_focus, projects, creative_interests,
                   domains, makes, interestingness_score, review_reason, created_at
            FROM people WHERE status = 'pending_review'
            ORDER BY interestingness_score DESC NULLS LAST, created_at DESC
        """)
        rows = cur.fetchall()
    return [_parse_json_fields(dict(r), ["projects", "creative_interests", "domains", "makes"]) for r in rows]


def index_approved_person(person_id: int, person_data: dict):
    """Embed and index approved person's profile in Qdrant."""
    try:
        parts = []
        if person_data.get("one_liner"):
            parts.append(person_data["one_liner"])
        if person_data.get("work_summary"):
            parts.append(person_data["work_summary"])
        if person_data.get("current_focus"):
            parts.append(f"Currently: {person_data['current_focus']}")
        projects = person_data.get("projects", [])
        if isinstance(projects, str):
            try:
                projects = json.loads(projects)
            except (json.JSONDecodeError, TypeError, ValueError):
                projects = []
        project_texts = [f"{p['name']}: {p['description']}" for p in projects[:5]
                         if isinstance(p, dict) and p.get("name") and p.get("description")]
        if project_texts:
            parts.append("Projects: " + "; ".join(project_texts))
        interests = person_data.get("creative_interests", [])
        if isinstance(interests, str):
            try:
                interests = json.loads(interests)
            except (json.JSONDecodeError, TypeError, ValueError):
                interests = []
        if interests:
            parts.append("Interests: " + ", ".join(interests[:10]))
        embedding_text = " | ".join(parts)
        if embedding_text:
            upsert_person_embedding(person_id, embedding_text, {
                "name": person_data.get("name"),
                "one_liner": person_data.get("one_liner"),
                "homepage_url": person_data.get("homepage_url"),
            })
            print(f"  Added to Qdrant: {person_data.get('name', 'Unknown')}")
    except Exception as e:
        print(f"  Warning: Failed to add to Qdrant: {e}")


# Staged projects: temporarily stored until person is approved or rejected.

def save_staged_projects(person_id: int, homepage_url: str, projects: list):
    """Store person's projects temporarily pending review."""
    if not projects:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        for p in projects:
            cur.execute(
                "INSERT INTO staged_projects (person_id, homepage_url, name, url, project_type, summary) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (person_id, homepage_url, p.get("name"), p.get("url"), p.get("type"), p.get("summary")))
        conn.commit()


def get_staged_projects(person_id: int) -> list[dict]:
    """Retrieve staged projects for a person."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, url, project_type, summary FROM staged_projects WHERE person_id = %s", (person_id,))
        return [dict(r) for r in cur.fetchall()]


def delete_staged_projects(person_id: int):
    """Delete person's staged projects."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM staged_projects WHERE person_id = %s", (person_id,))
        conn.commit()


def index_person_projects(person_id: int, person: dict, projects: list):
    """Embed and index each project individually in Qdrant."""
    import uuid
    if not LOCAL_LLM_KEY or not QDRANT_KEY:
        return
    points = []
    for p in projects:
        text = f"{p.get('name','')}. {p.get('summary','')}".strip()
        if len(text) < 10:
            continue
        vector = _embed(text, kind="document")
        if not vector:
            continue
        points.append({
            "id": str(uuid.uuid4()),
            "vector": vector,
            "payload": {
                "kind": "project",
                "person_id": person_id,
                "person_name": person.get("name"),
                "homepage_url": person.get("homepage_url"),
                "project_name": p.get("name"),
                "project_url": p.get("url"),
                "project_summary": p.get("summary"),
                "project_type": p.get("project_type"),
            },
        })
    if points:
        result = _qdrant("PUT", f"/collections/{_col()}/points", json={"points": points, "wait": True})
        if result.get("status") != "ok":
            print(f"  Qdrant project upsert error for person {person_id}: {result}")
        else:
            print(f"  Indexed {len(points)} creation(s) for {person.get('name', '?')}")


def _delete_person_points(person_id: int):
    """Delete person and all associated project vectors from Qdrant."""
    if not QDRANT_KEY:
        return
    _qdrant("POST", f"/collections/{_col()}/points/delete",
            json={"filter": {"must": [{"key": "person_id", "match": {"value": person_id}}]}})


# Approval and rejection decisions.

def approve_person(person_id: int, score: int) -> bool:
    """Approve person and index profile and projects. Returns success."""
    score = max(1, min(10, score))
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            UPDATE people SET status = 'approved', interestingness_score = %s, reviewed_at = %s
            WHERE id = %s
            RETURNING id, name, one_liner, work_summary, current_focus,
                      homepage_url, projects, creative_interests, domains, makes
        """, (score, datetime.utcnow(), person_id))
        row = cur.fetchone()
        if not row:
            return False
        conn.commit()

    # Embedding + Qdrant indexing is slow (one LLM round-trip per person and per
    # project, against a self-hosted endpoint). Do it off the request thread so
    # the MCP approve call returns immediately instead of hanging/disconnecting.
    threading.Thread(
        target=_index_approved_async, args=(person_id, dict(row)), daemon=True
    ).start()
    return True


def _index_approved_async(person_id: int, row: dict):
    """Index an approved person (profile + staged projects) in the background."""
    try:
        index_approved_person(person_id, row)
        staged = get_staged_projects(person_id)
        if staged:
            index_person_projects(person_id, row, staged)
        delete_staged_projects(person_id)
    except Exception as e:
        print(f"  Background indexing failed for person {person_id}: {e}")


def reject_person(person_id: int) -> bool:
    """Reject person, remove from search, delete staged projects. Returns success."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE people SET status = 'rejected', reviewed_at = %s WHERE id = %s",
                    (datetime.utcnow(), person_id))
        conn.commit()
        if cur.rowcount == 0:
            return False
    try:
        _delete_person_points(person_id)
    except Exception as e:
        print(f"  Warning: Failed to remove from Qdrant: {e}")
    delete_staged_projects(person_id)
    return True


def get_review_stats() -> dict:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM people WHERE status = 'pending_review'")
        pending = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM people WHERE status = 'approved'")
        approved = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM people WHERE status = 'rejected'")
        rejected = cur.fetchone()[0]
        recent = "datetime('now', '-1 day')" if IS_SQLITE else "NOW() - INTERVAL '24 hours'"
        cur.execute(f"SELECT COUNT(*) FROM people WHERE status = 'approved' AND reviewed_at > {recent}")
        approved_today = cur.fetchone()[0]
    return {"pending": pending, "approved": approved, "rejected": rejected, "approved_today": approved_today}


# Text fields the MCP server is allowed to rewrite.
_MCP_EDITABLE = {"hook", "one_liner", "work_summary", "current_focus", "unique_angle"}


def update_person_text(person_id: int, fields: dict, conn=None) -> dict:
    """Update whitelisted text fields. Returns updated row."""
    bad = set(fields) - _MCP_EDITABLE
    if bad:
        raise ValueError(f"Fields not editable: {sorted(bad)}. Allowed: {sorted(_MCP_EDITABLE)}")
    if not fields:
        raise ValueError("No fields to update")

    def _run(c):
        cur = c.cursor(cursor_factory=RealDictCursor)
        sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = %s"
        vals = list(fields.values()) + [datetime.utcnow(), person_id]
        cur.execute(f"UPDATE people SET {sets} WHERE id = %s RETURNING *", vals)
        return cur.fetchone()

    if conn is not None:
        return dict(_run(conn) or {})
    with get_connection() as c:
        row = _run(c)
        c.commit()
        return dict(row or {})


# Event logging for crawler activity.
# Recent events (max 100) populate the live feed on /crawl page.

MAX_EVENTS = 100


@dataclass
class CrawlerEvent:
    timestamp: str
    event_type: str
    url: str
    message: str
    details: Optional[dict] = None


def _ensure_events_table():
    if IS_SQLITE:
        return
    try:
        with get_connection_optional() as conn:
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS crawler_events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    event_type VARCHAR(50) NOT NULL,
                    url TEXT NOT NULL, message TEXT, details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crawler_events_created ON crawler_events(created_at DESC)")
            conn.commit()
    except Exception as e:
        print(f"Warning: Could not create crawler_events table: {e}")


def log_event(event_type: str, url: str, message: str, details: dict = None):
    event = CrawlerEvent(datetime.now(timezone.utc).isoformat(), event_type, url, message, details)
    try:
        with get_connection_optional() as conn:
            if not conn:
                return event
            cur = conn.cursor()
            cur.execute("INSERT INTO crawler_events (event_type, url, message, details) VALUES (%s, %s, %s, %s)",
                        (event_type, url, message, json.dumps(details) if details else None))
            cur.execute("DELETE FROM crawler_events WHERE id NOT IN "
                        "(SELECT id FROM crawler_events ORDER BY created_at DESC LIMIT %s)", (MAX_EVENTS,))
            conn.commit()
    except Exception as e:
        print(f"Warning: Could not log event: {e}")
    return event


def get_recent_events(limit: int = 20) -> list:
    try:
        with get_connection_optional() as conn:
            if not conn:
                return []
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT event_type, url, message, details, created_at AS timestamp "
                        "FROM crawler_events ORDER BY created_at DESC LIMIT %s", (limit,))
            return [{
                "event_type": r["event_type"], "url": r["url"], "message": r["message"],
                "details": r["details"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            } for r in cur.fetchall()]
    except Exception as e:
        print(f"Warning: Could not get events: {e}")
        return []


def _short_url(url: str) -> str:
    return urlparse(url).netloc or url[:30]


def log_started(url):                      return log_event("started", url, f"Started processing {_short_url(url)}")
def log_crawled(url, pages, chars):        return log_event("crawled", url, f"Crawled {pages} pages ({chars:,} chars)", {"pages": pages, "chars": chars})
def log_extracted(url, name, projects):    return log_event("extracted", url, f"Extracted: {name} ({projects} projects)", {"name": name, "projects": projects})
def log_saved(url, name, person_id):       return log_event("saved", url, f"Saved: {name} (ID: {person_id})", {"name": name, "person_id": person_id})
def log_error(url, error):                 return log_event("error", url, f"Error: {error[:100]}", {"error": error})


def log_classified(url, is_personal, reason):
    if is_personal:
        return log_event("classified", url, "Classified as personal site", {"is_personal": True})
    return log_event("skipped", url, f"Skipped: {reason[:50]}", {"is_personal": False, "reason": reason})


_ensure_events_table()
