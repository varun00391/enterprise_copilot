"""
Web Crawl Agent — validates URLs, sitemap expansion, bulk fetch with crawl4ai/Playwright,
robots.txt checks, rate limits, deduplication, and handoff to the Ingestion Agent.
"""
import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urljoin, urlunparse

import structlog

from app.core.config import settings

log = structlog.get_logger()

_USER_AGENT = "OrgMindBot/1.0 (enterprise knowledge crawler)"


# ─── URL validation / normalization ───────────────────────────────────────────

def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def normalize_http_url(url: str) -> str:
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        u = f"https://{u}"
    parsed = urlparse(u)
    if not parsed.netloc:
        return u
    # Strip fragment; keep query (some sites use it for routing)
    return urlunparse(
        (parsed.scheme, parsed.netloc.lower(), parsed.path or "", parsed.params, parsed.query, "")
    )


def looks_like_sitemap_url(url: str) -> bool:
    """Heuristic for crawl_mode=auto."""
    u = (url or "").lower().strip()
    if "sitemap" in u and (u.endswith(".xml") or u.endswith(".xml.gz") or "/sitemap" in u):
        return True
    if u.endswith("sitemap.xml"):
        return True
    return False


def _check_robots_txt(url: str) -> bool:
    """Basic robots.txt check. Returns True if crawling is allowed."""
    try:
        from urllib.robotparser import RobotFileParser
        import httpx

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        with httpx.Client(timeout=5) as client:
            resp = client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                return rp.can_fetch("*", url)
        return True
    except Exception:
        return True


# ─── Sitemap ──────────────────────────────────────────────────────────────────

def _parse_sitemap_body(content: str) -> Tuple[List[str], List[str]]:
    """
    Parse sitemap XML. Returns (nested_sitemap_locs, page_locs).
    """
    root = ET.fromstring(content.encode("utf-8"))
    tag_local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    locs: List[str] = []
    for el in root.iter():
        el_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if el_local == "loc" and el.text and el.text.strip():
            locs.append(el.text.strip())
    if tag_local == "sitemapindex":
        return locs, []
    return [], locs


def expand_sitemap_urls(
    entry_url: str,
    max_urls: int,
    max_sitemap_fetches: Optional[int] = None,
) -> List[str]:
    """
    Fetch a sitemap (including nested sitemap indexes) and return up to max_urls page URLs.
    """
    import httpx

    max_fetches = max_sitemap_fetches if max_sitemap_fetches is not None else settings.CRAWL_SITEMAP_MAX_FETCHES
    pages: List[str] = []
    seen_pages: Set[str] = set()
    sitemap_queue: List[str] = [normalize_http_url(entry_url)]
    seen_sitemaps: Set[str] = set()
    fetches = 0
    headers = {"User-Agent": _USER_AGENT}

    while sitemap_queue and len(pages) < max_urls and fetches < max_fetches:
        sm_url = sitemap_queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        fetches += 1
        try:
            with httpx.Client(timeout=45, headers=headers, follow_redirects=True) as client:
                resp = client.get(sm_url)
                resp.raise_for_status()
                text = resp.text
        except Exception as e:
            log.warning("web_crawl.sitemap_fetch_failed", url=sm_url, error=str(e))
            continue
        try:
            child_maps, page_locs = _parse_sitemap_body(text)
        except ET.ParseError as e:
            log.warning("web_crawl.sitemap_parse_failed", url=sm_url, error=str(e))
            continue
        for cm in child_maps:
            nu = normalize_http_url(cm)
            if nu not in seen_sitemaps and _is_valid_url(nu):
                sitemap_queue.append(nu)
        for u in page_locs:
            nu = normalize_http_url(u)
            if nu not in seen_pages and _is_valid_url(nu):
                seen_pages.add(nu)
                pages.append(nu)
                if len(pages) >= max_urls:
                    break
    log.info("web_crawl.sitemap_expand", entry=entry_url, page_count=len(pages))
    return pages


# ─── Content extraction ───────────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    """Strip HTML, scripts, styles and extract main content."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 30]
    return "\n".join(lines)


