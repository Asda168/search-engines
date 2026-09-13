"""Core scraping + fuzzy-search engine.

Fetches a page, splits it into logical content blocks (articles, list
items, cards, or heading+paragraph pairs), and ranks those blocks against
a search query using fuzzy string matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from rapidfuzz import fuzz

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10.0

# Elements that never carry meaningful page content — stripped before parsing.
BOILERPLATE_TAGS = ("script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside")

# Candidate block containers, in priority order. The first tier that yields
# usable blocks wins, so nested tiers (e.g. <div> inside <li>) aren't double-counted.
BLOCK_SELECTORS = ("article", "li", "section", "div")

MIN_BLOCK_TEXT_LEN = 15


class ScrapeError(Exception):
    """Raised when the target URL cannot be fetched or parsed."""


@dataclass
class Block:
    title: str
    description: str
    url: Optional[str]
    tags: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    title: str
    url: Optional[str]
    snippet: str
    score: float

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "score": round(self.score, 1),
        }


def fetch_html(url: str, timeout: float = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_USER_AGENT) -> str:
    """Fetch a page's HTML, raising ScrapeError with a descriptive message on failure."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ScrapeError(f"Unsupported URL scheme: {parsed.scheme!r} (only http/https allowed)")

    headers = {"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"}
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ScrapeError(f"Timed out fetching {url!r} after {timeout}s") from exc
    except httpx.HTTPStatusError as exc:
        raise ScrapeError(f"{url!r} returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise ScrapeError(f"Network error fetching {url!r}: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if content_type and "html" not in content_type:
        raise ScrapeError(f"{url!r} did not return HTML content (got {content_type!r})")

    return response.text


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(BOILERPLATE_TAGS):
        tag.decompose()


def _extract_title(node: Tag) -> str:
    heading = node.find(["h1", "h2", "h3", "h4", "strong"])
    if heading:
        text = _clean_text(heading.get_text())
        if text:
            return text
    link = node.find("a")
    if link:
        text = _clean_text(link.get_text())
        if text:
            return text
    return _clean_text(node.get_text())[:120]


def _extract_description(node: Tag, title: str) -> str:
    parts = [
        text
        for p in node.find_all("p")
        if (text := _clean_text(p.get_text())) and text != title
    ]
    if parts:
        return " ".join(parts)
    full_text = _clean_text(node.get_text())
    if full_text.startswith(title):
        full_text = full_text[len(title):].strip()
    return full_text


def _clean_href(href: str) -> Optional[str]:
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None
    return href


def _extract_url(node: Tag, base_url: str, prefer: Optional[Tag] = None) -> Optional[str]:
    for source in (prefer, node):
        if source is None:
            continue
        link = source if source.name == "a" and source.has_attr("href") else source.find("a", href=True)
        if link:
            href = _clean_href(link["href"])
            if href:
                return urljoin(base_url, href)
    return None


def _extract_tags(node: Tag) -> list[str]:
    tags = []
    for el in node.find_all(class_=re.compile(r"tag|badge|category|label", re.I)):
        text = _clean_text(el.get_text())
        if text and len(text) < 40:
            tags.append(text)
    return tags


def _dedupe_blocks(blocks: list[Block]) -> list[Block]:
    seen: set[tuple[str, Optional[str]]] = set()
    unique = []
    for block in blocks:
        key = (block.title, block.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(block)
    return unique


HEADING_TAGS = ("h1", "h2", "h3", "h4")
MAX_CONTAINER_DEPTH = 6


def _find_card_container(heading: Tag) -> Tag:
    """Walk up from a heading to the smallest ancestor that still holds only
    this one heading — i.e. the single "card" for this item, not the list
    wrapping every card."""
    node = heading
    for _ in range(MAX_CONTAINER_DEPTH):
        parent = node.parent
        if parent is None or not isinstance(parent, Tag) or parent.name in ("body", "html"):
            break
        if len(parent.find_all(HEADING_TAGS)) > 1:
            break  # ascending further would merge sibling cards into one block
        node = parent
    return node


def _extract_blocks_by_heading(root: Tag, base_url: str) -> list[Block]:
    blocks = []
    for heading in root.find_all(HEADING_TAGS):
        title = _clean_text(heading.get_text())
        if not title:
            continue
        container = _find_card_container(heading)
        blocks.append(
            Block(
                title=title,
                description=_extract_description(container, title),
                url=_extract_url(container, base_url, prefer=heading),
                tags=_extract_tags(container),
            )
        )
    return blocks


def _extract_blocks_by_selector(root: Tag, base_url: str) -> list[Block]:
    """Fallback for pages with no headings at all (e.g. plain link lists)."""
    blocks: list[Block] = []
    for selector in BLOCK_SELECTORS:
        for node in root.find_all(selector):
            text = _clean_text(node.get_text())
            if len(text) < MIN_BLOCK_TEXT_LEN:
                continue
            title = _extract_title(node)
            if not title:
                continue
            blocks.append(
                Block(
                    title=title,
                    description=_extract_description(node, title),
                    url=_extract_url(node, base_url),
                    tags=_extract_tags(node),
                )
            )
        if blocks:
            break  # a higher-priority selector already produced usable blocks
    return blocks


def extract_blocks(html: str, base_url: str) -> list[Block]:
    """Parse HTML into logical content blocks, skipping nav/footer boilerplate."""
    soup = BeautifulSoup(html, "html.parser")
    _strip_boilerplate(soup)

    root = soup.find("main") or soup.body or soup

    blocks = _extract_blocks_by_heading(root, base_url)
    if not blocks:
        blocks = _extract_blocks_by_selector(root, base_url)

    return _dedupe_blocks(blocks)


def _snippet(block: Block, query: str, max_len: int = 220) -> str:
    text = block.description or block.title
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return text[:max_len] + ("..." if len(text) > max_len else "")
    start = max(0, idx - 60)
    end = min(len(text), idx + len(query) + 120)
    snippet = text[start:end]
    return ("..." if start > 0 else "") + snippet + ("..." if end < len(text) else "")


def score_block(block: Block, query: str) -> float:
    """Weighted fuzzy score: title matches count most, then description, then tags."""
    title_score = fuzz.WRatio(query, block.title) if block.title else 0
    desc_score = fuzz.WRatio(query, block.description) if block.description else 0
    tag_score = max((fuzz.WRatio(query, tag) for tag in block.tags), default=0)
    return max(title_score, desc_score * 0.9, tag_score * 0.8)


def search_blocks(blocks: Iterable[Block], query: str, threshold: int = 60) -> list[SearchResult]:
    results = []
    for block in blocks:
        score = score_block(block, query)
        if score >= threshold:
            results.append(
                SearchResult(title=block.title, url=block.url, snippet=_snippet(block, query), score=score)
            )
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def scrape_and_search(
    url: str,
    query: str,
    threshold: int = 60,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Fetch `url`, extract content blocks, and return ranked matches for `query`."""
    html = fetch_html(url, timeout=timeout)
    blocks = extract_blocks(html, base_url=url)
    results = search_blocks(blocks, query, threshold=threshold)
    return {
        "target_url": url,
        "query": query,
        "total_matches": len(results),
        "results": [r.to_dict() for r in results],
    }
