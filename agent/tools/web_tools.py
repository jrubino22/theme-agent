from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx


class WebToolError(RuntimeError):
    pass


# --- small HTML helpers (keep minimal; no BeautifulSoup dependency) ---

_RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_RE_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"[ \t]+\n|\n[ \t]+")
_RE_MULTI_NL = re.compile(r"\n{3,}")


def _html_to_text(html: str, *, max_chars: int = 200_000) -> str:
    html = html[: max_chars * 2]  # cap work even if huge
    html = _RE_SCRIPT.sub("", html)
    html = _RE_STYLE.sub("", html)
    # Replace <br> and </p> with newlines before stripping tags
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p\s*>", "\n\n", html)
    text = _RE_TAGS.sub("", html)
    text = urllib.parse.unquote(text)
    text = text.replace("\r", "")
    text = _RE_WS.sub("\n", text)
    text = _RE_MULTI_NL.sub("\n\n", text)
    return text.strip()[:max_chars]


def _safe_url(url: str) -> str:
    # Normalize / basic validation
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebToolError("Only http/https URLs are allowed.")
    return url


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def duckduckgo_search(
    query: str,
    *,
    max_results: int = 8,
    timeout_sec: float = 15.0,
    user_agent: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    DuckDuckGo HTML search (no API key).
    Returns list of {title, url, snippet}.
    """
    if not query or not query.strip():
        raise WebToolError("query is required.")

    q = query.strip()
    max_results = max(1, min(int(max_results or 8), 15))

    headers = {
        "User-Agent": user_agent
        or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Use the HTML endpoint
    # Example: https://duckduckgo.com/html/?q=shopify+jsonld
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_sec, headers=headers) as client:
            r = client.get(url)
            if r.status_code != 200:
                raise WebToolError(f"DuckDuckGo returned HTTP {r.status_code}")
            html = r.text
    except httpx.TimeoutException:
        raise WebToolError("DuckDuckGo search timed out.")
    except httpx.HTTPError as e:
        raise WebToolError(f"DuckDuckGo search failed: {type(e).__name__}: {e}")

    # Parse results with regex (kept minimal).
    # DDG HTML result blocks usually contain:
    #  - a link: <a rel="nofollow" class="result__a" href="...">Title</a>
    #  - snippet: <a class="result__snippet"> ... </a> OR <div class="result__snippet"> ... </div>
    link_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_re = re.compile(
        r'(?:class="result__snippet"[^>]*>)(.*?)(?:</a>|</div>)',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_re.findall(html)
    snippets = snippet_re.findall(html)

    results: List[SearchResult] = []
    for idx, (href, title_html) in enumerate(links):
        if len(results) >= max_results:
            break

        # DDG sometimes uses redirect links like /l/?kh=-1&uddg=<encoded>
        u = href
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                u = qs["uddg"][0]

        try:
            u = _safe_url(u)
        except WebToolError:
            continue

        title = _html_to_text(title_html, max_chars=500)
        snippet_html = snippets[idx] if idx < len(snippets) else ""
        snippet = _html_to_text(snippet_html, max_chars=800)

        # Dedup by url
        if any(r.url == u for r in results):
            continue

        results.append(SearchResult(title=title, url=u, snippet=snippet))

    return [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results]


def web_fetch(
    url: str,
    *,
    timeout_sec: float = 20.0,
    max_chars: int = 200_000,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch a URL and return cleaned text (best-effort).
    """
    url = _safe_url(url)
    headers = {
        "User-Agent": user_agent
        or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_sec, headers=headers) as client:
            r = client.get(url)
            status = r.status_code
            final_url = str(r.url)
            content_type = r.headers.get("content-type", "")
            text = r.text if "text" in content_type or "html" in content_type or content_type == "" else ""
    except httpx.TimeoutException:
        raise WebToolError("Fetch timed out.")
    except httpx.HTTPError as e:
        raise WebToolError(f"Fetch failed: {type(e).__name__}: {e}")

    cleaned = _html_to_text(text or "", max_chars=max_chars)

    return {
        "ok": status >= 200 and status < 300,
        "status_code": status,
        "final_url": final_url,
        "content_type": content_type,
        "text": cleaned,
        "fetched_at": int(time.time()),
    }
