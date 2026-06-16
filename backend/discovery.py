"""Discover URLs from multiple web sources (directories, webrings, social platforms)."""


# Configuration for each discovery source: enabled, type, URL, priority, rate_limit.
SOURCES = {'nownownow': {'enabled': True,
               'type': 'nownownow',
               'url': 'https://nownownow.com',
               'description': "Derek Sivers' directory of /now pages",
               'priority': 1,
               'rate_limit': 1.0,
               'max_pages': 200},
 'personalsites': {'enabled': True,
                   'type': 'personalsites',
                   'url': 'https://personalsit.es',
                   'description': 'Curated directory of personal websites',
                   'priority': 1,
                   'rate_limit': 1.0},
 'ooh_directory': {'enabled': True,
                   'type': 'ooh_directory',
                   'url': 'https://ooh.directory',
                   'description': "Phil Gyford's curated blog directory",
                   'priority': 1,
                   'rate_limit': 1.0},
 'indieseek': {'enabled': True,
               'type': 'indieseek',
               'url': 'https://indieseek.xyz',
               'description': 'Indie web directory',
               'priority': 1,
               'rate_limit': 1.0},
 'indieweb_webring': {'enabled': True,
                      'type': 'webring',
                      'url': 'https://xn--sr8hvo.ws/directory',
                      'description': 'IndieWeb webring directory',
                      'priority': 2,
                      'rate_limit': 1.0},
 'xxiivv_webring': {'enabled': True,
                    'type': 'webring_xxiivv',
                    'url': 'https://webring.xxiivv.com',
                    'description': 'XXIIVV/Merveilles creative webring',
                    'priority': 2,
                    'rate_limit': 1.0},
 'neocities': {'enabled': True,
               'type': 'neocities',
               'url': 'https://neocities.org/browse',
               'description': 'Neocities hosting platform',
               'priority': 3,
               'rate_limit': 2.0,
               'max_pages': 200},
 'hackernews': {'enabled': True,
                'type': 'hackernews',
                'url': 'https://news.ycombinator.com',
                'description': 'Hacker News stories via Algolia API',
                'priority': 3,
                'rate_limit': 0.1,
                'mode': 'all',
                'hits_per_page': 1000,
                'max_pages': 50},
 'reddit': {'enabled': True,
            'type': 'reddit',
            'url': 'https://reddit.com',
            'description': 'Reddit - side projects, portfolios, indie hackers',
            'priority': 3,
            'rate_limit': 2.0,
            'max_posts_per_sub': 500},
 'awesome_personal_websites': {'enabled': True,
                               'type': 'github_awesome',
                               'url': 'https://github.com/logancyang/awesome-personal-websites',
                               'description': 'Curated list of personal websites (ML/data focus)',
                               'priority': 4,
                               'rate_limit': 1.0},
 'awesome_dev_websites': {'enabled': True,
                          'type': 'github_awesome',
                          'url': 'https://github.com/christopherkade/awesome-dev-websites',
                          'description': 'Developer personal websites',
                          'priority': 4,
                          'rate_limit': 1.0},
 'awesome_personal_blogs': {'enabled': True,
                            'type': 'github_awesome',
                            'url': 'https://github.com/jkup/awesome-personal-blogs',
                            'description': 'Personal tech blogs',
                            'priority': 4,
                            'rate_limit': 1.0}}



import re
import time
import requests
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Set
from dataclasses import dataclass
from bs4 import BeautifulSoup
from config import get_headers, GITHUB_TOKEN
from crawler import is_crawlable, extract_homepage, normalize_domain


@dataclass
class DiscoveredURL:
    """A URL discovered from a source."""
    url: str
    source: str
    name: Optional[str] = None
    now_page_url: Optional[str] = None
    metadata: Optional[dict] = None


def load_sources_config() -> dict:
    return {"sources": SOURCES}


