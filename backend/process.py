"""Process web pages using LLM: score, extract profiles, and enrich with GitHub data."""


# Prompt for scoring pages 0-10 based on content about what the person builds or creates.
# Prompt template for AI to rate pages.
SCORE_PROMPT = r"""Score each page 0-10. We want pages that reveal what this person BUILDS or CREATES.

SCORING:
9-10: Specific project with description, demo, or source code. Technical deep-dive with original insight.
7-8: About/bio page listing multiple projects. Blog post showing something they built.
5-6: General "about me" with some work mentions. Resume with project names.
3-4: Blog post with opinions but no project content. Links page.
1-2: Contact page, empty page, navigation-only, legal/privacy.
0: Completely irrelevant (404, login, ads).

PAGES TO SCORE:
{pages}

Return JSON:
{{
    "scores": [
        {{"page": 1, "score": 8, "reason": "Lists 3 open-source tools with GitHub links"}},
        {{"page": 2, "score": 2, "reason": "Contact form only"}}
    ]
}}
"""

# Rule-based heuristic configuration: keywords and URL patterns for initial page scoring.
SCORE_CONFIG = {'keywords': ['\\b(i built|i created|i made|i developed|i designed|i wrote|i launched)\\b',
              '\\b(building|creating|making|developing|working on)\\b',
              '\\b(my project|my app|my tool|my game|my book|my product)\\b',
              '\\b(project|portfolio|case study|side project|side-project)\\b',
              '\\b(open source|open-source|github|repository)\\b',
              '\\b(app|application|tool|library|framework|plugin|extension)\\b',
              '\\b(startup|saas|product|mvp|beta)\\b',
              '\\b(api|sdk|cli|gui|database|backend|frontend)\\b',
              '\\b(python|javascript|typescript|rust|go|ruby|swift)\\b',
              '\\b(react|vue|angular|node|django|flask|rails)\\b',
              '\\b(game|music|art|design|writing|blog post|essay|book)\\b',
              '\\b(podcast|video|course|tutorial|newsletter)\\b'],
 'interesting_paths': ['^/projects?/?',
                       '^/work/?',
                       '^/portfolio/?',
                       '^/creations?/?',
                       '^/builds?/?',
                       '^/things/?',
                       '^/about/?',
                       '^/now/?',
                       '^/blog/[^/]+',
                       '^/posts?/[^/]+',
                       '^/writing/[^/]+',
                       '^/articles?/[^/]+']}

# Prompt template for AI to extract structured profile data from selected pages.
EXTRACT_PROMPT = r"""Extract a profile for a directory of interesting indie creators. Read ALL pages below to understand what this person actually does.

SITE TITLE: {title}

PAGES:
{pages}
{now_section}

FIELD RULES:

"hook" — The card headline. What you'd say if someone asked "what does this person do?" in an elevator.
FORMAT: "[Verb]s [specific thing]" — 3 to 8 words. No articles if possible.
EXAMPLES:
  "Makes generative art from git commits" (6 words)
  "Built habit tracker with 50k users" (6 words)
  "Writes newsletter about weird Wikipedia" (5 words)
  "Translates Japanese folk tales to Turkish" (6 words)
  "Runs a WordPress consultancy" (4 words - boring but honest)
NEVER: job titles ("Software Engineer"), buzzwords ("innovative solutions"), vague ("exploring intersections")

"one_liner" — One sentence that adds NEW information the hook doesn't have.
DO NOT just rephrase the hook. Add a specific detail: a project name, a number, a technology, a niche.
EXAMPLE: hook="Built habit tracker with 50k users" → one_liner="Shippy is a daily habit tracker used by 50k people, built solo in Rust."

"work_summary" — 2-3 sentences. Name specific projects. This is for people who want depth.
"projects" — Every real project you can find. Use actual names, not descriptions. Include URLs if found.
"current_focus" — What they're working on RIGHT NOW. Use /now page if available. null if unclear.
"creative_interests" — Be specific: "procedural music generation", not "technology".
"category" — Exactly ONE from: {categories}

Use family-friendly language. Avoid explicit or shocking terms even if academically accurate.

Return JSON:
{{
    "name": "Their full name or null if not found",
    "category": "one_word_from_list",
    "hook": "[Verb]s [specific thing] — 3 to 8 words",
    "one_liner": "One sentence with a detail the hook doesn't have",
    "work_summary": "2-3 sentences with project names",
    "projects": [
        {{
            "name": "Project Name",
            "description": "What it does concretely",
            "url": "url or null",
            "status": "active/completed/ongoing",
            "highlight": true
        }}
    ],
    "current_focus": "specific current work or null",
    "creative_interests": ["specific interest 1", "specific interest 2"],
    "unique_angle": "What makes their approach different in one sentence",
    "domains": ["indie games", "developer tools"],
    "makes": ["apps", "games", "essays"]
}}
"""

