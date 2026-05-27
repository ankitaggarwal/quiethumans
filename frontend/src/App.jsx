import { useState, useEffect, useRef } from 'react'
import { Search, ExternalLink, RefreshCw, Sparkles, ChevronDown, ChevronUp, X, Activity, CheckCircle, XCircle, AlertCircle, Loader } from 'lucide-react'
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
  const [showHowItWorks, setShowHowItWorks] = useState(false)
  const [searchMode, setSearchMode] = useState(false)
  const [showCrawlerLog, setShowCrawlerLog] = useState(false)
  const [crawlerEvents, setCrawlerEvents] = useState([])
  const [newApprovalCount, setNewApprovalCount] = useState(0)
  const [lastKnownCount, setLastKnownCount] = useState(null)
  const [categories, setCategories] = useState([])
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [featuredPerson, setFeaturedPerson] = useState(null)
  const [featuredDismissed, setFeaturedDismissed] = useState(false)
  const [featuredExpanded, setFeaturedExpanded] = useState(false)

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
  }, [])

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
    statsPollRef.current = setInterval(fetchStatsQuietly, 10000)
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
      if (lastKnownCount !== null && data.with_work_summary > lastKnownCount) {
        const newCount = data.with_work_summary - lastKnownCount
        setNewApprovalCount(prev => prev + newCount)
        // Auto-clear notification after 5 seconds
        setTimeout(() => setNewApprovalCount(0), 5000)
      }

      setLastKnownCount(data.with_work_summary)
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
      // Initialize lastKnownCount on first fetch
      if (lastKnownCount === null) {
        setLastKnownCount(data.with_work_summary)
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

      if (Array.isArray(data)) {
        setPeople(data)
      } else {
        setPeople([])
      }
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
      <header className="header">
        <h1>discover interesting humans</h1>
        <p className="tagline">by what they build, not how they brand</p>

        <button
          className={`how-it-works-toggle ${showHowItWorks ? 'active' : ''}`}
          onClick={() => setShowHowItWorks(!showHowItWorks)}
        >
          <span>how it works</span>
          <ChevronDown size={14} className={`toggle-chevron ${showHowItWorks ? 'open' : ''}`} />
        </button>

        {showHowItWorks && (
          <div className="how-it-works">
            <div className="how-step">
              <span className="step-number">1</span>
              <p>We crawl <em>personal websites</em> — people who care about sharing their real work</p>
            </div>
            <div className="how-step">
              <span className="step-number">2</span>
              <p>AI reads each site to find what's <em>genuinely interesting</em> about their work</p>
            </div>
            <div className="how-step">
              <span className="step-number">3</span>
              <p>Search by meaning — try <em>"building tools for thought"</em> and we'll get it</p>
            </div>
          </div>
        )}
      </header>

      <main className="main">
        <div className="controls">
          <form className="search-form" onSubmit={handleSearch}>
            <div className="search-box">
              <Search className="search-icon" size={18} />
              <input
                type="text"
                placeholder="search by what people are building..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="search-input"
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
            <Sparkles className="loading-icon" size={24} />
            <p>finding interesting work...</p>
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
                      <p className="one-liner-detail">{person.one_liner}</p>
                    )}

                    {/* Work summary for those who want more */}
                    {person.work_summary && (
                      <p className="work-summary">{person.work_summary}</p>
                    )}

                    {person.current_focus && (
                      <div className="current-focus">
                        <div className="current-focus-header">
                          <span className="status-dot"></span>
                          <span className="current-label">Currently</span>
                        </div>
                        <p className="current-focus-text">{person.current_focus}</p>
                      </div>
                    )}

                    {person.projects?.length > 0 && (
                      <div className="projects">
                        {person.projects.slice(0, 2).map((project, i) => (
                          <div key={i} className="project">
                            <span className="project-name">{project.name}</span>
                            {project.description && (
                              <span className="project-desc"> — {project.description}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="card-footer">
                  <div className="person-info">
                    <span className="person-name">{person.name || 'Anonymous builder'}</span>
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
            <p>you've seen everyone</p>
          </div>
        )}

        {!loading && people.length === 0 && (
          <div className="empty">
            <p>{error ? "couldn't load results" : "no one found with that search"}</p>
            <button onClick={clearSearch} className="reset-btn">
              {error ? 'try again' : 'show everyone'}
            </button>
          </div>
        )}
      </main>

      <footer className="footer">
        <p>discovering interesting humans across the web</p>
      </footer>

      {/* Crawler Status Panel */}
      <CrawlerPanel
        events={crawlerEvents}
        isOpen={showCrawlerLog}
        onToggle={() => setShowCrawlerLog(!showCrawlerLog)}
      />

      {/* Person of the Day */}
      {featuredPerson && !featuredDismissed && (
        <div
          className={`featured-widget ${featuredExpanded ? 'expanded' : ''}`}
          onClick={() => setFeaturedExpanded(!featuredExpanded)}
        >
          <button className="featured-dismiss" onClick={(e) => { e.stopPropagation(); setFeaturedDismissed(true) }}>
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
                <p className="featured-summary">{featuredPerson.work_summary}</p>
              )}
              {featuredPerson.current_focus && (
                <div className="featured-focus">
                  <span className="status-dot"></span>
                  <span>{featuredPerson.current_focus}</span>
                </div>
              )}
              {featuredPerson.projects?.length > 0 && (
                <div className="featured-projects">
                  {featuredPerson.projects.slice(0, 2).map((project, i) => (
                    <div key={i} className="featured-project">
                      <span className="project-name">{project.name}</span>
                      {project.description && <span className="project-desc"> — {project.description}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="featured-footer">
            <span className="person-name">{featuredPerson.name}</span>
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

function getDisplayHook(person) {
  // For search results, use the search snippet if it's good
  if (person.search_snippet && !person.search_snippet.toLowerCase().includes('no match')) {
    return person.search_snippet
  }

  // Use hook if available (new field)
  if (person.hook) {
    return person.hook
  }

  // Fall back to one_liner (show complete, no truncation)
  if (person.one_liner) {
    return person.one_liner
  }

  // Last resort: first sentence of work_summary
  if (person.work_summary) {
    const firstSentence = person.work_summary.split('.')[0]
    return firstSentence + '.'
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