class SourceCrawler(ABC):
    """Base class for source crawlers. Handles HTTP requests, rate limiting, and HTML parsing."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("name", "unknown")
        self.url = config.get("url")
        self.rate_limit = config.get("rate_limit", 1.0)
        self.max_pages = config.get("max_pages", 50)
        self.session = requests.Session()
        self._last_request = 0

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def fetch(self, url: str) -> Optional[str]:
        self._rate_limit_wait()
        try:
            response = self.session.get(url, headers=get_headers(), timeout=15)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  Error fetching {url}: {e}")
            return None

    def parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @abstractmethod
    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl source and yield discovered URLs."""
        pass

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})"


class GitHubAwesomeCrawler(SourceCrawler):
    """Crawl GitHub awesome lists to extract personal website links."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl a GitHub awesome list README."""
        print(f"Crawling {self.name}: {self.url}")

        content = self._fetch_readme()
        if not content:
            print("  Could not fetch README")
            return

        seen_urls = set()
        count = 0

        # Parse markdown links: [text](url)
        link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

        for match in link_pattern.finditer(content):
            name = match.group(1).strip()
            url = match.group(2).strip()

            # Skip non-http links
            if not url.startswith("http"):
                continue

            # Skip GitHub links (repo links, not personal sites)
            if "github.com" in url and "/blob/" not in url:
                # Check if it's a user profile (might have website)
                if re.match(r"https://github\.com/[^/]+$", url):
                    # This is a user profile, skip for now
                    continue
                # Skip repo links
                continue

            # Skip common non-personal sites
            skip_domains = [
                "twitter.com", "linkedin.com", "youtube.com",
                "medium.com", "dev.to", "dribbble.com", "behance.net"
            ]
            if any(domain in url for domain in skip_domains):
                continue

            # Normalize URL
            url = url.rstrip("/")

            if url in seen_urls:
                continue
            seen_urls.add(url)

            count += 1
            yield DiscoveredURL(
                url=url,
                source="github_awesome",
                name=name,
                metadata={
                    "awesome_list": self.url
                }
            )

        print(f"  Found {count} personal sites")

    def _fetch_readme(self) -> Optional[str]:
        """Resolve and fetch the repo's README via the GitHub API.

        The API's /readme endpoint returns whatever the README is actually
        named (e.g. lowercase `readme.md`) on the default branch, so we don't
        have to guess main/master or the file's casing.
        """
        m = re.search(r"github\.com/([^/]+)/([^/]+)", self.url)
        if not m:
            return None
        owner, repo = m.group(1), m.group(2).rstrip("/")

        headers = get_headers()
        headers["Accept"] = "application/vnd.github+json"
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

        self._rate_limit_wait()
        try:
            resp = self.session.get(
                f"https://api.github.com/repos/{owner}/{repo}/readme",
                headers=headers, timeout=15)
            resp.raise_for_status()
            download_url = resp.json().get("download_url")
        except (requests.RequestException, ValueError) as e:
            print(f"  Error resolving README for {owner}/{repo}: {e}")
            return None

        if not download_url:
            return None
        return self.fetch(download_url)