# Valid profile categories (AI must select exactly one).
CATEGORIES = ['software',
 'writing',
 'music',
 'visual',
 'games',
 'education',
 'hardware',
 'media',
 'research',
 'community',
 'other']


# ── Tools we borrow ──
import json
import re
import threading
import requests
from typing import Optional
from config import LOCAL_LLM_URL, LOCAL_LLM_KEY, LOCAL_LLM_MODEL
from dataclasses import dataclass
from config import render_prompt
from collections import Counter
from config import GITHUB_TOKEN


class LLMError(Exception):
    pass


class LocalProvider:
    """Client for calling self-hosted LLM (Gemma). Provides complete() and complete_json() methods."""

    def __init__(self, url: str = None, api_key: str = None, model: str = None):
        self.url = (url or LOCAL_LLM_URL).rstrip("/") + "/v1/chat/completions"
        self.api_key = api_key or LOCAL_LLM_KEY
        self.model = model or LOCAL_LLM_MODEL
        self.name = f"local/{self.model}"

    def complete(self, prompt: str, system: str = None, max_tokens: int = 500,
                 temperature: float = 0, json_mode: bool = False) -> dict:
        """Send prompt to LLM and return response."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        response = requests.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=300,  # local model can be slow on large prompts
        )

        if response.status_code != 200:
            raise LLMError(f"Local {response.status_code}: {response.text[:200]}")

        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return {"text": text, "usage": data.get("usage", {})}

    def complete_json(self, prompt: str, system: str = None, max_tokens: int = 500,
                      temperature: float = 0) -> dict:
        """Send prompt to LLM and parse response as JSON, with fallback cleanup."""
        result = self.complete(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
        )
        text = result["text"].strip()
        if "```" in text:
            text = re.sub(r"```json?\n?", "", text)
            text = re.sub(r"```\n?", "", text)
            text = text.strip()
        if not text.endswith("}"):
            open_braces = text.count("{") - text.count("}")
            open_brackets = text.count("[") - text.count("]")
            text = text.rstrip(",\n ")
            text += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        return json.loads(text)


_cheap_llm: Optional[LocalProvider] = None
_expensive_llm: Optional[LocalProvider] = None
_llm_lock = threading.Lock()


def get_cheap_llm() -> LocalProvider:
    """Get singleton LLM provider for scoring (cheap tier)."""
    global _cheap_llm
    if _cheap_llm is None:
        with _llm_lock:
            if _cheap_llm is None:
                _cheap_llm = LocalProvider()
    return _cheap_llm


def get_expensive_llm() -> LocalProvider:
    """Get singleton LLM provider for extraction (expensive tier)."""
    global _expensive_llm
    if _expensive_llm is None:
        with _llm_lock:
            if _expensive_llm is None:
                _expensive_llm = LocalProvider()
    return _expensive_llm


@dataclass
class ScoredPage:
    """Web page with heuristic and LLM scores."""
    url: str
    path: str
    title: str
    text: str
    text_length: int
    heuristic_score: float
    llm_score: Optional[float]
    llm_reason: Optional[str]
    is_priority: bool


def _load_score_config():
    """Fetch the keyword and page-address patterns we score against."""
    cfg = SCORE_CONFIG
    return cfg.get("keywords", []), cfg.get("interesting_paths", [])


def _calculate_heuristic_score(page) -> float:
    """Calculate heuristic score 0-100 based on URL patterns, keywords, content length, and title."""
    keywords, interesting_paths = _load_score_config()

    score = 0.0
    text_lower = page.text.lower()
    path_lower = page.path.lower()
    title_lower = page.title.lower() if page.title else ""

    # Path scoring (0-30 points)
    for pattern in interesting_paths:
        if re.match(pattern, path_lower):
            score += 30
            break

    # Priority path bonus
    if page.is_priority:
        score += 10

    # Keyword scoring (0-40 points)
    keyword_matches = 0
    for pattern in keywords:
        matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
        keyword_matches += min(matches, 3)

    keyword_score = min(keyword_matches * 4, 40)
    score += keyword_score

    # Content length scoring (0-15 points)
    if page.text_length > 5000:
        score += 15
    elif page.text_length > 2000:
        score += 12
    elif page.text_length > 1000:
        score += 10
    elif page.text_length > 500:
        score += 5

    # Title scoring (0-5 points)
    interesting_title_words = ["project", "built", "created", "portfolio", "work", "about"]
    for word in interesting_title_words:
        if word in title_lower:
            score += 5
            break

    return min(score, 100)


def heuristic_filter(pages: list, min_score: float = 20.0, max_candidates: int = 25) -> list[ScoredPage]:
    """Filter pages by heuristic score and return top candidates."""
    scored_pages = []

    for page in pages:
        h_score = _calculate_heuristic_score(page)

        if h_score >= min_score:
            scored_pages.append(ScoredPage(
                url=page.url,
                path=page.path,
                title=page.title,
                text=page.text,
                text_length=page.text_length,
                heuristic_score=h_score,
                llm_score=None,
                llm_reason=None,
                is_priority=page.is_priority,
            ))

    scored_pages.sort(key=lambda p: p.heuristic_score, reverse=True)
    return scored_pages[:max_candidates]


def _score_pages_batch(pages: list[ScoredPage], batch_size: int = 5) -> list[ScoredPage]:
    """Score a batch of pages using LLM."""

    if not pages:
        return pages

    # Build page excerpts
    page_excerpts = []
    for i, page in enumerate(pages):
        excerpt = page.text[:1500] if len(page.text) > 1500 else page.text
        page_excerpts.append(f"""
