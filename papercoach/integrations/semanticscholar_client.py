from __future__ import annotations

from urllib.parse import quote_plus

import requests

from .cache import SQLiteCache


class SemanticScholarClient:
    def __init__(self, base_url: str, cache: SQLiteCache, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout

    def healthcheck(self) -> None:
        resp = requests.get(
            f"{self.base_url}/paper/search?query=deep%20learning&limit=1&fields=title",
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Semantic Scholar healthcheck failed: {resp.status_code}")

    def resolve(self, query: str) -> dict | None:
        cache_key = f"resolve:{query.strip().lower()}"
        cached = self.cache.get("semanticscholar", cache_key)
        if cached is not None:
            return cached

        url = (
            f"{self.base_url}/paper/search?query={quote_plus(query)}&limit=1"
            "&fields=paperId,title,year,venue,url,abstract,citationCount"
        )
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        if not data:
            self.cache.set("semanticscholar", cache_key, None, ttl_seconds=86400)
            return None
        item = data[0]
        abstract = item.get("abstract")
        result = {
            "s2_paper_id": item.get("paperId"),
            "title": item.get("title"),
            "year": item.get("year"),
            "venue": item.get("venue"),
            "url": item.get("url"),
            "abstract_snippet": (abstract[:300] + "...") if abstract and len(abstract) > 300 else abstract,
            "citation_count": item.get("citationCount"),
        }
        self.cache.set("semanticscholar", cache_key, result, ttl_seconds=604800)
        return result