class HackerNewsCrawler(SourceCrawler):
    """Crawls Hacker News via Algolia Search API to discover personal websites."""

    ALGOLIA_BASE = "https://hn.algolia.com/api/v1"

    def __init__(self, config: dict):
        super().__init__(config)
        self.hits_per_page = config.get("hits_per_page", 1000)
        self.max_pages = config.get("max_pages", 50)
        self.search_queries = config.get("search_queries", [
            "Show HN", "my website", "my blog", "personal site",
            "side project", "I built", "I made", "launching",
        ])
        self.seen_domains: Set[str] = set()

    def _search_stories(self, query: str = None, page: int = 0, by_date: bool = True,
                         before: int = None) -> dict:
        endpoint = "search_by_date" if by_date else "search"
        url = f"{self.ALGOLIA_BASE}/{endpoint}"

        params = {
            "tags": "story",
            "hitsPerPage": self.hits_per_page,
            "page": page,
        }
        if query:
            params["query"] = query
        # Algolia caps each query at 1000 retrievable hits regardless of paging.
        # To walk further back than that, window by creation time: ask only for
        # stories older than the oldest one we've already seen.
        if before:
            params["numericFilters"] = f"created_at_i<{before}"

        try:
            self._rate_limit_wait()
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Algolia API error: {e}")
            return {"hits": [], "nbPages": 0}

    def _process_hits(self, hits: list, source_tag: str) -> Iterator[DiscoveredURL]:
        for hit in hits:
            url = hit.get("url")
            if not url:
                continue

            if not is_crawlable(url):
                continue

            homepage = extract_homepage(url)
            domain = normalize_domain(homepage)

            if domain in self.seen_domains:
                continue
            self.seen_domains.add(domain)

            yield DiscoveredURL(
                url=homepage,
                source=source_tag,
                name=hit.get("title", "").replace("Show HN: ", "")[:100],
                metadata={
                    "hn_id": hit.get("objectID"),
                    "points": hit.get("points"),
                    "created_at": hit.get("created_at"),
                    "original_url": url,
                }
            )

    def _crawl_windowed(self, source_tag: str, query: str = None,
                        max_windows: int = None) -> Iterator[DiscoveredURL]:
        """Walk HN history backwards in time, one ~1000-story window at a time.

        Algolia only ever returns the first 1000 hits of a query, so simple
        page-based paging stalls after one page. Instead we sort by date and,
        after each batch, move the `created_at_i<` cursor to the oldest story we
        just saw — letting us page through all 3.6M+ stories.
        """
        max_windows = max_windows or self.max_pages
        label = f"'{query}'" if query else "all stories"
        print(f"  Crawling HN {label} (up to {max_windows} time windows)...")

        before = None
        for window in range(max_windows):
            result = self._search_stories(query=query, page=0, by_date=True, before=before)
            hits = result.get("hits", [])
            if not hits:
                break

            yield from self._process_hits(hits, source_tag)

            # Advance the cursor to just before the oldest story in this batch.
            timestamps = [h.get("created_at_i") for h in hits if h.get("created_at_i")]
            if not timestamps:
                break
            oldest = min(timestamps)
            if before is not None and oldest >= before:
                break  # no forward progress — we've hit the tail
            before = oldest

            if window % 10 == 0:
                print(f"  Window {window}/{max_windows} (before {oldest}), "
                      f"{len(self.seen_domains)} unique domains")

    def _crawl_all_stories(self, max_pages: int = None) -> Iterator[DiscoveredURL]:
        yield from self._crawl_windowed("hackernews", query=None, max_windows=max_pages)

    def _crawl_show_hn(self, max_pages: int = None) -> Iterator[DiscoveredURL]:
        yield from self._crawl_windowed(
            "hackernews_showhn", query="Show HN",
            max_windows=max_pages or min(self.max_pages, 500))

    def _crawl_search_queries(self) -> Iterator[DiscoveredURL]:
        for query in self.search_queries:
            print(f"  Searching: '{query}'...")

            for page in range(min(100, self.max_pages)):
                result = self._search_stories(query=query, page=page, by_date=False)
                hits = result.get("hits", [])

                if not hits:
                    break

                yield from self._process_hits(hits, "hackernews_search")

    def crawl(self) -> Iterator[DiscoveredURL]:
        print("HackerNews crawler starting...")
        mode = self.config.get("mode", "all")
        print(f"  Mode: {mode}")

        if mode in ("showhn", "show_hn"):
            yield from self._crawl_show_hn()
        elif mode == "search":
            yield from self._crawl_search_queries()
        elif mode == "all_stories":
            yield from self._crawl_all_stories()
        else:  # "all"
            yield from self._crawl_show_hn(max_pages=200)
            yield from self._crawl_search_queries()
            yield from self._crawl_all_stories(max_pages=500)

        print(f"  Total unique domains discovered: {len(self.seen_domains)}")


