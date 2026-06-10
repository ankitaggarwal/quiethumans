"""Web crawler for discovering and classifying personal sites.

Filters URLs, downloads and parses homepage content, crawls related pages,
and classifies whether a site belongs to a single individual."""


# LLM prompt for personal site classification
CLASSIFY_PROMPT = r"""We are building a directory of curious, independent creators — people who build things because they are genuinely interested, not just for corporate work.

Does this URL belong to ONE individual person who creates things (not a company, agency, or product)?

ACCEPT (is_personal = true):
- Personal site of a developer, designer, writer, artist, researcher, or maker
- Blog, portfolio, or project showcase clearly owned by one named person
- Solo founder whose site reads like a personal space (not a startup landing page)
- /now page, /about me, "I built X", "my projects" language
- Freelancer site where one individual is clearly the subject

REJECT (is_personal = false):
- Company, agency, consultancy, or team site (even if small)
- E-commerce store, SaaS marketing page, or product landing page
- Documentation site, technical reference, news/media site
- Link-in-bio, placeholder, or empty site
- Anonymous site with no identifiable person
- Site focused purely on selling services (e.g. "Hire me for $X/hour")

IMPORTANT: Be strict. When in doubt, return false. It is better to miss a good site than to include a company or content farm.

URL: {url}
CONTENT:
{content}

Return JSON:
{{"is_personal": true/false, "confidence": 0.0-1.0, "reason": "one sentence"}}
"""

# Rule-based classification patterns (applied before LLM)
CLASSIFY_CONFIG = {'min_content_length': 500,
 'reject_url_patterns': ['/login',
                         '/signup',
                         '/signin',
                         '/auth',
                         '/cart',
                         '/checkout',
                         '/shop',
                         '/api/',
                         '/docs/',
                         '/documentation/',
                         '/pricing',
                         '/plans',
                         '/careers',
                         '/jobs',
                         '/hiring',
                         '/support',
                         '/help-center',
                         '/terms',
                         '/privacy-policy',
                         '/products/',
                         '/services/'],
 'reject_content_patterns': [{'pattern': 'add to cart', 'category': 'e-commerce'},
                             {'pattern': 'buy now', 'category': 'e-commerce'},
                             {'pattern': 'checkout', 'category': 'e-commerce'},
                             {'pattern': 'shopping cart', 'category': 'e-commerce'},
                             {'pattern': 'free shipping', 'category': 'e-commerce'},
                             {'pattern': '\\$\\d+\\.\\d{2}', 'category': 'e-commerce'},
                             {'pattern': 'our team of \\d+', 'category': 'corporate'},
                             {'pattern': 'we are hiring', 'category': 'corporate'},
                             {'pattern': 'join our team', 'category': 'corporate'},
                             {'pattern': 'enterprise solution', 'category': 'corporate'},
                             {'pattern': 'request a demo', 'category': 'corporate'},
                             {'pattern': 'schedule a call', 'category': 'corporate'},
                             {'pattern': 'trusted by \\d+', 'category': 'corporate'},
                             {'pattern': '© \\d{4} .+ (inc|llc|ltd|corp)', 'category': 'corporate'},
                             {'pattern': 'api documentation', 'category': 'documentation'},
                             {'pattern': 'getting started guide', 'category': 'documentation'},
                             {'pattern': 'installation instructions', 'category': 'documentation'},
                             {'pattern': 'sdk reference', 'category': 'documentation'},
                             {'pattern': 'breaking news', 'category': 'news site'},
                             {'pattern': 'latest headlines', 'category': 'news site'},
                             {'pattern': 'subscribe to newsletter', 'category': 'news site'},
                             {'pattern': 'start your free trial', 'category': 'saas'},
                             {'pattern': 'pricing plans', 'category': 'saas'},
                             {'pattern': 'monthly billing', 'category': 'saas'},
                             {'pattern': 'per user/month', 'category': 'saas'}],
 'accept_content_patterns': [{'pattern': 'about me', 'category': 'personal intro'},
                             {'pattern': 'my name is \\w+', 'category': 'personal intro'},
                             {'pattern': "i('m| am) a (developer|designer|writer|engineer|creator)",
                              'category': 'personal intro'},
                             {'pattern': 'my (blog|projects|portfolio|work)',
                              'category': 'personal content'},
                             {'pattern': '/now page', 'category': 'has /now page'},
                             {'pattern': 'contact me at', 'category': 'personal contact'},
                             {'pattern': 'my twitter|my github|follow me',
                              'category': 'personal social'},
                             {'pattern': 'i built|i created|i made', 'category': 'personal work'}]}

