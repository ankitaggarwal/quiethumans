# Data model

quiethumans uses two stores:

- **PostgreSQL** — the source of truth: people, the crawl queue, the activity
  log, and staged creations. (Local development can use SQLite instead via a
  `sqlite:///` `DATABASE_URL`; the application creates the SQLite schema
  automatically. The DDL below is the canonical Postgres form.)
- **Qdrant** — the vector index used for semantic search. Only *approved*
  people and their creations are indexed here.

---

## PostgreSQL schema

```sql
-- People discovered by the crawler. Saved as 'pending_review'; promoted to
-- 'approved' (or 'rejected') during curation. JSON-typed columns hold lists
-- or small structured records.
CREATE TABLE people (
    id                     BIGSERIAL PRIMARY KEY,
    homepage_url           TEXT UNIQUE NOT NULL,
    now_page_url           TEXT,
    name                   TEXT,
    hook                   TEXT,
    work_summary           TEXT,
    one_liner              TEXT,
    unique_angle           TEXT,
    current_focus          TEXT,
    category               TEXT,
    projects               JSONB,
    creative_interests     JSONB,
    domains                JSONB,
    makes                  JSONB,
    github_username        TEXT,
    github_languages       JSONB,
    github_top_repos       JSONB,
    social_links           JSONB,
    status                 TEXT DEFAULT 'pending_review',  -- pending_review | approved | rejected
    interestingness_score  INTEGER,                        -- 1-10, set at approval
    reviewed_by            TEXT,
    reviewed_at            TIMESTAMPTZ,
    crawled_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    created_at             TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_people_status ON people(status);

-- The crawl to-do list.
CREATE TABLE crawl_queue (
    url            TEXT PRIMARY KEY,
    source         TEXT,                       -- which source the URL came from
    status         TEXT DEFAULT 'pending',     -- pending | in_progress | crawled | failed
    attempts       INTEGER DEFAULT 0,
    priority       INTEGER DEFAULT 0,
    last_attempt   TIMESTAMPTZ,
    error_message  TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_crawl_queue_status ON crawl_queue(status);

-- Rolling activity log that powers the live crawl feed (kept to ~100 rows).
CREATE TABLE crawler_events (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ DEFAULT now(),
    event_type  VARCHAR(50) NOT NULL,          -- started | classified | crawled | extracted | saved | error | ...
    url         TEXT NOT NULL,
    message     TEXT,
    details     JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_crawler_events_created ON crawler_events(created_at DESC);

-- A person's candidate creations, held between crawl and curation. On approval
-- they are embedded into Qdrant and deleted from here; on rejection, just deleted.
CREATE TABLE staged_projects (
    id            BIGSERIAL PRIMARY KEY,
    person_id     BIGINT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    homepage_url  TEXT,
    name          TEXT,
    url           TEXT,
    project_type  TEXT,
    summary       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_staged_projects_person ON staged_projects(person_id);
```

---

## Qdrant collection

- **Vectors:** 768 dimensions, **cosine** distance (matches the embedding model).
- Only approved people are indexed. Each person produces **one "person" point**
  plus **one "project" point per kept creation**, so a search can return the
  person and the specific work that matched.

**Person point**
- `id`: the person's integer id (matches `people.id`).
- vector: embedding of one-liner + work summary + current focus + top projects + interests.
- payload:
  ```json
  {
    "kind": "person",
    "person_id": 123,
    "name": "...",
    "one_liner": "...",
    "homepage_url": "https://..."
  }
  ```

**Project point**
- `id`: a UUID (so it never collides with person ids).
- vector: embedding of the creation's name + summary.
- payload:
  ```json
  {
    "kind": "project",
    "person_id": 123,
    "person_name": "...",
    "homepage_url": "https://...",
    "project_name": "...",
    "project_url": "https://...",
    "project_summary": "...",
    "project_type": "software"
  }
  ```

At search time, both point kinds carry `person_id`, so hits are de-duplicated to
the person; a project hit additionally surfaces the matched creation.
