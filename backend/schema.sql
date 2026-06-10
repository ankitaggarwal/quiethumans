-- quiethumans Postgres schema.
-- The app auto-creates these tables on SQLite, but NOT on Postgres (it only
-- auto-creates crawler_events). Run this once against a fresh Postgres DB:
--     psql "$DATABASE_URL" -f backend/schema.sql
-- Safe to re-run: every statement uses IF NOT EXISTS.

-- People discovered by the crawler. Saved as 'pending_review'; promoted to
-- 'approved' (or 'rejected') during curation.
CREATE TABLE IF NOT EXISTS people (
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
    status                 TEXT DEFAULT 'pending_review',
    interestingness_score  INTEGER,
    review_reason          TEXT,
    review_highlights      JSONB,
    review_red_flags       JSONB,
    score_breakdown        JSONB,
    reviewed_by            TEXT,
    reviewed_at            TIMESTAMPTZ,
    crawled_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    created_at             TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_people_status ON people(status);

-- Review columns added after the original schema; bring older databases up to date.
ALTER TABLE people ADD COLUMN IF NOT EXISTS review_reason TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS review_highlights JSONB;
ALTER TABLE people ADD COLUMN IF NOT EXISTS review_red_flags JSONB;
ALTER TABLE people ADD COLUMN IF NOT EXISTS score_breakdown JSONB;

-- The crawl to-do list.
CREATE TABLE IF NOT EXISTS crawl_queue (
    url            TEXT PRIMARY KEY,
    source         TEXT,
    status         TEXT DEFAULT 'pending',
    attempts       INTEGER DEFAULT 0,
    priority       INTEGER DEFAULT 0,
    last_attempt   TIMESTAMPTZ,
    error_message  TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_crawl_queue_status ON crawl_queue(status);

-- Rolling activity log that powers the live crawl feed.
CREATE TABLE IF NOT EXISTS crawler_events (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ DEFAULT now(),
    event_type  VARCHAR(50) NOT NULL,
    url         TEXT NOT NULL,
    message     TEXT,
    details     JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_crawler_events_created ON crawler_events(created_at DESC);

-- A person's candidate creations, held between crawl and curation.
CREATE TABLE IF NOT EXISTS staged_projects (
    id            BIGSERIAL PRIMARY KEY,
    person_id     BIGINT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    homepage_url  TEXT,
    name          TEXT,
    url           TEXT,
    project_type  TEXT,
    summary       TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_staged_projects_person ON staged_projects(person_id);