PAGE {i+1}:
URL: {page.url}
Title: {page.title or 'Untitled'}
Content excerpt:
{excerpt}
""")

    prompt = render_prompt(SCORE_PROMPT, pages="\n".join(page_excerpts))

    try:
        result = get_cheap_llm().complete_json(prompt, max_tokens=500, temperature=0)

        for score_item in result.get("scores", []):
            # The local model sometimes returns page/score as strings — coerce safely.
            try:
                page_num = int(score_item.get("page", 0)) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= page_num < len(pages):
                try:
                    pages[page_num].llm_score = float(score_item.get("score", 5))
                except (TypeError, ValueError):
                    pages[page_num].llm_score = 5
                pages[page_num].llm_reason = score_item.get("reason", "")

        return pages

    except Exception as e:
        print(f"  LLM scoring exception: {e}")
        return pages


def score_pages_with_llm(pages: list[ScoredPage], batch_size: int = 5) -> list[ScoredPage]:
    """Score all pages in batches using LLM."""
    result = []
    for i in range(0, len(pages), batch_size):
        batch = pages[i:i + batch_size]
        scored_batch = _score_pages_batch(batch, batch_size)
        result.extend(scored_batch)
    return result


def select_top_pages(
    pages: list[ScoredPage],
    n: int = 10,
    always_include: list[str] = None,
    max_chars_per_page: int = 4000,
) -> list[ScoredPage]:
    """Select top N pages, always including homepage, /about, /now. Rank by combined score."""
    always_include = always_include or ["/", "/about", "/now"]

    must_include = []
    candidates = []

    for page in pages:
        if len(page.text) > max_chars_per_page:
            page.text = page.text[:max_chars_per_page] + "\n...[truncated]"
            page.text_length = len(page.text)

        if page.path in always_include or page.path.rstrip("/") in always_include:
            must_include.append(page)
        else:
            candidates.append(page)

    def combined_score(p):
        llm = p.llm_score if p.llm_score is not None else 0
        heuristic = p.heuristic_score / 10
        return llm * 0.7 + heuristic * 0.3

    candidates.sort(key=combined_score, reverse=True)

    remaining_slots = n - len(must_include)
    selected = must_include + candidates[:max(0, remaining_slots)]
    return selected[:n]


def filter_and_score_pages(
    pages: list,
    max_final: int = 10,
    heuristic_min_score: float = 15.0,
    heuristic_max_candidates: int = 25,
) -> list[ScoredPage]:
    """Filter, score, and select top pages in one call."""
    print(f"  Stage 1: Heuristic filter ({len(pages)} pages)")

    candidates = heuristic_filter(pages, heuristic_min_score, heuristic_max_candidates)
    print(f"    -> {len(candidates)} candidates (score >= {heuristic_min_score})")

    if not candidates:
        return []

    print(f"  Stage 2: LLM scoring ({len(candidates)} candidates)")
    scored = score_pages_with_llm(candidates)

    with_llm_score = len([p for p in scored if p.llm_score is not None])
    print(f"    -> {with_llm_score} scored by LLM")

    print(f"  Stage 3: Selecting top {max_final} pages")
    selected = select_top_pages(scored, n=max_final)
    print(f"    -> {len(selected)} pages selected")

    return selected


def extract_person_data_from_pages(
    pages: list,
    homepage_title: str = None,
    now_page_text: str = None,
    max_chars_total: int = 30000,
) -> dict:
    """Extract structured profile data from pages using LLM."""

    page_sections = []
    total_chars = 0

    for page in pages:
        remaining = max_chars_total - total_chars
        if remaining <= 500:
            break

        page_text = page.text[:min(len(page.text), remaining - 100)]
        section = f"""
