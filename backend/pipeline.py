"""URL processing pipeline for discovering and profiling personal websites."""



import time          # to measure how long things take, and to pause between rounds
import argparse      # to read the options you type after the command (e.g. --continuous)

from concurrent.futures import ThreadPoolExecutor, as_completed   # to crawl several sites at once
from threading import Lock                                        # keeps shared counters tidy when crawling in parallel

from database import (
    get_pending_urls, mark_url_crawled, upsert_person, add_to_queue,
    get_queue_stats, reset_stale_in_progress, save_staged_projects
)

from crawler import crawl_homepage
from crawler import deep_crawl_site, summarize_crawl, CrawledPage
from crawler import classify_site

from process import fetch_github_enrichment
from process import extract_person_data_from_pages
from process import filter_and_score_pages
from process import CATEGORIES   # the fixed list of allowed categories (software, writing, music...)
from projects import extract_projects   # pulls out the person's real creations

from database import (
    log_started, log_classified, log_crawled, log_extracted,
    log_saved, log_error
)


# Thread-safe counters for batch processing statistics.
_stats_lock = Lock()
_stats = {"success": 0, "failed": 0, "in_progress": 0}


def process_url(url: str, deep_crawl: bool = True, max_pages: int = 50) -> bool:
    """Extract and save a person's profile from their website. Thread-safe."""

    import threading
    thread_id = threading.current_thread().name

    # Mark that one more site is being worked on right now.
    with _stats_lock:
        _stats["in_progress"] += 1

    try:
        log_started(url)   # write "started processing X" to the activity feed


        # Fetch and read the homepage.
        homepage = crawl_homepage(url)

        if homepage.get("error"):
            # Couldn't even load the page — note the failure and stop.
            log_error(url, homepage["error"])
            mark_url_crawled(url, success=False, error=homepage["error"])
            return False

        raw_text = homepage.get("raw_text", "")


        # Classify the site; reject non-personal sites.

        classification = classify_site(url, raw_text)

        if not classification.is_personal:
            log_classified(url, False, classification.reason)
            mark_url_crawled(url, success=False, error=f"Not personal: {classification.reason}")
            return False

        log_classified(url, True, classification.reason)


        # Crawl linked pages (about, projects, now, blog) or use homepage only.

        if deep_crawl:
            all_pages = deep_crawl_site(url, max_pages=max_pages, max_depth=3)
        else:
            all_pages = [CrawledPage(
                url=url,
                path="/",
                title=homepage.get("title", ""),
                text=raw_text,
                text_length=len(raw_text),
                links=homepage.get("links", []),
                depth=0,
                is_priority=True,
            )]

        summary = summarize_crawl(all_pages)
        log_crawled(url, summary["total_pages"], summary["total_text_chars"])

        if not all_pages:
            mark_url_crawled(url, success=False, error="No pages found")
            return False


        # Select the most relevant pages for AI analysis.

        selected_pages = filter_and_score_pages(
            all_pages,
            max_final=10,
            heuristic_min_score=15.0,
            heuristic_max_candidates=25,
        )

        if not selected_pages:
            mark_url_crawled(url, success=False, error="No interesting pages")
            return False


        # Extract person data using AI; check for /now page as a special signal.

        now_page = None
        for page in all_pages:
            if page.path.lower() in ["/now", "/now/"]:
                now_page = page
                break

        # The AI turns the raw pages into structured facts: name, hook, projects.
        extracted = extract_person_data_from_pages(
            selected_pages,
            homepage_title=homepage.get("title"),
            now_page_text=now_page.text if now_page else None,
        )

        if extracted.get("error"):
            mark_url_crawled(url, success=False, error=f"Extraction failed: {extracted['error']}")
            return False

        name = extracted.get("name", "Unknown")
        projects_count = len(extracted.get("projects", []))
        log_extracted(url, name, projects_count)


        # Save the profile as pending_review; approval is done separately.

        # Make sure the category is one we recognise; otherwise call it "other".
        category = extracted.get("category", "other")
        if category not in CATEGORIES:
            category = "other"

        # If we found a GitHub username on the site, fetch their top languages
        # and repos to enrich the profile.
        github_username = homepage.get("github_username")
        github_data = fetch_github_enrichment(github_username) if github_username else {}

        # Assemble everything we know into one tidy record to save.
        person = {
            "homepage_url": url,
            "name": extracted.get("name"),
            "hook": extracted.get("hook"),
            "work_summary": extracted.get("work_summary"),
            "one_liner": extracted.get("one_liner"),
            "unique_angle": extracted.get("unique_angle"),
            "current_focus": extracted.get("current_focus"),
            "category": category,
            "projects": extracted.get("projects", []),
            "creative_interests": extracted.get("creative_interests", []),
            "domains": extracted.get("domains", []),
            "makes": extracted.get("makes", []),
            "github_username": github_username,
            "github_languages": github_data.get("github_languages", []),
            "github_top_repos": github_data.get("github_top_repos", []),
            "social_links": homepage.get("social_links", {}),
            "status": "pending_review",   # always pending — approval comes later
        }

        if now_page:
            person["now_page_url"] = now_page.url

        # Write the person to the database and mark this URL as done.
        try:
            person_id = upsert_person(person)
            mark_url_crawled(url, success=True)
            log_saved(url, name, person_id)

            # Extract and stage projects; they require approval before indexing.
            try:
                creations = extract_projects(selected_pages)
                if creations:
                    save_staged_projects(person_id, url, creations)
                    print(f"  Staged {len(creations)} creation(s) for {name}")
            except Exception as e:
                print(f"  Project staging skipped: {e}")

            return True

        except Exception as e:
            log_error(url, str(e))
            mark_url_crawled(url, success=False, error=str(e))
            return False

    except Exception as e:
        # Catch-all to prevent a single site failure from crashing the pipeline.
        log_error(url, str(e))
        try:
            mark_url_crawled(url, success=False, error=str(e))
        except Exception as db_err:
            log_error(url, f"DB update also failed: {db_err}")
        print(f"[{thread_id}] FAILED: {url[:60]} - {str(e)[:80]}")
        return False

    finally:
        # Decrement in-progress counter regardless of outcome.
        with _stats_lock:
            _stats["in_progress"] -= 1


