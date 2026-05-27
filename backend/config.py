"""Configuration module for environment settings.

Reads database credentials, API keys, and other settings from environment variables.
"""

import os
import random
from typing import Any


# Qdrant vector database for semantic search.
QDRANT_URL        = os.environ.get("QDRANT_URL", "")
QDRANT_KEY        = os.environ.get("QDRANT_KEY", "")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "quiet-humans")  # 768-number fingerprints

# Self-hosted LLM for generation and embeddings.
LOCAL_LLM_URL   = os.environ.get("LOCAL_LLM_URL", "")
LOCAL_LLM_KEY   = os.environ.get("LOCAL_LLM_KEY", "")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")

# GitHub API token for increased rate limits.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Main database connection string.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# MCP server authentication token.
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")


# Browser User-Agent strings for web requests.

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]


def get_headers() -> dict:
    """Return HTTP headers with a random User-Agent."""
    return {"User-Agent": random.choice(USER_AGENTS)}


def render_prompt(template: str, **kwargs: Any) -> str:
    """Format a prompt template by substituting placeholder variables."""
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template