=== PAGE: {page.path} ===
Title: {page.title or 'Untitled'}
{page_text}
"""
        page_sections.append(section)
        total_chars += len(section)

    combined_content = "\n".join(page_sections)

    now_section = ""
    if now_page_text:
        now_section = f"""
=== /NOW PAGE (Current Focus) ===
{now_page_text[:4000]}
"""

    categories = ", ".join(CATEGORIES)

    prompt = render_prompt(
        EXTRACT_PROMPT,
        title=homepage_title or "Unknown",
        pages=combined_content,
        now_section=now_section,
        categories=categories,
    )

    try:
        result = get_expensive_llm().complete_json(prompt, max_tokens=3000, temperature=0)
        return result
    except Exception as e:
        print(f"  Extraction error: {e}")
        return {"error": str(e)}


_API = "https://api.github.com/users/{username}/repos"
_TOP_REPOS = 5
_TOP_LANGS = 8


def fetch_github_enrichment(username: str) -> dict:
    """Fetch top repositories and programming languages for a GitHub user."""
    if not username:
        return {}

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        resp = requests.get(
            _API.format(username=username),
            params={"per_page": 100, "sort": "pushed"},
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"  GitHub enrich request failed for {username}: {e}")
        return {}

    if resp.status_code != 200:
        print(f"  GitHub enrich {resp.status_code} for {username}: {resp.text[:120]}")
        return {}

    repos = resp.json()
    if not isinstance(repos, list):
        return {}

    own = [r for r in repos if not r.get("fork")]

    top = sorted(own, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:_TOP_REPOS]
    top_repos = [
        {
            "name": r.get("name"),
            "description": r.get("description"),
            "url": r.get("html_url"),
            "stars": r.get("stargazers_count", 0),
            "language": r.get("language"),
        }
        for r in top
    ]

    langs = Counter(r["language"] for r in own if r.get("language"))
    languages = [lang for lang, _ in langs.most_common(_TOP_LANGS)]

    return {"github_languages": languages, "github_top_repos": top_repos}
