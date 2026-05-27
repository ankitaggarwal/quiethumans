"""MCP server for profile curation.

Provides authenticated remote access to approve/reject profiles and edit profile text.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from psycopg2.extras import RealDictCursor
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import MCP_TOKEN
from database import get_connection, update_person_text, approve_person, reject_person


# FastMCP instance. DNS rebinding protection is disabled because the server
# runs on a public domain with TLS termination handled upstream.
mcp = FastMCP("quiethumans",
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


# Tools exposed to MCP client

@mcp.tool()
def search_profiles(status: str = None, limit: int = 20, query: str = None) -> list:
    """List profiles (id, name, hook, one_liner).

    Pass status='pending_review' to find the profiles waiting for an
    approve/reject decision. Optionally filter by a name/one-liner search term.
    """
    with get_connection() as c:
        cur = c.cursor(cursor_factory=RealDictCursor)

        # Build query with optional status and search filters.
        clauses, params = [], []
        if status:
            clauses.append("status = %s"); params.append(status)
        if query:
            clauses.append("(name ILIKE %s OR one_liner ILIKE %s)"); params += [f"%{query}%", f"%{query}%"]

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(limit, 100))   # cap results at 100

        cur.execute(f"SELECT id, name, hook, one_liner FROM people {where} ORDER BY id DESC LIMIT %s", params)
        return [dict(r) for r in cur.fetchall()]


@mcp.tool()
def get_profile(id: int) -> dict:
    """Get one complete profile by its id, with every field filled in."""
    with get_connection() as c:
        cur = c.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM people WHERE id = %s", (id,))
        r = cur.fetchone()
        return dict(r) if r else {}


@mcp.tool()
def update_profile(id: int, fields: dict) -> dict:
    """Rewrite a profile's text.

    Only these fields may be changed: hook, one_liner, work_summary,
    current_focus, unique_angle. (The database layer enforces that list.)
    """
    return update_person_text(id, fields)


@mcp.tool()
def approve_profile(id: int, score: int = 7) -> dict:
    """Approve a profile so it appears in the public directory and in search.

    score (1-10) is how interesting the person is. Approving also creates the
    person's "meaning fingerprint" and adds it to the search index.
    """
    ok = approve_person(id, score)
    return {"approved": ok, "id": id, "score": score}


@mcp.tool()
def reject_profile(id: int) -> dict:
    """Reject a profile so it never shows up in the directory or in search.

    This also removes the person from the search index, in case they were
    indexed before.
    """
    ok = reject_person(id)
    return {"rejected": ok, "id": id}


# Authentication middleware

class _BearerAuth(BaseHTTPMiddleware):
    """Validates Bearer token on each request."""
    async def dispatch(self, request, call_next):
        if request.headers.get("authorization", "") != f"Bearer {MCP_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_mcp_app():
    """Build the MCP app with authentication, or return None if disabled.

    Returns None if MCP_TOKEN is not set; otherwise returns the configured app.
    """
    if not MCP_TOKEN:
        return None
    app = mcp.sse_app()
    app.add_middleware(_BearerAuth)
    return app