# URL filtering rules
FILTERS = {'blocked_subdomain_hosts': ['wordpress.com',
                             'blogspot.com',
                             'blogger.com',
                             'tumblr.com',
                             'medium.com',
                             'substack.com',
                             'ghost.io',
                             'wixsite.com',
                             'squarespace.com',
                             'weebly.com',
                             'carrd.co',
                             'webflow.io',
                             'framer.website',
                             'netlify.app',
                             'vercel.app',
                             'herokuapp.com',
                             'glitch.me',
                             'pages.dev',
                             'workers.dev',
                             'fly.dev',
                             'railway.app',
                             'github.io',
                             'gitlab.io',
                             'codeberg.page',
                             'bitbucket.io',
                             'neocities.org',
                             'bearblog.dev',
                             'mataroa.blog',
                             'write.as',
                             'micro.blog',
                             'omg.lol',
                             'linktree.com',
                             'linktr.ee',
                             'bio.link',
                             'bento.me',
                             'about.me',
                             'notion.site',
                             'notion.so',
                             'hashnode.dev',
                             'dev.to',
                             'geocities.ws',
                             'angelfire.com',
                             'tripod.com',
                             'livejournal.com'],
 'skip_domains': ['google.com',
                  'youtube.com',
                  'facebook.com',
                  'twitter.com',
                  'x.com',
                  'instagram.com',
                  'linkedin.com',
                  'tiktok.com',
                  'reddit.com',
                  'amazon.com',
                  'ebay.com',
                  'apple.com',
                  'microsoft.com',
                  'github.com',
                  'gitlab.com',
                  'bitbucket.org',
                  'stackoverflow.com',
                  'stackexchange.com',
                  'wikipedia.org',
                  'wikimedia.org',
                  'news.ycombinator.com',
                  'ycombinator.com',
                  'nownownow.com',
                  'nytimes.com',
                  'wsj.com',
                  'bbc.com',
                  'cnn.com',
                  'techcrunch.com',
                  'theverge.com',
                  'wired.com',
                  'arstechnica.com',
                  'w3.org',
                  'schema.org',
                  'npmjs.com',
                  'pypi.org',
                  'dropbox.com',
                  'drive.google.com',
                  'docs.google.com',
                  'imgur.com',
                  'gfycat.com',
                  'giphy.com',
                  'v.redd.it',
                  'i.redd.it',
                  'preview.redd.it',
                  'streamable.com',
                  'twitch.tv',
                  'xn--sr8hvo.ws'],
 'blocked_domains': ['example.com', 'localhost'],
 'suspicious_tlds': ['.xyz', '.top', '.club', '.work', '.click'],
 'blocked_content_patterns': ['casino',
                              'gambling',
                              'porn',
                              'xxx',
                              'adult',
                              'viagra',
                              'cialis',
                              'crypto-invest',
                              'get-rich'],
 'max_redirects': 3}



import re
import time
import threading
import requests
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from config import get_headers, render_prompt


# ============================================================
# Polite, robust outbound fetching
# A single chokepoint for page GETs: respects robots.txt, rate-limits per host,
# and retries transient failures with backoff. All page fetches route through
# polite_get() so behaviour is consistent and the crawler is a good web citizen.
# ============================================================
CRAWL_DELAY_DEFAULT = 1.0   # min seconds between requests to the same host
ROBOTS_TIMEOUT = 10         # seconds to fetch robots.txt
FETCH_RETRIES = 2           # extra attempts after the first, on transient errors
FETCH_BACKOFF = 0.8         # base backoff seconds (doubles each retry)
_ROBOTS_UA = "quiethumans"  # token used for robots.txt rule matching
_RETRY_STATUS = (429, 500, 502, 503, 504)

_robots_cache: dict = {}    # host -> (RobotFileParser | None, crawl_delay | None)
_last_fetch: dict = {}      # host -> monotonic time the next request may start
_polite_lock = threading.Lock()