def process_batch(batch_size: int = 100, workers: int = 10, deep_crawl: bool = True):
    """Process a batch of URLs from the queue, optionally in parallel."""

    global _stats

    # Claim a batch of pending URLs from the to-do list.
    print(f"Fetching {batch_size} URLs from queue...")
    urls = get_pending_urls(limit=batch_size)

    if not urls:
        print("No pending URLs in queue")
        return

    print(f"Processing {len(urls)} URLs with {workers} worker(s)...")

    # Reset the tally for this batch.
    with _stats_lock:
        _stats = {"success": 0, "failed": 0, "in_progress": 0}
    start_time = time.time()

    if workers <= 1:
        # Sequential processing.
        for url in urls:
            try:
                success = process_url(url, deep_crawl=deep_crawl)
                with _stats_lock:
                    if success:
                        _stats["success"] += 1
                    else:
                        _stats["failed"] += 1
            except Exception as e:
                print(f"  Error processing {url}: {e}")
                with _stats_lock:
                    _stats["failed"] += 1

    else:
        # Parallel processing with worker pool.
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {
                executor.submit(process_url, url, deep_crawl): url
                for url in urls
            }

            # Track results and print progress periodically.
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    success = future.result()
                    with _stats_lock:
                        if success:
                            _stats["success"] += 1
                        else:
                            _stats["failed"] += 1

                    total_done = _stats["success"] + _stats["failed"]
                    if total_done % 10 == 0:
                        elapsed = time.time() - start_time
                        rate = total_done / elapsed if elapsed > 0 else 0
                        print(f"  Progress: {total_done}/{len(urls)} ({rate:.1f}/sec) "
                              f"ok={_stats['success']} err={_stats['failed']} active={_stats['in_progress']}")

                except Exception as e:
                    print(f"  Error processing {url}: {e}")
                    with _stats_lock:
                        _stats["failed"] += 1

    # Print batch summary.
    elapsed = time.time() - start_time
    rate = len(urls) / elapsed if elapsed > 0 else 0

    print(f"\n{'='*60}")
    print(f"Batch complete in {elapsed:.1f}s ({rate:.1f} URLs/sec)")
    print(f"  Success: {_stats['success']}")
    print(f"  Failed: {_stats['failed']}")
    print("=" * 60)


