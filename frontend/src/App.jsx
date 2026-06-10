import { useState, useEffect, useRef } from 'react'
import { Search, ExternalLink, RefreshCw, Sparkles, ChevronDown, ChevronUp, X, Activity, CheckCircle, XCircle, AlertCircle, Loader, Laptop, ArrowRight } from 'lucide-react'
import './App.css'

const API_URL = '/api'
const MIN_SEARCH_LENGTH = 2
const DEBOUNCE_MS = 500

function App() {
  const [query, setQuery] = useState('')
  const [searchedQuery, setSearchedQuery] = useState('')
  const [people, setPeople] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [isTyping, setIsTyping] = useState(false)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [searchMode, setSearchMode] = useState(false)
  const [showCrawlerLog, setShowCrawlerLog] = useState(false)
  const [crawlerEvents, setCrawlerEvents] = useState([])
  const [newApprovalCount, setNewApprovalCount] = useState(0)
  // Ref, not state: read/written inside polling intervals whose closures would
  // otherwise capture a stale value and never detect new approvals.
  const lastKnownCountRef = useRef(null)
  const [categories, setCategories] = useState([])
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [featuredPerson, setFeaturedPerson] = useState(null)
  const [featuredDismissed, setFeaturedDismissed] = useState(false)
  const [featuredExpanded, setFeaturedExpanded] = useState(false)
  const [featuredOpen, setFeaturedOpen] = useState(false)

  // live "the machine, right now" band + educational funnel page
  const [crawlStats, setCrawlStats] = useState(null)
  const [funnel, setFunnel] = useState(null)
  const [view, setView] = useState(() => (typeof window !== 'undefined' && window.location.hash.replace('#', '') === 'funnel' ? 'funnel' : 'home'))

  // Infinite scroll state
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [seed] = useState(() => Math.floor(Math.random() * 2147483647))

  const searchTimerRef = useRef(null)
  const abortControllerRef = useRef(null)
  const crawlerPollRef = useRef(null)
  const statsPollRef = useRef(null)

  // Initial load only
  useEffect(() => {
    fetchStats()
    fetchPeople()
    fetchCrawlerEvents()
    fetchCategories()
    fetchFeaturedPerson()
    fetchCrawlStats()
    fetchFunnel()
  }, [])

  // keep the view in sync with the URL hash (shareable #funnel)
  useEffect(() => {
    const onHash = () => setView(window.location.hash.replace('#', '') === 'funnel' ? 'funnel' : 'home')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const goTo = (next) => {
    window.location.hash = next === 'funnel' ? 'funnel' : ''
    setView(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const fetchCrawlStats = async () => {
    try {
      const res = await fetch(`${API_URL}/crawl/stats`)
      const data = await res.json()
      if (!data.error) setCrawlStats(data)
    } catch (e) {
      console.error('Failed to fetch crawl stats:', e)
    }
  }

  const fetchFunnel = async () => {
    try {
      const res = await fetch(`${API_URL}/pipeline/funnel`)
      const data = await res.json()
      if (!data.error) setFunnel(data)
    } catch (e) {
      console.error('Failed to fetch funnel:', e)
    }
  }

  const fetchFeaturedPerson = async () => {
    try {
      const res = await fetch(`${API_URL}/featured`)
      const data = await res.json()
      if (data.person) setFeaturedPerson(data.person)
    } catch (e) {
      console.error('Failed to fetch featured person:', e)
    }
  }

  const fetchCategories = async () => {
    try {
      const res = await fetch(`${API_URL}/categories`)
      const data = await res.json()
      if (Array.isArray(data)) {
        setCategories(data)
      }
    } catch (e) {
      console.error('Failed to fetch categories:', e)
    }
  }

  // Infinite scroll
  useEffect(() => {
    const handleScroll = () => {
      if (searchMode || loading || loadingMore || !hasMore) return

      const scrollTop = window.scrollY
      const windowHeight = window.innerHeight
      const docHeight = document.documentElement.scrollHeight

      // Load more when 300px from bottom
      if (scrollTop + windowHeight >= docHeight - 300) {
        loadMore()
      }
    }

    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [searchMode, loading, loadingMore, hasMore, offset])

  // Poll for crawler events and stats when log is open
  useEffect(() => {
    if (showCrawlerLog) {
      fetchCrawlerEvents()
      fetchStatsQuietly()
      crawlerPollRef.current = setInterval(() => {
        fetchCrawlerEvents()
        fetchStatsQuietly()
      }, 3000)
    } else {
      if (crawlerPollRef.current) {
        clearInterval(crawlerPollRef.current)
        crawlerPollRef.current = null
      }
    }
    return () => {
      if (crawlerPollRef.current) {
        clearInterval(crawlerPollRef.current)
      }
    }
  }, [showCrawlerLog])

  // Background stats polling (every 10 seconds) to catch new approvals
  useEffect(() => {
    statsPollRef.current = setInterval(() => {
      fetchStatsQuietly()
      fetchCrawlStats()
      fetchCrawlerEvents()
    }, 10000)
    return () => {
      if (statsPollRef.current) {
        clearInterval(statsPollRef.current)
      }
    }
  }, [])

  const fetchCrawlerEvents = async () => {
    try {
      const res = await fetch(`${API_URL}/crawler/events?limit=30`)
      const data = await res.json()
      if (data.events) {
        setCrawlerEvents(data.events)
      }
    } catch (e) {
      console.error('Failed to fetch crawler events:', e)
    }
  }

  const fetchStatsQuietly = async () => {
    try {
      const res = await fetch(`${API_URL}/stats`)
      const data = await res.json()

      // Detect new approvals
      const last = lastKnownCountRef.current
      if (last !== null && data.with_work_summary > last) {
        const newCount = data.with_work_summary - last
        setNewApprovalCount(prev => prev + newCount)
        // Auto-clear notification after 5 seconds
        setTimeout(() => setNewApprovalCount(0), 5000)
      }

      lastKnownCountRef.current = data.with_work_summary
      setStats(data)
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }

  // Debounced search - only depends on query
  useEffect(() => {
    // Clear any existing timer
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
      searchTimerRef.current = null
    }

    const trimmedQuery = query.trim()

    // If query is empty, do nothing here - let clearSearch handle reset
    if (!trimmedQuery) {
      setIsTyping(false)
      return
    }

    // Don't search if query too short
    if (trimmedQuery.length < MIN_SEARCH_LENGTH) {
      setIsTyping(false)
      return
    }

    // Show typing indicator
    setIsTyping(true)

    // Set up debounced search
    searchTimerRef.current = setTimeout(() => {
      searchTimerRef.current = null
      setIsTyping(false)
      performSearch(trimmedQuery)
    }, DEBOUNCE_MS)

    return () => {
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current)
        searchTimerRef.current = null
      }
    }
  }, [query]) // Only query - removed searchMode to prevent re-triggers

  const cancelPendingRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }

  const performSearch = async (searchQuery) => {
    cancelPendingRequest()

    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)
    setExpandedId(null)

    try {
      const res = await fetch(
        `${API_URL}/search?q=${encodeURIComponent(searchQuery)}&limit=24`,
        { signal: controller.signal }
      )

      // Check if this request was aborted while waiting
      if (controller.signal.aborted) return

      if (!res.ok) throw new Error('Search failed')

      const data = await res.json()

      // Check again after parsing
      if (controller.signal.aborted) return

      if (Array.isArray(data)) {
        setPeople(data)
        setSearchedQuery(searchQuery)
        setSearchMode(true)
      } else {
        setPeople([])
        setSearchedQuery(searchQuery)
        setSearchMode(true)
      }
      setLoading(false)
    } catch (e) {
      if (e.name === 'AbortError') return // Don't update any state on abort

      console.error('Search failed:', e)
      setError('Search failed')
      setPeople([])
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_URL}/stats`)
      const data = await res.json()
      setStats(data)
      // Initialize the baseline on first fetch
      if (lastKnownCountRef.current === null) {
        lastKnownCountRef.current = data.with_work_summary
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e)
    }
  }

  const fetchPeople = async (reset = true, category = selectedCategory) => {
    if (reset) {
      cancelPendingRequest()
      setLoading(true)
      setOffset(0)
      setHasMore(true)
      setPeople([])
    }

    const controller = new AbortController()
    abortControllerRef.current = controller

    if (!reset) setLoadingMore(true)
    setError(null)
    if (reset) setExpandedId(null)

    const currentOffset = reset ? 0 : offset

    try {
      let url = `${API_URL}/discover?limit=24&offset=${currentOffset}&seed=${seed}`
      if (category) {
        url += `&category=${encodeURIComponent(category)}`
      }
      const res = await fetch(url, { signal: controller.signal })

      if (controller.signal.aborted) return

      const data = await res.json()

      if (controller.signal.aborted) return

      const newPeople = data.people || []

      if (reset) {
        setPeople(newPeople)
      } else {
        setPeople(prev => [...prev, ...newPeople])
      }

      setHasMore(data.has_more)
      setOffset(currentOffset + newPeople.length)
      setSearchMode(false)
      setSearchedQuery('')
      setLoading(false)
      setLoadingMore(false)
    } catch (e) {
      if (e.name === 'AbortError') return

      console.error('Failed to fetch people:', e)
      setError('Failed to load')
      if (reset) setPeople([])
      setLoading(false)
      setLoadingMore(false)
    }
  }

  const loadMore = () => {
    if (!loadingMore && hasMore && !searchMode) {
      fetchPeople(false)
    }
  }

  const shufflePeople = async () => {
    if (loading) return

    cancelPendingRequest()

    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)
    setExpandedId(null)
    setQuery('')
    setSearchedQuery('')
    setSearchMode(false)
    setIsTyping(false)

    try {
      const res = await fetch(
        `${API_URL}/discover?limit=24`,
        { signal: controller.signal }
      )

      if (controller.signal.aborted) return

      if (!res.ok) throw new Error('Failed to fetch')

      const data = await res.json()

      if (controller.signal.aborted) return

      const newPeople = data.people || []
      setPeople(newPeople)
      setOffset(newPeople.length)
      setHasMore(Boolean(data.has_more))
      setLoading(false)
    } catch (e) {
      if (e.name === 'AbortError') return

      console.error('Failed to shuffle:', e)
      setError('Failed to shuffle')
      setLoading(false)
    }
  }

  const handleSearch = (e) => {
    e.preventDefault()

    const trimmedQuery = query.trim()

    // Cancel any pending debounce
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
      searchTimerRef.current = null
    }
    setIsTyping(false)

    if (!trimmedQuery) {
      clearSearch()
      return
    }

    if (trimmedQuery.length < MIN_SEARCH_LENGTH) {
      return
    }

    performSearch(trimmedQuery)
  }

  const selectCategory = (category) => {
    const newCategory = category === selectedCategory ? null : category
    setSelectedCategory(newCategory)
    setQuery('')
    setSearchedQuery('')
    setSearchMode(false)
    fetchPeople(true, newCategory)
  }

  const clearSearch = () => {
    // Cancel any pending operations
    if (searchTimerRef.current) {
      clearTimeout(searchTimerRef.current)
      searchTimerRef.current = null
    }
    cancelPendingRequest()

    // Reset state
    setQuery('')
    setSearchedQuery('')
    setIsTyping(false)
    setSearchMode(false)
    setError(null)
    setSelectedCategory(null)

    // Fetch homepage
    fetchPeople(true, null)
  }

  const toggleExpand = (id) => {
    setExpandedId(expandedId === id ? null : id)
  }

  const getStatsText = () => {
    if (isTyping) {
      return 'searching...'
    }
    if (searchMode && searchedQuery) {
      const count = people.length
      return `found ${count} ${count === 1 ? 'person' : 'people'} matching "${searchedQuery}"`
    }
    if (selectedCategory) {
      const count = people.length
      return `${count} ${count === 1 ? 'person' : 'people'} in ${selectedCategory}`
    }
    if (stats) {
      return <>exploring <AnimatedNumber value={stats.with_work_summary} /> people's work</>
    }
    return ''
  }

  return (
    <div className="app">
      {/* floaty decorative blobs */}
      <span className="blob b1" aria-hidden="true" />
      <span className="blob b2" aria-hidden="true" />
      <span className="blob b3" aria-hidden="true" />
      <span className="blob b4" aria-hidden="true" />
      <span className="blob b5" aria-hidden="true" />

      <nav className="topnav">
        <div className="topnav-inner">
          <button className="topnav-brand" onClick={() => goTo('home')}>
            quiet <span className="accent">humans</span><span className="dot">.</span>
          </button>
          <div className="topnav-links">
            <button className={view === 'home' ? 'active' : ''} onClick={() => goTo('home')}>explore</button>
            <button className={view === 'funnel' ? 'active' : ''} onClick={() => goTo('funnel')}>the funnel</button>
          </div>
        </div>
      </nav>

      {view === 'funnel' ? (
        <FunnelPage funnel={funnel} crawlStats={crawlStats} onExplore={() => goTo('home')} />
      ) : (
      <>
      <header className="header">
        <div className="brand-row">
          <h1 className="anim-up d1">
            quiet <span className="accent">humans</span><span className="dot">.</span>
          </h1>
          <Pip className="anim d2" />
        </div>

        <p className="tagline anim-up d3">
          a search engine for the <span className="u-wavy">interesting people</span> the internet forgot.
        </p>

        {/* SEARCH — the primary action the moment you land */}
        <div className="hero-search anim-up d4">
          <form className="search-form" onSubmit={handleSearch}>
            <div className="search-box">
              <Search className="search-icon" size={20} />
              <input
                type="text"
                placeholder="search by what people make — e.g. “tools for thought”"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="search-input"
                aria-label="Search the index"
                autoFocus
              />
              {query && (
                <button type="button" className="clear-btn" onClick={clearSearch} aria-label="Clear search">
                  <X size={16} />
                </button>
              )}
            </div>
          </form>
          <button
            className="shuffle-btn"
            onClick={shufflePeople}
            disabled={loading}
            title="Show different people"
          >
            <RefreshCw size={18} className={loading ? 'spinning' : ''} />
            <span>shuffle</span>
          </button>
        </div>

        <div className="hero-examples anim-up d5">
          <span className="hero-examples-label">try</span>
          {['makes generative art', 'tools for thought', 'cozy games', 'self-hosting'].map((ex) => (
            <button key={ex} className="example-chip" onClick={() => setQuery(ex)}>{ex}</button>
          ))}
        </div>

        <LiveBand
          stats={stats}
          crawlStats={crawlStats}
          events={crawlerEvents}
          onSeeFunnel={() => goTo('funnel')}
        />
      </header>

      <main className="main">
        {categories.length > 0 && !searchMode && (
          <div className="category-filters">
            {categories.map((cat) => (
              <button
                key={cat.name}
                className={`category-chip ${selectedCategory === cat.name ? 'active' : ''} category-${cat.name}`}
                onClick={() => selectCategory(cat.name)}
              >
                {cat.name}
              </button>
            ))}
            {selectedCategory && (
              <button
                className="category-chip clear-filter"
                onClick={() => selectCategory(null)}
              >
                <X size={12} />
                clear
              </button>
            )}
          </div>
        )}

        <p className="stats-line">
          {getStatsText()}
          {newApprovalCount > 0 && (
            <span className="new-approval-badge">
              +{newApprovalCount} new!
            </span>
          )}
          <CrawlerHint events={crawlerEvents} onClick={() => setShowCrawlerLog(true)} />
        </p>

        {loading ? (
          <div className="loading">
            <Pip small />
            <p>finding interesting work…</p>
          </div>
        ) : (
          <div className="people-grid">
            {people.map((person) => (
              <article
                key={person.id}
                className={`card ${expandedId === person.id ? 'expanded' : ''}`}
                onClick={() => toggleExpand(person.id)}
              >
                {/* Primary hook - the main thing you see */}
                <p className="hook">
                  {getDisplayHook(person)}
                </p>

                {expandedId === person.id && (
                  <div className="expanded-content">
                    {/* One-liner expansion */}
                    {person.one_liner && person.one_liner !== getDisplayHook(person) && (
                      <p className="one-liner-detail">{clean(person.one_liner)}</p>
                    )}

                    {/* Work summary for those who want more */}
                    {person.work_summary && (
                      <p className="work-summary">{clean(person.work_summary)}</p>
                    )}

                    {person.current_focus && (
                      <div className="current-focus">
                        <div className="current-focus-header">
                          <span className="status-dot"></span>
                          <span className="current-label">Currently</span>
                        </div>
                        <p className="current-focus-text">{clean(person.current_focus)}</p>
                      </div>
                    )}

                    {person.projects?.length > 0 && (
                      <div className="projects">
                        {person.projects.slice(0, 2).map((project, i) => (
                          <div key={i} className="project">
                            <span className="project-name">{clean(project.name)}</span>
                            {project.description && (
                              <span className="project-desc"> — {clean(project.description)}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="card-footer">
                  <div className="person-info">
                    <span className="person-name">{clean(person.name) || 'Anonymous builder'}</span>
                    {person.category && person.category !== 'other' && (
                      <span className={`category-tag category-${person.category}`}>
                        {person.category}
                      </span>
                    )}
                  </div>
                  <a
                    href={person.homepage_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="visit-link"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ExternalLink size={14} />
                  </a>
                </div>
              </article>
            ))}
          </div>
        )}

        {/* Loading more indicator */}
        {loadingMore && (
          <div className="loading-more">
            <Sparkles className="loading-icon-small" size={18} />
            <span>loading more...</span>
          </div>
        )}

        {/* End of results */}
        {!loading && !loadingMore && !hasMore && people.length > 0 && !searchMode && (
          <div className="end-of-results">
            <p>that's everyone we've found so far ✦</p>
          </div>
        )}

        {!loading && people.length === 0 && (
          <div className="empty">
            <Pip small />
            <p>{error ? "something went wrong — couldn't load" : "hmm, no one found with that search"}</p>
            <button onClick={clearSearch} className="reset-btn">
              {error ? 'try again' : 'show everyone'}
            </button>
          </div>
        )}
      </main>

      <StorySections />
      </>
      )}

      <footer className="footer">
        <p><span className="brand-dot" />discovering the interesting people the internet forgot</p>
      </footer>

      {/* Crawler Status Panel */}
      <CrawlerPanel
        events={crawlerEvents}
        isOpen={showCrawlerLog}
        onToggle={() => setShowCrawlerLog(!showCrawlerLog)}
      />

      {/* Person of the Day — collapsed to a pill by default so it never covers cards */}
      {view === 'home' && featuredPerson && !featuredDismissed && !featuredOpen && (
        <button className="featured-pill" onClick={() => setFeaturedOpen(true)}>
          <Sparkles size={14} /> person of the day
        </button>
      )}
      {view === 'home' && featuredPerson && !featuredDismissed && featuredOpen && (
        <div
          className={`featured-widget ${featuredExpanded ? 'expanded' : ''}`}
          onClick={() => setFeaturedExpanded(!featuredExpanded)}
        >
          <button className="featured-dismiss" onClick={(e) => { e.stopPropagation(); setFeaturedOpen(false); setFeaturedExpanded(false) }}>
            <X size={12} />
          </button>
          <div className="featured-label">
            <Sparkles size={12} />
            <span>person of the day</span>
            <ChevronDown size={12} className={`featured-chevron ${featuredExpanded ? 'open' : ''}`} />
          </div>
          <p className="featured-hook">{getDisplayHook(featuredPerson)}</p>
          {featuredExpanded && (
            <div className="featured-expanded">
              {featuredPerson.work_summary && (
                <p className="featured-summary">{clean(featuredPerson.work_summary)}</p>
              )}
              {featuredPerson.current_focus && (
                <div className="featured-focus">
                  <span className="status-dot"></span>
                  <span>{clean(featuredPerson.current_focus)}</span>
                </div>
              )}
              {featuredPerson.projects?.length > 0 && (
                <div className="featured-projects">
                  {featuredPerson.projects.slice(0, 2).map((project, i) => (
                    <div key={i} className="featured-project">
                      <span className="project-name">{clean(project.name)}</span>
                      {project.description && <span className="project-desc"> — {clean(project.description)}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="featured-footer">
            <span className="person-name">{clean(featuredPerson.name)}</span>
            <a
              href={featuredPerson.homepage_url}
              target="_blank"
              rel="noopener noreferrer"
              className="featured-visit"
              onClick={(e) => e.stopPropagation()}
            >
              visit <ExternalLink size={12} />
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

// Pip — the little crawler bot mascot (pure CSS)
function Pip({ small = false, className = '' }) {
  return (
    <div className={`bot bot--bob ${small ? 'bot--sm' : ''} ${className}`} aria-hidden="true">
      <div className="antenna" />
      <div className="body" />
      <div className="face"><span className="eye" /><span className="eye" /></div>
      <div className="cheek l" /><div className="cheek r" />
      <div className="foot l" /><div className="foot r" />
    </div>
  )
}

// ---- LiveBand: "the machine, right now" ----------------------------------
function LiveBand({ stats, crawlStats, events, onSeeFunnel }) {
  const grouped = groupEventsByUrl(events || [])
  const active = grouped.filter(g => g.status === 'processing')
  const live = isRecentlyActive(events) || active.length > 0
  const nowDomain = active[0]?.domain
  const lastFound = grouped.find(g => g.status === 'approved')?.name

  const approved = crawlStats?.people?.approved ?? stats?.total_people ?? 0
  const inReview = crawlStats?.people?.pending_review ?? 0
  const crawled = crawlStats?.queue?.crawled ?? 0
  const queued = crawlStats?.queue?.pending ?? 0

  return (
    <section className="live-band anim-up d6">
      <div className="live-now">
        <span className={`live-pip-dot ${live ? 'on' : ''}`} />
        {live && nowDomain ? (
          <span>reading <strong>{nowDomain}</strong> right now</span>
        ) : lastFound ? (
          <span>just found <strong>{lastFound}</strong></span>
        ) : (
          <span>quietly crawling the web</span>
        )}
      </div>

      <div className="live-stats">
        <LiveTile n={approved} label="searchable" accent="mint" />
        <LiveTile n={inReview} label="in review" accent="sky" />
        <LiveTile n={crawled} label="read" accent="coral" />
        <LiveTile n={queued} label="queued" accent="lav" />
      </div>

      <div className="live-meta">
        <span className="local-badge"><Laptop size={14} /> one Mac · zero cloud AI</span>
        <button className="link-arrow" onClick={onSeeFunnel}>how we choose <ArrowRight size={14} /></button>
      </div>
    </section>
  )
}

function LiveTile({ n, label, accent }) {
  return (
    <div className={`live-tile tile-${accent}`}>
      <span className="live-tile-n"><AnimatedNumber value={n} /></span>
      <span className="live-tile-label">{label}</span>
    </div>
  )
}

// ---- StorySections: the deck's narrative, condensed --------------------------
function StorySections() {
  return (
    <div className="story">
      <section className="story-band band-cream">
        <span className="kicker">the problem</span>
        <h2>the web rewards the <span className="u-wavy">loud</span>.</h2>
        <p>the people quietly building the most interesting things never trend — no threads, no “top 100” lists, just a personal site and real work.</p>
      </section>

      <section className="story-band band-mint">
        <span className="kicker">the idea</span>
        <h2>search people by <span className="u-wavy">what they make</span>.</h2>
        <p>not <i>“react developer, 5 yrs experience”</i> — but <b>“makes generative art from git commits.”</b> we read their work, you search it by meaning.</p>
      </section>

      <section className="story-band band-ink">
        <span className="kicker">the twist</span>
        <h2>…and it all runs on <span className="mark">one Mac.</span></h2>
        <p>no cloud AI. Gemma + EmbeddingGemma + Qdrant + Postgres + the crawler, all on a single machine at home. free, private, and a little stubborn.</p>
      </section>
    </div>
  )
}

// ---- FunnelPage: educational "how selectively Pip puts pages out" ------------
function FunnelPage({ funnel, crawlStats, onExplore }) {
  const q = funnel?.queue || crawlStats?.queue || {}
  const p = funnel?.people || crawlStats?.people || {}

  const discovered = (q.pending || 0) + (q.in_progress || 0) + (q.crawled || 0) + (q.failed || 0)
  const crawled = q.crawled || 0
  const profiled = (p.approved || 0) + (p.pending_review || 0) + (p.rejected || 0)
  const reviewed = (p.approved || 0) + (p.rejected || 0)
  const approved = p.approved || 0

  const stages = [
    { key: 'discovered', n: discovered, color: 'lav',   title: 'discovered',  blurb: 'URLs we find from Hacker News, GitHub “awesome” lists, webrings, blogrolls & now-pages.' },
    { key: 'crawled',    n: crawled,    color: 'sky',    title: 'read',        blurb: 'the crawler visits and reads the site — about, projects, now, and blog pages.', note: (q.pending ? `${q.pending.toLocaleString()} still waiting their turn` : null) },
    { key: 'profiled',   n: profiled,   color: 'coral',  title: 'profiled',    blurb: 'a tiny local model reads the pages and writes up who the person is and what they build.' },
    { key: 'reviewed',   n: reviewed,   color: 'sun',    title: 'reviewed',    blurb: 'kept or set aside — is this a real person doing genuinely interesting work?', note: (p.pending_review ? `${p.pending_review} still in review` : null) },
    { key: 'approved',   n: approved,   color: 'mint',   title: 'searchable',  blurb: 'approved, embedded as a vector, and live in semantic search.' },
  ]
  // log scale: the range (thousands → tens) is too wide for a linear bar
  const lmax = Math.log(Math.max(discovered, 1) + 1)

  return (
    <div className="funnel-page">
      <header className="funnel-head">
        <span className="kicker">how it works, in numbers</span>
        <h1>we're <span className="accent">picky</span>.</h1>
        <p className="tagline">thousands of URLs go in. only a few real, interesting humans come out. here’s every stage and how many make it through.</p>
      </header>

      <div className="funnel">
        {stages.map((s, i) => {
          const prev = i === 0 ? null : stages[i - 1].n
          const pct = prev ? Math.round((s.n / Math.max(prev, 1)) * 100) : null
          const width = Math.max(16, Math.round((Math.log(s.n + 1) / lmax) * 100))
          return (
            <div className="funnel-row" key={s.key} style={{ animationDelay: `${i * 0.09}s` }}>
              <div className="funnel-meta">
                <span className="funnel-stage-name">{s.title}</span>
                <span className="funnel-count"><AnimatedNumber value={s.n} /></span>
              </div>
              <div className="funnel-bar-track">
                <div className={`funnel-bar bar-${s.color}`} style={{ width: `${width}%` }}>
                  <span className="funnel-bar-n">{s.n.toLocaleString()}</span>
                </div>
                {pct !== null && <span className="funnel-pct">{pct}% of previous stage</span>}
              </div>
              <p className="funnel-blurb">{s.blurb}{s.note && <span className="funnel-note"> · {s.note}</span>}</p>
            </div>
          )
        })}
      </div>

      <div className="funnel-kicker-line">
        <Pip small />
        <p>that’s a <strong>{discovered ? Math.max(1, Math.round(discovered / Math.max(approved, 1))) : '—'}-to-1</strong> filter from discovered URL to searchable human.</p>
        <button className="reset-btn" onClick={onExplore}>explore who made it through</button>
      </div>
    </div>
  )
}

function AnimatedNumber({ value }) {
  const [display, setDisplay] = useState(0)
  const prevRef = useRef(0)

  useEffect(() => {
    if (!value || value === prevRef.current) return
    const start = prevRef.current
    const end = value
    const duration = 800
    const startTime = Date.now()

    const tick = () => {
      const elapsed = Date.now() - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(start + (end - start) * eased))
      if (progress < 1) requestAnimationFrame(tick)
      else prevRef.current = end
    }
    requestAnimationFrame(tick)
  }, [value])

  return <>{display.toLocaleString()}</>
}

// Repair display-only mojibake (e.g. "KateÅ™ina MedvÄ›dovÃ¡" → "Kateřina Medvědová").
// Maps each char back to its byte (Latin-1 + the cp1252 0x80-0x9F range) and re-decodes
// as UTF-8. The strict decoder bails on anything that isn't real mojibake, so correct
// Unicode (Søren, Zoë, 北京, smart quotes, emoji) passes through untouched.
const CP1252 = { 0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f }
function clean(text) {
  if (!text || !/[^\x00-\x7f]/.test(text)) return text
  try {
    const bytes = []
    for (const ch of text) {
      const cp = ch.codePointAt(0)
      if (cp <= 0xff) bytes.push(cp)
      else if (CP1252[cp] != null) bytes.push(CP1252[cp])
      else return text
    }
    return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes))
  } catch {
    return text
  }
}

function getDisplayHook(person) {
  // For search results, use the search snippet if it's good
  if (person.search_snippet && !person.search_snippet.toLowerCase().includes('no match')) {
    return clean(person.search_snippet)
  }

  // Use hook if available (new field)
  if (person.hook) {
    return clean(person.hook)
  }

  // Fall back to one_liner (show complete, no truncation)
  if (person.one_liner) {
    return clean(person.one_liner)
  }

  // Last resort: first sentence of work_summary
  if (person.work_summary) {
    const firstSentence = person.work_summary.split('.')[0]
    return clean(firstSentence + '.')
  }

  return 'Exploring something interesting...'
}

function formatTime(timestamp) {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = (now - date) / 1000

  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return date.toLocaleDateString()
}

function isRecentlyActive(events) {
  if (!events || events.length === 0) return false
  const latestEvent = events[0]
  if (!latestEvent?.timestamp) return false

  const eventTime = new Date(latestEvent.timestamp)
  const now = new Date()
  const diffSeconds = (now - eventTime) / 1000

  // Consider active if last event was within 60 seconds
  return diffSeconds < 60
}

function extractDomain(url) {
  try {
    const parsed = new URL(url)
    return parsed.hostname.replace('www.', '')
  } catch {
    return url.slice(0, 30)
  }
}

// Group events by URL and determine status
function groupEventsByUrl(events) {
  const groups = {}

  // Process events in chronological order (oldest first) to build timeline
  const chronological = [...events].reverse()

  chronological.forEach(event => {
    const domain = extractDomain(event.url)

    if (!groups[domain]) {
      groups[domain] = {
        url: event.url,
        domain,
        events: [],
        status: 'processing',
        name: null,
        score: null,
        reason: null,
        pages: null,
        latestTimestamp: event.timestamp,
        stages: {
          started: false,
          classified: false,
          crawled: false,
          extracted: false,
          reviewed: false
        }
      }
    }

    const group = groups[domain]
    group.events.push(event)
    group.latestTimestamp = event.timestamp

    // Track stages
    if (event.event_type === 'started') group.stages.started = true
    if (event.event_type === 'classified') group.stages.classified = true
    if (event.event_type === 'crawled') {
      group.stages.crawled = true
      group.pages = event.details?.pages
    }
    if (event.event_type === 'extracted') {
      group.stages.extracted = true
      group.name = event.details?.name
    }

    // Final statuses
    if (event.event_type === 'approved' || event.event_type === 'saved') {
      group.status = 'approved'
      group.stages.reviewed = true
      if (event.details?.name) group.name = event.details.name
      if (event.details?.score) group.score = event.details.score
      if (event.details?.reason) group.reason = event.details.reason
    } else if (event.event_type === 'rejected') {
      group.status = 'rejected'
      group.stages.reviewed = true
      if (event.details?.name) group.name = event.details.name
      if (event.details?.score) group.score = event.details.score
      if (event.details?.reason) group.reason = event.details.reason
    } else if (event.event_type === 'error') {
      group.status = 'error'
      group.reason = event.details?.error
    } else if (event.event_type === 'skipped') {
      group.status = 'skipped'
      group.reason = event.details?.reason
    }
  })

  // Sort by latest timestamp (most recent first)
  return Object.values(groups).sort((a, b) =>
    new Date(b.latestTimestamp) - new Date(a.latestTimestamp)
  )
}

// CrawlerPanel component
function CrawlerPanel({ events, isOpen, onToggle }) {
  const grouped = groupEventsByUrl(events)

  // Separate active from completed
  const active = grouped.filter(g => g.status === 'processing')
  const completed = grouped.filter(g => g.status !== 'processing')

  const hasActivity = isRecentlyActive(events)

  return (
    <div className={`crawler-panel ${isOpen ? 'open' : ''}`}>
      <button className="crawler-toggle" onClick={onToggle}>
        {hasActivity ? (
          <span className="live-dot" />
        ) : (
          <Activity size={16} />
        )}
        <span>Crawler Activity</span>
        {events.length > 0 && !isOpen && (
          <span className="event-badge">{grouped.length}</span>
        )}
        {isOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>

      {isOpen && (
        <div className="crawler-log">
          {grouped.length === 0 ? (
            <p className="no-events">No recent activity</p>
          ) : (
            <>
              {/* Currently Processing */}
              {active.length > 0 && (
                <div className="crawl-section">
                  <h4 className="section-title">
                    <Loader size={14} className="spinning" />
                    Processing ({active.length})
                  </h4>
                  {active.map((group, i) => (
                    <div key={i} className="crawl-item active">
                      <div className="crawl-header">
                        <span className="crawl-domain">{group.domain}</span>
                        <span className="crawl-time">{formatTime(group.latestTimestamp)}</span>
                      </div>
                      <div className="crawl-pipeline">
                        <PipelineStage done={group.stages.started} label="Start" />
                        <PipelineArrow />
                        <PipelineStage done={group.stages.classified} label="Classify" />
                        <PipelineArrow />
                        <PipelineStage done={group.stages.crawled} label={group.pages ? `${group.pages} pages` : "Crawl"} />
                        <PipelineArrow />
                        <PipelineStage done={group.stages.extracted} label={group.name || "Extract"} />
                        <PipelineArrow />
                        <PipelineStage done={group.stages.reviewed} label="Review" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Completed */}
              {completed.length > 0 && (
                <div className="crawl-section">
                  <h4 className="section-title">Recent Results</h4>
                  {completed.map((group, i) => (
                    <div key={i} className={`crawl-item result ${group.status}`}>
                      <div className="crawl-header">
                        <span className="result-icon">
                          {group.status === 'approved' && <CheckCircle size={16} />}
                          {group.status === 'rejected' && <XCircle size={16} />}
                          {group.status === 'error' && <AlertCircle size={16} />}
                          {group.status === 'skipped' && <XCircle size={16} />}
                        </span>
                        <span className="result-info">
                          {group.name ? (
                            <>
                              <strong>{group.name}</strong>
                              {group.score && <span className="result-score">{group.score}/10</span>}
                            </>
                          ) : (
                            <span className="result-domain">{group.domain}</span>
                          )}
                        </span>
                        <span className="crawl-time">{formatTime(group.latestTimestamp)}</span>
                      </div>
                      {group.reason && (
                        <p className="result-reason">{group.reason.slice(0, 100)}{group.reason.length > 100 ? '...' : ''}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function PipelineStage({ done, label }) {
  return (
    <span className={`pipeline-stage ${done ? 'done' : ''}`}>
      {done ? <CheckCircle size={12} /> : <span className="stage-dot" />}
      <span className="stage-label">{label}</span>
    </span>
  )
}

function PipelineArrow() {
  return <span className="pipeline-arrow">→</span>
}

// Subtle crawler hint that shows on hover
function CrawlerHint({ events, onClick }) {
  const grouped = groupEventsByUrl(events)
  const active = grouped.filter(g => g.status === 'processing')
  const hasActivity = isRecentlyActive(events)

  if (!hasActivity && active.length === 0) {
    return null
  }

  return (
    <span className="crawler-hint" onClick={onClick}>
      <span className="crawler-hint-dot" />
      <span className="crawler-hint-text">
        crawling {active.length > 0 ? active[0].domain : '...'}
      </span>
      {active.length > 0 && (
        <span className="crawler-hint-tooltip">
          <strong>Currently crawling:</strong>
          {active.slice(0, 3).map((g, i) => (
            <div key={i} className="tooltip-item">
              {g.domain}
              {g.name && <span className="tooltip-name"> — {g.name}</span>}
            </div>
          ))}
          {active.length > 3 && <div className="tooltip-more">+{active.length - 3} more</div>}
        </span>
      )}
    </span>
  )
}

export default App