def _get_robots(scheme: str, host: str):
    """Fetch & cache robots.txt for a host. Fails open (allow) if unreachable."""
    with _polite_lock:
        if host in _robots_cache:
            return _robots_cache[host]
    rp, delay = None, None
    try:
        r = requests.get(f"{scheme}://{host}/robots.txt", headers=get_headers(), timeout=ROBOTS_TIMEOUT)
        if r.status_code == 200 and r.text:
            rp = robotparser.RobotFileParser()
            rp.parse(r.text.splitlines())
            try:
                delay = rp.crawl_delay(_ROBOTS_UA)
            except Exception:
                delay = None
        # Non-200 (404/401/...) => treat as no restrictions.
    except requests.RequestException:
        rp = None  # unreachable robots => allow
    with _polite_lock:
        _robots_cache[host] = (rp, delay)
    return rp, delay


def _await_host_slot(host: str, delay: float):
    """Space out requests to the same host. Reserves the next slot under the lock,
    then sleeps outside it so different hosts never block each other."""
    with _polite_lock:
        now = time.monotonic()
        start = max(now, _last_fetch.get(host, 0.0))
        _last_fetch[host] = start + delay
    wait = start - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def polite_get(url: str, timeout: int = 15, retries: int = FETCH_RETRIES):
    """robots-aware, rate-limited GET with retry/backoff. Returns a Response, or
    None if the host is unparseable, disallowed by robots.txt, or all retries fail."""
    parsed = urlparse(url)
    scheme, host = (parsed.scheme or "https"), parsed.netloc.lower()
    if not host:
        return None

    rp, robots_delay = _get_robots(scheme, host)
    try:
        if rp is not None and not rp.can_fetch(_ROBOTS_UA, url):
            return None  # disallowed by robots.txt
    except Exception:
        pass

    delay = max(CRAWL_DELAY_DEFAULT, robots_delay or 0.0)
    for attempt in range(retries + 1):
        _await_host_slot(host, delay)
        try:
            resp = requests.get(url, headers=get_headers(), timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            if attempt < retries:
                time.sleep(FETCH_BACKOFF * (2 ** attempt))
                continue
            return None
        if resp.status_code in _RETRY_STATUS and attempt < retries:
            time.sleep(FETCH_BACKOFF * (2 ** attempt))
            continue
        return resp
    return None


@dataclass
class FilterResult:
    """Result of URL filtering."""
    passed: bool
    reason: Optional[str] = None
    normalized_url: Optional[str] = None


# Known multi-part public suffixes, so apex domains like "example.co.uk" or
# "example.co.in" aren't mistaken for subdomains. Not exhaustive (no full PSL),
# just the common second-level ccTLDs we're likely to encounter.
MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk", "net.uk", "sch.uk", "ltd.uk", "plc.uk",
    "co.in", "net.in", "org.in", "gen.in", "firm.in", "ind.in", "ac.in", "edu.in", "gov.in",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au",
    "co.nz", "net.nz", "org.nz", "ac.nz",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "com.jp",
    "com.br", "net.br", "org.br",
    "co.za", "org.za", "web.za",
    "com.mx", "org.mx", "com.ar", "com.tw", "org.tw", "com.tr", "net.tr", "org.tr",
    "co.kr", "or.kr", "ne.kr", "com.cn", "net.cn", "org.cn",
    "co.il", "org.il", "net.il", "com.sg", "edu.sg", "com.hk", "org.hk",
    "co.id", "web.id", "or.id", "com.ph", "com.my", "com.vn", "co.th", "in.th",
}