def replenish_queue(min_pending: int = 100, target_add: int = 5000):
    """Discover and queue new URLs from configured sources when queue is low."""

    try:
        # How many URLs are still waiting? If plenty, do nothing.
        queue_stats = get_queue_stats()
        pending = queue_stats.get("pending", 0)

        if pending >= min_pending:
            return

        print(f"\nQueue low ({pending} pending). Discovering URLs from all sources...")

        from collections import defaultdict
        from discovery import crawl_all_sources

        added = 0
        batches = defaultdict(list)   # real source name -> URLs waiting to be saved
        queued = 0                    # how many URLs are waiting in `batches` right now
        seen = set()                  # URLs already seen this run, so we skip repeats

        # Preserve the original source for each discovered URL for later analysis.
        for discovered in crawl_all_sources(enabled_only=True):
            url = discovered.url
            if url in seen:
                continue
            seen.add(url)

            batches[discovered.source].append(url)
            queued += 1

            # Batch insert for efficiency; preserve source tagging.
            if queued >= 200:
                for src, urls in batches.items():
                    added += add_to_queue(urls, source=src)
                batches.clear()
                queued = 0
                print(f"  Added {added} URLs so far...")

            # Stop after reaching target count.
            if added >= target_add:
                break

        # Insert remaining URLs from final incomplete batch.
        for src, urls in batches.items():
            added += add_to_queue(urls, source=src)

        print(f"  Total added: {added} URLs (each tagged with its real source)")

    except Exception as e:
        print(f"Error replenishing queue: {e}")
        import traceback
        traceback.print_exc()


def run(batch_size: int = 100, workers: int = 10, deep_crawl: bool = True,
        continuous: bool = False, min_queue: int = 100):
    """Run one or more batches, optionally in continuous mode."""

    if not continuous:
        process_batch(batch_size, workers, deep_crawl)
        return
    print("Starting continuous pipeline...")
    print(f"  Batch size: {batch_size}")
    print(f"  Workers: {workers}")
    print(f"  Deep crawl: {deep_crawl}")
    print(f"  Min queue before replenish: {min_queue}")
    print("  Press Ctrl+C to stop\n")

    try:
        while True:

            # Reset stale in-progress entries from crashes.
            stale_reset = reset_stale_in_progress(stale_minutes=30)
            if stale_reset > 0:
                print(f"Reset {stale_reset} stale in_progress URLs")

            # Replenish queue if needed.
            replenish_queue(min_pending=min_queue, target_add=5000)

            # Process next batch.
            process_batch(batch_size, workers, deep_crawl)

            # Wait before next iteration.
            print("\nWaiting 10s before next batch...")
            time.sleep(10)

    except KeyboardInterrupt:
        print("\nStopped by user")


def main():
    """Entry point: parse args and execute pipeline."""

    parser = argparse.ArgumentParser(description="URL processing pipeline")
    parser.add_argument("--batch", type=int, default=100, help="Batch size")
    parser.add_argument("--workers", type=int, default=10, help="Parallel workers (1=sequential)")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--url", type=str, help="Process a single URL")
    parser.add_argument("--no-deep", action="store_true", help="Disable deep crawl")
    parser.add_argument("--min-queue", type=int, default=100, help="Min queue size before replenish")

    args = parser.parse_args()
    deep_crawl = not args.no_deep

    if args.url:
        # Process single URL.
        success = process_url(args.url, deep_crawl=deep_crawl)
        print(f"Result: {'Success' if success else 'Failed'}")
    else:
        # Run batch or continuous mode.
        run(
            batch_size=args.batch,
            workers=args.workers,
            deep_crawl=deep_crawl,
            continuous=args.continuous,
            min_queue=args.min_queue,
        )


if __name__ == "__main__":
    main()