def _same_site(a: str, b: str) -> bool:
    try:
        return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()
    except Exception:
        return False


async def _crawl_with_crawl4ai(
    start_urls: List[str],
    max_depth: int = 0,
    max_pages: int = 5,
    follow_links: bool = True,
    request_delay_sec: float = 0.0,
) -> List[Dict[str, str]]:
    """Crawl using crawl4ai. If follow_links is False, only listed URLs are fetched (bulk/sitemap)."""
    from crawl4ai import AsyncWebCrawler

    results: List[Dict[str, str]] = []
    visited: Set[str] = set()
    content_hashes: Set[str] = set()
    delay = request_delay_sec if request_delay_sec is not None else settings.CRAWL_REQUEST_DELAY_SEC

    async with AsyncWebCrawler(headless=settings.PLAYWRIGHT_HEADLESS) as crawler:

        async def fetch_one(page_url: str) -> Optional[Dict[str, str]]:
            if not _check_robots_txt(page_url):
                log.info("web_crawl.robots_skip", url=page_url)
                return None
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                result = await crawler.arun(url=page_url)
            except Exception as e:
                log.warning("web_crawl.arun_failed", url=page_url, error=str(e))
                return None
            if not result.success:
                return None
            content = (result.markdown or "").strip() or _clean_html(result.html or "")
            if not content.strip():
                return None
            ch = hashlib.sha256(content.encode()).hexdigest()
            if ch in content_hashes:
                return None
            content_hashes.add(ch)
            title = (result.metadata or {}).get("title") or page_url
            return {"url": page_url, "content": content, "title": str(title)}

        if not follow_links:
            deduped: List[str] = []
            seen_u: Set[str] = set()
            for u in start_urls:
                nu = normalize_http_url(u)
                if nu not in seen_u:
                    seen_u.add(nu)
                    deduped.append(nu)
            for page_url in deduped:
                if len(results) >= max_pages:
                    break
                if page_url in visited:
                    continue
                visited.add(page_url)
                row = await fetch_one(page_url)
                if row:
                    results.append(row)
            return results

        # BFS link following (same host only); single arun per page
        queue: deque[Tuple[str, int]] = deque()
        for u in start_urls:
            nu = normalize_http_url(u)
            if nu not in visited:
                visited.add(nu)
                queue.append((nu, 0))

        while queue and len(results) < max_pages:
            page_url, depth = queue.popleft()
            if not _check_robots_txt(page_url):
                continue
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                result = await crawler.arun(url=page_url)
            except Exception as e:
                log.warning("web_crawl.arun_failed", url=page_url, error=str(e))
                continue
            if not result.success:
                continue
            content = (result.markdown or "").strip() or _clean_html(result.html or "")
            if content.strip():
                ch = hashlib.sha256(content.encode()).hexdigest()
                if ch not in content_hashes:
                    content_hashes.add(ch)
                    title = (result.metadata or {}).get("title") or page_url
                    results.append({"url": page_url, "content": content, "title": str(title)})
            if depth >= max_depth or len(results) >= max_pages:
                continue
            for link in result.links or []:
                href = link.get("href", "") if isinstance(link, dict) else getattr(link, "href", "")
                if not href:
                    continue
                link_url = urljoin(page_url, href)
                if not _is_valid_url(link_url):
                    continue
                link_url = normalize_http_url(link_url.split("#")[0])
                if link_url in visited:
                    continue
                if not _same_site(page_url, link_url):
                    continue
                if not _check_robots_txt(link_url):
                    continue
                visited.add(link_url)
                queue.append((link_url, depth + 1))

        return results