class IndieseekCrawler(SourceCrawler):
    """Crawl indieseek.xyz directory."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl indieseek.xyz listings."""
        print(f"Crawling {self.name}: {self.url}")

        # Indieseek has multiple categories
        categories = [
            "/links/personal/",
            "/links/blogs/",
            "/links/creative/",
        ]

        seen_urls = set()
        count = 0

        for category in categories:
            cat_url = f"{self.url.rstrip('/')}{category}"
            print(f"  Category: {category}")

            html = self.fetch(cat_url)
            if not html:
                continue

            soup = self.parse_html(html)

            # Find site links
            for link in soup.find_all("a", href=True):
                href = link["href"]

                # Skip internal links
                if not href.startswith("http"):
                    continue
                if "indieseek.xyz" in href:
                    continue

                # Normalize
                url = href.rstrip("/")

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                name = link.get_text(strip=True)
                if not name or len(name) < 2:
                    name = None

                count += 1
                yield DiscoveredURL(
                    url=url,
                    source="indieseek",
                    name=name,
                    metadata={"category": category}
                )

        print(f"  Found {count} sites")


class NeocitiesCrawler(SourceCrawler):
    """Crawl neocities.org browse pages to discover personal sites."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl Neocities browse pages."""
        print(f"Crawling {self.name}: {self.url}")

        seen_urls = set()
        count = 0
        page = 1

        # Each site's own subdomain. The browse markup wraps a card in the link
        # (rather than nesting the link inside a "site-*" box), so just pull every
        # *.neocities.org link off the page and dedupe.
        site_link_re = re.compile(r"^https?://([a-z0-9][a-z0-9-]*)\.neocities\.org/?$", re.I)

        while page <= self.max_pages:
            # Neocities has pagination
            page_url = f"{self.url}?page={page}"
            print(f"  Page {page}/{self.max_pages}")

            html = self.fetch(page_url)
            if not html:
                break

            soup = self.parse_html(html)

            sites_on_page = 0
            for link in soup.find_all("a", href=site_link_re):
                href = link["href"]
                # Skip the platform's own www subdomain, keep real user sites.
                if href.rstrip("/").endswith("//www.neocities.org") or "www.neocities.org" in href:
                    continue
                url = href.rstrip("/")

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                name = link.get_text(strip=True) or None

                sites_on_page += 1
                count += 1

                yield DiscoveredURL(
                    url=url,
                    source="neocities",
                    name=name,
                    metadata={"platform": "neocities"},
                )

            # If no sites found on page, we've reached the end
            if sites_on_page == 0:
                break

            page += 1

        print(f"  Found {count} Neocities sites")


class NowNowNowCrawler(SourceCrawler):
    """Crawl nownownow.com to discover people with /now pages."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl all locations on nownownow.com."""
        print(f"Crawling {self.name}: {self.url}")

        # First, get the list of locations
        html = self.fetch(self.url)
        if not html:
            return

        soup = self.parse_html(html)

        # Find location links (e.g., /US-CA, /GB-ENG, /DE)
        location_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Match patterns like /US-CA, /GB-ENG, /DE (country/region codes)
            if re.match(r"^/[A-Z]{2}(-[A-Z]{2,3})?$", href):
                href = f"https://nownownow.com{href}"
                location_links.append(href)

        # Deduplicate
        location_links = list(set(location_links))
        print(f"  Found {len(location_links)} locations")

        # Crawl each location page
        for i, loc_url in enumerate(location_links[:self.max_pages]):
            print(f"  [{i+1}/{min(len(location_links), self.max_pages)}] {loc_url}")

            loc_html = self.fetch(loc_url)
            if not loc_html:
                continue

            loc_soup = self.parse_html(loc_html)

            # NEW: Extract directly from location page
            # Structure: <h2><a href="/p/xxx">Name</a></h2>
            #           <h3><a href="https://site.com/now">site.com/now</a></h3>

            for h2 in loc_soup.find_all("h2"):
                # Get person name from h2 link
                name_link = h2.find("a", href=re.compile(r"/p/"))
                if not name_link:
                    continue

                name = name_link.get_text(strip=True)

                # Get /now URL from next h3 sibling
                h3 = h2.find_next_sibling("h3")
                if not h3:
                    continue

                now_link = h3.find("a", href=True)
                if not now_link:
                    continue

                now_url = now_link["href"]

                # Skip if not external URL
                if not now_url.startswith("http"):
                    continue

                # Derive homepage from /now URL
                homepage_url = re.sub(r"/now/?$", "", now_url, flags=re.IGNORECASE)
                if not homepage_url or homepage_url == now_url:
                    # /now wasn't at end, use the URL as-is
                    homepage_url = now_url.rstrip("/")

                yield DiscoveredURL(
                    url=homepage_url,
                    source="nownownow",
                    name=name if name else None,
                    now_page_url=now_url,
                )

        print(f"  Discovery complete for {self.name}")