class URLFilter:
    """Filters URLs based on domain and content heuristics."""

    def __init__(self, config: Optional[dict] = None):
        if config is None:
            config = self._load_config()

        filters = config.get("filters", {})
        self.blocked_subdomain_hosts = set(filters.get("blocked_subdomain_hosts", []))
        self.skip_domains = set(filters.get("skip_domains", []))
        self.blocked_domains = set(filters.get("blocked_domains", []))
        self.suspicious_tlds = set(filters.get("suspicious_tlds", []))
        self.blocked_content_patterns = filters.get("blocked_content_patterns", [])
        self.max_redirects = filters.get("max_redirects", 3)
        # Crawl only apex domains (and www). Reject all other subdomains
        # (blog.example.com, user.neocities.org, name.github.io, ...).
        self.reject_subdomains = filters.get("reject_subdomains", True)

    def _load_config(self) -> dict:
        return {"filters": FILTERS}

    def filter(self, url: str) -> FilterResult:
        """Filter a URL. Returns FilterResult with passed=True if URL should be kept."""
        url = url.strip().rstrip("/")
        if not url:
            return FilterResult(False, "Empty URL")

        try:
            parsed = urlparse(url)
        except Exception as e:
            return FilterResult(False, f"Invalid URL: {e}")

        if parsed.scheme not in ("http", "https"):
            return FilterResult(False, f"Invalid scheme: {parsed.scheme}")

        if not parsed.netloc:
            return FilterResult(False, "No host in URL")

        hostname = parsed.netloc.lower()

        url_lower = url.lower()
        for pattern in self.blocked_content_patterns:
            if pattern in url_lower:
                return FilterResult(False, f"Blocked pattern in URL: {pattern}")

        for blocked in self.blocked_domains:
            if hostname == blocked or hostname.endswith(f".{blocked}"):
                return FilterResult(False, f"Blocked domain: {blocked}")

        for skip in self.skip_domains:
            if hostname == skip or hostname.endswith(f".{skip}"):
                return FilterResult(False, f"Skipped domain: {skip}")

        is_subdomain, host = self._is_subdomain_of(hostname, self.blocked_subdomain_hosts)
        if is_subdomain:
            return FilterResult(False, f"Subdomain of platform: {host}")

        if re.match(r"^\d+\.\d+\.\d+\.\d+", hostname):
            return FilterResult(False, "IP address, not a domain")

        if self.reject_subdomains and self._is_plain_subdomain(hostname):
            return FilterResult(False, "Subdomain (only apex domains and www are crawled)")

        path = parsed.path.lower()
        skip_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".mp3", ".mp4", ".exe"]
        if any(path.endswith(ext) for ext in skip_extensions):
            return FilterResult(False, "Non-page file extension")

        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        return FilterResult(True, None, normalized)

    def _is_subdomain_of(self, hostname: str, hosts: set) -> Tuple[bool, Optional[str]]:
        for host in hosts:
            if hostname.endswith(f".{host}"):
                prefix = hostname[:-len(host)-1]
                if prefix and "." not in prefix:
                    return True, host
        return False, None

    def _is_plain_subdomain(self, hostname: str) -> bool:
        """True for any subdomain other than 'www' (e.g. blog.example.com,
        user.neocities.org). Apex domains and www.<apex> return False. Uses
        MULTI_PART_SUFFIXES so apex domains on ccTLDs like example.co.uk are kept."""
        host = hostname.split(":", 1)[0]  # drop any :port
        if host.startswith("www."):
            host = host[4:]
        labels = host.split(".")
        if len(labels) <= 2:
            return False
        # Registrable domain is 2 labels, or 3 when it ends in a known multi-part suffix.
        allowed = 3 if ".".join(labels[-2:]) in MULTI_PART_SUFFIXES else 2
        return len(labels) > allowed


_default_filter: Optional[URLFilter] = None


def is_crawlable(url: str) -> bool:
    """Convenience function: check if a URL passes all filters."""
    global _default_filter
    if _default_filter is None:
        _default_filter = URLFilter()
    return _default_filter.filter(url).passed