def _crawl_with_httpx_bulk(urls: List[str], max_pages: int) -> List[Dict[str, str]]:
    """Fallback: fetch URLs with httpx + BeautifulSoup (no JS)."""
    import httpx
    from bs4 import BeautifulSoup

    results: List[Dict[str, str]] = []
    headers = {"User-Agent": _USER_AGENT}
    content_hashes: Set[str] = set()
    try:
        with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
            for url in urls:
                if len(results) >= max_pages:
                    break
                u = normalize_http_url(url)
                if not _check_robots_txt(u):
                    continue
                try:
                    resp = client.get(u)
                    resp.raise_for_status()
                except Exception as e:
                    log.error("web_crawl.httpx_failed", url=u, error=str(e))
                    continue
                content = _clean_html(resp.text)
                if not content.strip():
                    continue
                ch = hashlib.sha256(content.encode()).hexdigest()
                if ch in content_hashes:
                    continue
                content_hashes.add(ch)
                soup = BeautifulSoup(resp.text, "lxml")
                title_el = soup.title
                title = title_el.get_text(strip=True) if title_el else u
                results.append({"url": u, "content": content, "title": str(title)})
    except Exception as e:
        log.error("web_crawl.httpx_bulk_failed", error=str(e))
    return results


def crawl_pages(
    seed_urls: List[str],
    *,
    max_depth: Optional[int] = None,
    max_pages: Optional[int] = None,
    follow_links: bool = True,
    request_delay_sec: Optional[float] = None,
) -> List[Dict[str, str]]:
    """
    Synchronous crawl: try crawl4ai first, fall back to httpx bulk fetch.
    `follow_links=False` is used for expanded sitemap URL lists.
    """
    max_depth = max_depth if max_depth is not None else settings.CRAWL_MAX_DEPTH
    max_pages = max_pages if max_pages is not None else settings.CRAWL_MAX_PAGES_PER_URL
    delay = (
        request_delay_sec
        if request_delay_sec is not None
        else settings.CRAWL_REQUEST_DELAY_SEC
    )

    seeds = [normalize_http_url(u) for u in seed_urls if str(u).strip()]
    if not seeds:
        return []

    for u in seeds:
        if not _is_valid_url(u):
            raise ValueError(f"Invalid URL: {u}")

    try:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            out = loop.run_until_complete(
                _crawl_with_crawl4ai(
                    seeds,
                    max_depth=max_depth,
                    max_pages=max_pages,
                    follow_links=follow_links,
                    request_delay_sec=delay,
                )
            )
        finally:
            loop.close()
        if out:
            return out
    except Exception as e:
        log.warning("web_crawl.crawl4ai_failed", error=str(e))

    if follow_links and len(seeds) == 1:
        return _crawl_with_httpx_bulk(seeds, max_pages=1)
    return _crawl_with_httpx_bulk(seeds if not follow_links else seeds[:1], max_pages=max_pages)


def crawl_url(url: str, max_depth: int = None, max_pages: int = None) -> List[Dict[str, str]]:
    """Backward-compatible single-seed crawl with link following."""
    return crawl_pages(
        [url],
        max_depth=max_depth,
        max_pages=max_pages,
        follow_links=True,
    )


# ─── Ingestion handoff ────────────────────────────────────────────────────────

def ingest_crawled_pages(
    pages: List[Dict[str, str]],
    dept_id: str,
    doc_id_prefix: str,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    For each crawled page, check deduplication and pass to ingestion pipeline.
    Returns list of {url, doc_id, chunk_count} for successfully indexed pages.
    """
    from app.agents.ingestion import ingest_document
    import uuid

    results: List[Dict[str, Any]] = []
    if metadata is None:
        metadata = {}

    for page in pages:
        url = page["url"]
        content = page["content"]
        if not content.strip():
            continue

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        doc_id = str(uuid.uuid4())

        try:
            title = page.get("title") or url
            safe_name = re.sub(r"[^\w\-./]+", "_", str(title))[:120] + ".txt"
            chunk_count = ingest_document(
                file_bytes=content.encode("utf-8"),
                file_type="txt",
                filename=safe_name,
                doc_id=doc_id,
                dept_id=dept_id,
                metadata={
                    **metadata,
                    "source_url": url,
                    "title": title,
                },
            )
            results.append(
                {"url": url, "doc_id": doc_id, "chunk_count": chunk_count, "sha256": content_hash}
            )
            log.info("web_crawl.indexed", url=url, chunks=chunk_count)
        except Exception as e:
            log.error("web_crawl.ingest_failed", url=url, error=str(e))

    return results
