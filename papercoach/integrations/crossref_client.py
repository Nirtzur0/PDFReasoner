from __future__ import annotations

from urllib.parse import quote_plus

import requests

from .cache import SQLiteCache


class CrossrefClient:
    def __init__(self, base_url: str, cache: SQLiteCache, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout

    def healthcheck(self) -> None:
        resp = requests.get(f"{self.base_url}/works?rows=1", timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Crossref healthcheck failed: {resp.status_code}")

    def resolve(self, query: str) -> dict | None:
        cache_key = f"resolve:{query.strip().lower()}"
        cached = self.cache.get("crossref", cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/works?rows=1&query.bibliographic={quote_plus(query)}"
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            return None

        items = resp.json().get("message", {}).get("items", [])
        if not items:
            self.cache.set("crossref", cache_key, None, ttl_seconds=86400)
            return None

        item = items[0]
        result = {
            "doi": item.get("DOI"),
            "title": (item.get("title") or [None])[0],
            "year": (item.get("issued", {}).get("date-parts", [[None]])[0][0]),
            "venue": (item.get("container-title") or [None])[0],
            "url": item.get("URL"),
        }
        self.cache.set("crossref", cache_key, result, ttl_seconds=604800)
        return result