class OohDirectoryCrawler(SourceCrawler):
    """Crawl ooh.directory to discover curated blogs."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl ooh.directory blog listings."""
        print(f"Crawling {self.name}: {self.url}")

        # ooh.directory has categories, we'll crawl the main listing
        # and also personal blogs category
        urls_to_crawl = [
            f"{self.url}/blogs/personal/",
            f"{self.url}/blogs/",
        ]

        seen_urls = set()
        count = 0

        for page_url in urls_to_crawl:
            html = self.fetch(page_url)
            if not html:
                continue

            soup = self.parse_html(html)

            # Find blog entries - they have links to external sites
            for article in soup.find_all(["article", "li", "div"]):
                # Look for the main link in each entry
                link = article.find("a", href=True)
                if not link:
                    continue

                href = link["href"]

                # Skip internal links
                if not href.startswith("http"):
                    continue
                if "ooh.directory" in href:
                    continue

                # Normalize URL
                url = href.rstrip("/")

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Get name from link text or title
                name = link.get_text(strip=True)
                if not name or len(name) < 2:
                    name = link.get("title")

                count += 1
                yield DiscoveredURL(
                    url=url,
                    source="ooh_directory",
                    name=name,
                    metadata={"category": page_url}
                )

        print(f"  Found {count} blogs")


class PersonalSitesCrawler(SourceCrawler):
    """Crawl personalsit.es to discover personal websites."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl personalsit.es directory."""
        print(f"Crawling {self.name}: {self.url}")

        html = self.fetch(self.url)
        if not html:
            return

        soup = self.parse_html(html)

        # personalsit.es has a list of links to personal sites
        # They're typically in a main content area with external links
        count = 0
        seen_urls = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]

            # Skip internal links and non-http links
            if not href.startswith("http"):
                continue
            if "personalsit.es" in href:
                continue
            if "github.com/xdesro" in href:
                continue

            # Normalize URL
            url = href.rstrip("/")

            # Skip duplicates
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Get the name from the link text
            name = link.get_text(strip=True)
            if not name or len(name) < 2:
                name = None

            count += 1
            yield DiscoveredURL(
                url=url,
                source="personalsites",
                name=name,
                metadata={"source_page": self.url}
            )

        print(f"  Found {count} personal sites")


SUBREDDITS = [
    ("SideProject", "top", 1000),
    ("sideproject", "top", 500),
    ("indiehackers", "top", 500),
    ("InternetIsBeautiful", "top", 1000),
    ("indieweb", "top", 300),
    ("smallweb", "top", 200),
    ("webdev", "top", 500),
    ("web_design", "top", 500),
    ("Frontend", "top", 300),
    ("programming", "top", 500),
    ("coding", "top", 300),
    ("learnprogramming", "top", 300),
    ("design", "top", 300),
    ("graphic_design", "top", 300),
    ("UI_Design", "top", 200),
    ("coolgithubprojects", "top", 300),
    ("opensource", "top", 300),
    ("blogs", "top", 300),
    ("blogging", "top", 200),
    ("PersonalFinance", "top", 200),
]