def extract_homepage(url: str) -> str:
    """Extract homepage URL from a deep link."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return url


def normalize_domain(url: str) -> str:
    """Normalize URL to canonical domain (strips www, port, path)."""
    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc or parsed.path.split('/')[0]
        if domain.startswith('www.'):
            domain = domain[4:]
        domain = domain.split(':')[0]
        return domain
    except Exception:
        return url


def crawl_homepage(url: str) -> dict:
    """Fetch and parse a homepage URL, extracting text, title, links, and social profiles."""
    result = {
        "homepage_url": url,
        "raw_text": "",
        "title": None,
        "links": [],
        "github_username": None,
        "social_links": {},
        "meta_description": None,
    }

    resp = polite_get(url, timeout=30)
    if resp is None:
        result["error"] = "fetch failed or blocked by robots.txt"
        return result
    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    content_type = resp.headers.get("content-type", "").lower()
    if content_type and "html" not in content_type:
        result["error"] = f"Not HTML: {content_type.split(';')[0]}"
        return result

    soup = BeautifulSoup(resp.text, "lxml")

    if soup.title:
        result["title"] = soup.title.get_text(strip=True)

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        result["meta_description"] = meta_desc["content"]

    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    main_content = soup.find("main") or soup.find("article") or soup.find("body")
    if main_content:
        result["raw_text"] = _clean_text_str(main_content.get_text(separator="\n"))

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if not href.startswith("http"):
            href = urljoin(url, href)

        result["links"].append({"url": href, "text": text})

        social = _detect_social_link(href)
        if social:
            result["social_links"][social["platform"]] = social["url"]
            if social["platform"] == "github" and social.get("username"):
                result["github_username"] = social["username"]

    return result


def _clean_text_str(text: str) -> str:
    """Normalize and truncate extracted text."""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > 50000:
        text = text[:50000] + "\n...[truncated]"

    return text


def _detect_social_link(url: str) -> Optional[dict]:
    """Extract social media platform and handle from URL."""
    patterns = {
        "github": (r"github\.com/([a-zA-Z0-9_-]+)", "username"),
        "twitter": (r"(?:twitter|x)\.com/([a-zA-Z0-9_]+)", "username"),
        "linkedin": (r"linkedin\.com/in/([a-zA-Z0-9_-]+)", "username"),
        "youtube": (r"youtube\.com/(?:@|c(?:hannel)?/)?([a-zA-Z0-9_-]+)", "channel"),
        "bluesky": (r"bsky\.app/profile/([a-zA-Z0-9.-]+)", "handle"),
        "mastodon": (r"(?!.*(?:youtube|twitter|x|github|linkedin)\.com)([a-zA-Z0-9.-]+)/@([a-zA-Z0-9_]+)", "handle"),
    }

    for platform, (pattern, _) in patterns.items():
        match = re.search(pattern, url)
        if match:
            result = {"platform": platform, "url": url}
            if platform == "github":
                result["username"] = match.group(1)
            return result

    return None


PRIORITY_PATHS = [
    "/projects", "/work", "/portfolio", "/works", "/creations",
    "/about", "/about-me", "/bio", "/me",
    "/blog", "/posts", "/writing", "/articles", "/notes",
    "/now", "/uses", "/setup", "/tools", "/colophon",
    "/cv", "/resume", "/experience",
]

SKIP_PATHS = [
    "/login", "/signup", "/signin", "/auth", "/register",
    "/cart", "/checkout", "/shop", "/store",
    "/api/", "/feed", "/rss", "/atom",
    "/wp-admin", "/wp-content", "/wp-includes",
    "/tag/", "/category/", "/archive/",
    "/search", "/404", "/500",
    "/privacy", "/terms", "/legal", "/cookies",
    "/assets/", "/static/", "/images/", "/img/",
]

SKIP_EXTENSIONS = [
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm",
    ".zip", ".tar", ".gz", ".rar",
    ".css", ".js", ".json", ".xml",
    ".ico", ".woff", ".woff2", ".ttf", ".eot",
]


@dataclass
class CrawledPage:
    url: str
    path: str
    title: str
    text: str
    text_length: int
    links: list
    depth: int
    is_priority: bool


def _should_skip_url(url: str, path: str) -> bool:
    path_lower = path.lower()

    for ext in SKIP_EXTENSIONS:
        if path_lower.endswith(ext):
            return True

    for skip in SKIP_PATHS:
        if skip in path_lower:
            return True

    return False


def _is_priority_path(path: str) -> bool:
    path_lower = path.lower()
    for priority in PRIORITY_PATHS:
        if path_lower.startswith(priority) or path_lower == priority:
            return True
    return False


def _clean_text(soup: BeautifulSoup) -> str:
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        element.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def _extract_links(soup: BeautifulSoup, base_url: str) -> list:
    links = []
    base_domain = urlparse(base_url).netloc.lower()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower() != base_domain:
            continue

        path = parsed.path.rstrip("/") or "/"
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{path}"

        if not _should_skip_url(normalized_url, path):
            links.append({
                "url": normalized_url,
                "path": path,
                "text": a.get_text(strip=True)[:100],
            })

    return links


def _fetch_page(url: str, timeout: int = 15) -> Optional[CrawledPage]:
    """Fetch and parse a single page."""
    try:
        resp = polite_get(url, timeout=timeout)
        if resp is None or resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)

        main_content = soup.find("main") or soup.find("article") or soup.find("body")
        text = _clean_text(main_content) if main_content else ""
        links = _extract_links(soup, url)

        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"

        return CrawledPage(
            url=url,
            path=path,
            title=title,
            text=text,
            text_length=len(text),
            links=links,
            depth=0,
            is_priority=_is_priority_path(path),
        )

    except Exception:
        return None


def deep_crawl_site(
    base_url: str,
    max_pages: int = 50,
    max_depth: int = 3,
    timeout: int = 15,
) -> list[CrawledPage]:
    """Crawl multiple pages from a site, prioritizing paths likely to reveal personal content."""
    base_url = base_url.rstrip("/")

    visited = set()
    pages = []

    # (priority, depth, url) — 0=priority paths, 1=other
    queue = deque()
    queue.append((0, 0, base_url))  # Homepage is highest priority
    visited.add(base_url)

    for priority_path in PRIORITY_PATHS:
        priority_url = f"{base_url}{priority_path}"
        if priority_url not in visited:
            queue.append((0, 1, priority_url))
            visited.add(priority_url)

    while queue and len(pages) < max_pages:
        batch = []
        batch_info = []

        while queue and len(batch) < 10:
            priority, depth, url = queue.popleft()
            if depth <= max_depth:
                batch.append(url)
                batch_info.append((priority, depth))

        if not batch:
            break

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_page, url, timeout): (url, info)
                      for url, info in zip(batch, batch_info)}

            for future in as_completed(futures):
                url, (priority, depth) = futures[future]
                page = future.result()

                if page and page.text_length > 100:
                    page.depth = depth
                    pages.append(page)

                    if len(pages) >= max_pages:
                        break

                    if depth < max_depth:
                        for link in page.links:
                            link_url = link["url"]
                            if link_url not in visited:
                                visited.add(link_url)
                                link_priority = 0 if _is_priority_path(link["path"]) else 1
                                queue.append((link_priority, depth + 1, link_url))

        queue = deque(sorted(queue, key=lambda x: (x[0], x[1])))

    pages.sort(key=lambda p: (not p.is_priority, p.depth))

    return pages


def summarize_crawl(pages: list[CrawledPage]) -> dict:
    total_text = sum(p.text_length for p in pages)
    priority_pages = [p for p in pages if p.is_priority]

    return {
        "total_pages": len(pages),
        "total_text_chars": total_text,
        "priority_pages": len(priority_pages),
        "avg_text_length": total_text // len(pages) if pages else 0,
        "paths": [p.path for p in pages],
        "depths": {d: len([p for p in pages if p.depth == d]) for d in range(max(p.depth for p in pages) + 1)} if pages else {},
    }


_PERSONAL_DOMAIN_RE = re.compile(
    r'^([a-z]{2,12})\.(?:com|me|io|dev|net|org|co|xyz|space)$'
    r'|^([a-z]{2,10}[a-z]{2,12})\.(?:com|me|io|dev|net|org|co)$'
)
_CORPORATE_DOMAIN_WORDS = re.compile(
    r'\b(solutions|services|tech|group|agency|consulting|labs|digital|media|studio|inc|llc|corp)\b'
)

_PERSONAL_SOCIAL_RE = re.compile(
    r'github\.com/[a-z0-9_-]+(?:["\s]|$)'
    r'|twitter\.com/[a-z0-9_]+(?:["\s]|$)'
    r'|x\.com/[a-z0-9_]+(?:["\s]|$)'
    r'|linkedin\.com/in/[a-z0-9_-]+(?:["\s]|$)',
    re.IGNORECASE,
)


def _domain_signals(url: str) -> int:
    """Score domain structure: positive for personal, negative for corporate."""
    try:
        host = urlparse(url).hostname or ""
        host = host.lower().removeprefix("www.")
    except Exception:
        return 0

    if _CORPORATE_DOMAIN_WORDS.search(host):
        return -1
    if _PERSONAL_DOMAIN_RE.match(host):
        return 1
    return 0


@dataclass
class ClassificationResult:
    is_personal: bool
    confidence: float
    reason: str
    method: str


def _load_classify_config():
    """Classification thresholds and patterns."""
    cfg = CLASSIFY_CONFIG
    reject_url = cfg.get("reject_url_patterns", [])
    reject_content = [(p["pattern"], p["category"]) for p in cfg.get("reject_content_patterns", [])]
    accept_content = [(p["pattern"], p["category"]) for p in cfg.get("accept_content_patterns", [])]
    min_content = cfg.get("min_content_length", 500)
    return reject_url, reject_content, accept_content, min_content


def pre_filter(url: str, html: str) -> Optional[ClassificationResult]:
    """Rule-based pre-filtering before LLM classification."""
    reject_url_patterns, reject_content_patterns, accept_content_patterns, min_content = _load_classify_config()

    url_lower = url.lower()
    html_lower = html.lower()

    for pattern in reject_url_patterns:
        if re.search(pattern, url_lower):
            return ClassificationResult(
                is_personal=False,
                confidence=0.95,
                reason=f"URL pattern: {pattern}",
                method="pre_filter"
            )

    positive_score = 0
    negative_score = 0
    positive_reasons = []
    negative_reasons = []

    domain_boost = _domain_signals(url)
    if domain_boost > 0:
        positive_score += 1
        positive_reasons.append("personal domain structure")
    elif domain_boost < 0:
        negative_score += 1
        negative_reasons.append("corporate domain name")

    if _PERSONAL_SOCIAL_RE.search(html[:5000]):
        positive_score += 1
        positive_reasons.append("personal social profile link")

    for pattern, reason in reject_content_patterns:
        if re.search(pattern, html_lower):
            negative_score += 1
            negative_reasons.append(reason)

    for pattern, reason in accept_content_patterns:
        if re.search(pattern, html_lower):
            positive_score += 1
            positive_reasons.append(reason)

    if negative_score >= 3 and positive_score == 0:
        return ClassificationResult(
            is_personal=False,
            confidence=0.9,
            reason=f"Multiple commercial signals: {', '.join(negative_reasons[:3])}",
            method="pre_filter"
        )

    if positive_score >= 3 and negative_score == 0:
        return ClassificationResult(
            is_personal=True,
            confidence=0.85,
            reason=f"Personal signals: {', '.join(positive_reasons[:3])}",
            method="pre_filter"
        )

    if len(html) < 100 and any(x in html_lower for x in ['enable javascript', 'javascript required', 'loading...']):
        return ClassificationResult(
            is_personal=False,
            confidence=0.9,
            reason="JavaScript-only page (no server-rendered content)",
            method="pre_filter"
        )

    if len(html) < min_content:
        personal_nav_patterns = ['/about', '/now', '/blog', '/projects', '/work', '/contact', '/writing', '/posts']
        has_personal_nav = any(nav in html_lower for nav in personal_nav_patterns)

        if has_personal_nav:
            return None

        if len(html) < 50:
            return ClassificationResult(
                is_personal=False,
                confidence=0.8,
                reason="Minimal content (< 50 chars, no navigation)",
                method="pre_filter"
            )

    return None


def classify_with_llm(url: str, html: str) -> ClassificationResult:
    """Use LLM to classify ambiguous sites."""
    html_excerpt = html[:2500]
    prompt = render_prompt(CLASSIFY_PROMPT, url=url, content=html_excerpt)

    try:
        from process import get_cheap_llm
        result = get_cheap_llm().complete_json(prompt, max_tokens=150, temperature=0)

        return ClassificationResult(
            is_personal=result.get("is_personal", True),
            confidence=result.get("confidence", 0.8),
            reason=result.get("reason", "LLM classification"),
            method="llm"
        )

    except Exception as e:
        return ClassificationResult(
            is_personal=True,
            confidence=0.5,
            reason=f"Classification error: {str(e)}",
            method="llm_error"
        )


def classify_site(url: str, html: str) -> ClassificationResult:
    """Classify a site as personal or not (rule-based first, then LLM if needed)."""
    pre_result = pre_filter(url, html)
    if pre_result is not None:
        return pre_result

    return classify_with_llm(url, html)
