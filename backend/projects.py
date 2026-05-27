"""Extract user creations from crawled pages using LLM-powered filtering.

Distinguishes actual creative works from commentary and editorial content.
"""

from config import render_prompt
from process import get_expensive_llm


# LLM prompt for filtering creations from noise.
# Empirically tuned to filter by both validity and interestingness.
PROJECT_PROMPT = r"""You are listing the real, INTERESTING creations of one person, for a directory that celebrates indie people who BUILD and MAKE distinctive things.

From the pages below, list only things this person personally made that are worth showing off. For each, write a tight summary of what it is and why it's interesting, and give the URL where it lives.

STEP 1 — Is it a CREATION at all? (include only if YES)
A creation is a tangible thing the person made that exists in the world:
- Software: an app, tool, library, game, bot, hardware device, or a service with a real purpose
- Writing: a published book, novel, zine, or a sustained newsletter / series (a real body of work)
- Music: released songs, albums, EPs
- Art: a series, exhibition, installation, or published illustrations
- Research: a paper, study, or dataset
- A course, curriculum, or substantial tutorial series they authored
NOT a creation (leave out): opinion or commentary posts, reviews, link roundups, news, life updates, journal/"now"/"about me" text, reposting others' work, or anything too vague to tell what was made. Also NOT a creation: a review, overview, or summary of someone else's technology (e.g. "a review of the C++ STL") — explaining other people's work is not something you made.

STEP 2 — Is it INTERESTING? The test is a CREATIVE SPARK, not usefulness.
Score 0-5 and keep only 3 or higher.
KEEP (3-5) if the creation shows ANY of: novelty, originality, playfulness,
curiosity, technical craft, OR a clever / quirky solution to the person's OWN
problem — EVEN IF it has little practical utility. Minor-but-novel is exactly
what we want. Examples that KEEP:
- a heat printer that auto-prints every Shopify order the moment it arrives
- a smart lid that monitors sourdough-starter fermentation
- a 3D-printed engagement ring; a fan controller hacked from an ESP32
- a generative terrain map in p5.js; an AR transit-map filter
- a flexagon construction toy; a text-based interactive-poetry experiment
- a published book or album; an original tool, library, game, or art series
DROP (1-2) only when the creation is GENERIC and shows no creative spark:
- a plain personal blog, life journaling, or an "about / now" page
- bare plumbing: a homelab, dotfiles, a site setup/migration ("my blog built with Hugo")
- by-the-numbers exercises: a todo app, a generic portfolio, "built X with React"
- opinion / commentary, reviews, news, or how-to guides / documentation
- mainly a big team's or employer's work (AAA titles, large-company features) —
  we celebrate the INDIVIDUAL's own creations, not their day job

RULES:
- Be strict on BOTH steps. When unsure whether something is interesting, drop it.
- Every creation needs a concrete name. Include a URL only if one actually appears in the pages.
- The summary must say what the thing IS and why it's interesting — only the essence, no filler, 1-2 sentences.

PAGES:
{pages}

Return JSON:
{{
    "creations": [
        {{
            "name": "Concrete name of the thing",
            "url": "url where it lives, or null",
            "type": "software|writing|music|visual|games|hardware|research|education|other",
            "summary": "1-2 sentences: what it is and why it's interesting",
            "is_creation": true,
            "interesting": 4
        }}
    ]
}}
Only include items that are real creations AND score interesting >= 3. If the person made nothing that clears the bar, return an empty list.
"""


def extract_projects(pages: list, max_chars_total: int = 24000) -> list[dict]:
    """Extract interesting creations from crawled pages; returns empty list on error."""
    if not pages:
        return []

    # Concatenate pages with URLs; limit total size for model input.
    sections, total = [], 0
    for page in pages:
        remaining = max_chars_total - total
        if remaining <= 500:
            break
        text = page.text[:min(len(page.text), remaining - 100)]
        section = f"\n=== PAGE: {page.url} ===\nTitle: {page.title or 'Untitled'}\n{text}\n"
        sections.append(section)
        total += len(section)

    prompt = render_prompt(PROJECT_PROMPT, pages="\n".join(sections))

    try:
        result = get_expensive_llm().complete_json(prompt, max_tokens=1500, temperature=0)
    except Exception as e:
        print(f"  Project extraction error: {e}")
        return []

    creations = result.get("creations", []) if isinstance(result, dict) else []

    # Validate and filter results to ensure well-formed entries meet interestingness threshold.
    clean = []
    for c in creations:
        if not isinstance(c, dict):
            continue
        if not c.get("is_creation", True):
            continue
        try:
            if float(c.get("interesting", 3)) < 3:
                continue
        except (TypeError, ValueError):
            pass
        name = (c.get("name") or "").strip()
        summary = (c.get("summary") or "").strip()
        if not name or not summary:
            continue
        clean.append({
            "name": name[:200],
            "url": (c.get("url") or None),
            "type": (c.get("type") or "other"),
            "summary": summary[:600],
        })
    return clean