class RedditCrawler(SourceCrawler):
    """Crawl maker and indie subreddits for personal website links."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.subreddits = config.get("subreddits", SUBREDDITS)
        self.max_posts_per_sub = config.get("max_posts_per_sub", 500)
        self.seen_domains: Set[str] = set()

    def _fetch_subreddit(self, subreddit: str, sort: str = "top", limit: int = 100, after: str = None,
                         retries: int = 3) -> dict:
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
        params = {
            "limit": min(limit, 100),
            "t": "all",  # All time for "top"
        }
        if after:
            params["after"] = after

        try:
            self._rate_limit_wait()
            response = self.session.get(url, params=params, timeout=30)

            if response.status_code == 429:
                if retries <= 0:
                    print(f"  Rate limited on r/{subreddit}, giving up")
                    return {"data": {"children": [], "after": None}}
                print(f"  Rate limited on r/{subreddit}, waiting 60s...")
                time.sleep(60)
                return self._fetch_subreddit(subreddit, sort, limit, after, retries - 1)

            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Error fetching r/{subreddit}: {e}")
            return {"data": {"children": [], "after": None}}

    def _process_post(self, post: dict, subreddit: str):
        url = post.get("url", "")

        if not url or post.get("is_self") or post.get("is_video"):
            return None

        if not is_crawlable(url):
            return None

        homepage = extract_homepage(url)
        domain = normalize_domain(homepage)

        if domain in self.seen_domains:
            return None
        self.seen_domains.add(domain)

        return DiscoveredURL(
            url=homepage,
            source=f"reddit_r/{subreddit}",
            name=post.get("title", "")[:100],
            metadata={
                "reddit_id": post.get("id"),
                "score": post.get("score"),
                "subreddit": subreddit,
                "original_url": url,
            }
        )

    def _crawl_subreddit(self, subreddit: str, sort: str = "top", max_posts: int = 500) -> Iterator[DiscoveredURL]:
        print(f"  Crawling r/{subreddit} ({sort})...")

        after = None
        posts_fetched = 0
        urls_found = 0

        while posts_fetched < max_posts:
            data = self._fetch_subreddit(subreddit, sort, limit=100, after=after)

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                post = child.get("data", {})
                result = self._process_post(post, subreddit)
                if result:
                    urls_found += 1
                    yield result

            posts_fetched += len(children)
            after = data.get("data", {}).get("after")

            if not after:
                break

        print(f"    Fetched {posts_fetched} posts, found {urls_found} new URLs")

    def crawl(self) -> Iterator[DiscoveredURL]:
        print("Reddit crawler starting...")
        print(f"  Subreddits: {len(self.subreddits)}")

        for subreddit_config in self.subreddits:
            if isinstance(subreddit_config, tuple):
                subreddit, sort, max_posts = subreddit_config
            else:
                subreddit = subreddit_config
                sort = "top"
                max_posts = self.max_posts_per_sub

            try:
                yield from self._crawl_subreddit(subreddit, sort, max_posts)
            except Exception as e:
                print(f"  Error crawling r/{subreddit}: {e}")
                continue

        print(f"  Total unique domains discovered: {len(self.seen_domains)}")


class WebringCrawler(SourceCrawler):
    """Generic webring crawler for standard webring formats."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl a webring directory page."""
        print(f"Crawling {self.name}: {self.url}")

        html = self.fetch(self.url)
        if not html:
            return

        soup = self.parse_html(html)

        seen_urls = set()
        count = 0

        # Look for external links that aren't part of the webring infrastructure
        for link in soup.find_all("a", href=True):
            href = link["href"]

            # Skip non-http links
            if not href.startswith("http"):
                continue

            # Skip webring infrastructure links
            skip_patterns = [
                "webring", "previous", "next", "random",
                "github.com", "twitter.com", "mastodon"
            ]
            if any(pattern in href.lower() for pattern in skip_patterns):
                continue

            # Normalize URL
            url = href.rstrip("/")

            if url in seen_urls:
                continue
            seen_urls.add(url)

            name = link.get_text(strip=True)
            if not name or len(name) < 2:
                name = None

            count += 1
            yield DiscoveredURL(
                url=url,
                source="webring",
                name=name,
                metadata={"webring": self.url}
            )

        print(f"  Found {count} sites in webring")


