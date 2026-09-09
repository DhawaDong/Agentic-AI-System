"""
Thin wrapper around the Tavily search API — used by every research /
verification agent that needs live web evidence.
"""
import logging

from tavily import TavilyClient

from core import config

logger = logging.getLogger("agent.search")

_client = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        if not config.TAVILY_API_KEY:
            raise RuntimeError("TAVILY_API_KEY is not set")
        _client = TavilyClient(api_key=config.TAVILY_API_KEY)
    return _client


def web_search(query: str, max_results: int = None, search_depth: str = "advanced",
               days: int = None, include_answer: bool = False) -> list[dict]:
    """
    Returns a list of {title, url, content, score, published_date} dicts.
    `days` restricts results to the last N days (good for "what's new today").
    """
    client = _get_client()
    max_results = max_results or config.TAVILY_MAX_RESULTS
    try:
        kwargs = dict(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=include_answer,
        )
        if days:
            kwargs["days"] = days
        result = client.search(**kwargs)
        return result.get("results", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("Tavily search failed for %r: %s", query, e)
        return []


def multi_search(queries: list[str], max_results_each: int = None) -> list[dict]:
    """Runs several queries and returns a flat, de-duplicated (by URL) result list."""
    seen_urls = set()
    combined = []
    for q in queries:
        for r in web_search(q, max_results=max_results_each):
            url = r.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(r)
    return combined