class XXIIVVWebringCrawler(SourceCrawler):
    """Crawler for the XXIIVV/Merveilles webring."""

    def crawl(self) -> Iterator[DiscoveredURL]:
        """Crawl the XXIIVV webring."""
        print(f"Crawling {self.name}: {self.url}")

        # The XXIIVV webring has a specific format
        # Try the sites.js or hallway page
        urls_to_try = [
            "https://webring.xxiivv.com/sites.js",
            "https://webring.xxiivv.com/hallway.html",
            self.url
        ]

        seen_urls = set()
        count = 0

        for try_url in urls_to_try:
            content = self.fetch(try_url)
            if not content:
                continue

            # If it's JavaScript, parse the sites array
            if "sites.js" in try_url or "var sites" in content:
                # Parse JavaScript array: var sites = [{...}, ...]
                urls = re.findall(r'"url"\s*:\s*"([^"]+)"', content)
                names = re.findall(r'"title"\s*:\s*"([^"]+)"', content)

                for i, url in enumerate(urls):
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    name = names[i] if i < len(names) else None
                    count += 1

                    yield DiscoveredURL(
                        url=url.rstrip("/"),
                        source="xxiivv_webring",
                        name=name,
                        metadata={"webring": "xxiivv"}
                    )
            else:
                # Parse as HTML
                soup = self.parse_html(content)
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if not href.startswith("http"):
                        continue
                    if "xxiivv" in href or "webring" in href:
                        continue

                    url = href.rstrip("/")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    name = link.get_text(strip=True)
                    count += 1

                    yield DiscoveredURL(
                        url=url,
                        source="xxiivv_webring",
                        name=name if name else None,
                        metadata={"webring": "xxiivv"}
                    )

            if count > 0:
                break

        print(f"  Found {count} sites in XXIIVV webring")


CRAWLER_REGISTRY = {
    "nownownow": NowNowNowCrawler,
    "personalsites": PersonalSitesCrawler,
    "ooh_directory": OohDirectoryCrawler,
    "neocities": NeocitiesCrawler,
    "github_awesome": GitHubAwesomeCrawler,
    "webring": WebringCrawler,
    "webring_xxiivv": XXIIVVWebringCrawler,
    "indieseek": IndieseekCrawler,
    "hackernews": HackerNewsCrawler,
    "reddit": RedditCrawler,
}


def get_crawler_for_source(source_name: str, source_config: dict) -> Optional[SourceCrawler]:
    """Instantiate the appropriate crawler class for a source."""
    source_type = source_config.get("type")
    if source_type not in CRAWLER_REGISTRY:
        print(f"Unknown source type: {source_type}")
        return None

    crawler_class = CRAWLER_REGISTRY[source_type]
    config = {**source_config, "name": source_name}
    return crawler_class(config)


def crawl_all_sources(
    enabled_only: bool = True,
    priority: Optional[int] = None
) -> Iterator[DiscoveredURL]:
    """Crawl all sources in priority order and yield discovered URLs.

    Args:
        enabled_only: Only run sources marked as enabled in SOURCES.
        priority: If set, only run sources at this priority level (1 = highest).
    """
    config = load_sources_config()
    sources = config.get("sources", {})

    # Sort by priority
    sorted_sources = sorted(
        sources.items(),
        key=lambda x: x[1].get("priority", 99)
    )

    for source_name, source_config in sorted_sources:
        # Skip disabled sources
        if enabled_only and not source_config.get("enabled", True):
            continue

        # Filter by priority if specified
        if priority is not None and source_config.get("priority") != priority:
            continue

        crawler = get_crawler_for_source(source_name, source_config)
        if not crawler:
            continue

        try:
            for discovered in crawler.crawl():
                yield discovered
        except Exception as e:
            print(f"Error crawling {source_name}: {e}")
            continue
