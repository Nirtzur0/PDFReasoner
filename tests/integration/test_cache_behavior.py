from __future__ import annotations

from pathlib import Path

from papercoach.integrations.cache import SQLiteCache
from papercoach.integrations.crossref_client import CrossrefClient


def test_crossref_cache_hit_miss(monkeypatch, tmp_path: Path) -> None:
    cache = SQLiteCache(tmp_path / "cache.sqlite")
    client = CrossrefClient("https://api.crossref.org", cache)

    calls = {"n": 0}

    class Resp:
        status_code = 200

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1/abc",
                            "title": ["Test Title"],
                            "issued": {"date-parts": [[2020]]},
                            "container-title": ["Venue"],
                            "URL": "http://example.com",
                        }
                    ]
                }
            }

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return Resp()

    monkeypatch.setattr("papercoach.integrations.crossref_client.requests.get", fake_get)

    a = client.resolve("Some citation")
    b = client.resolve("Some citation")

    assert a is not None
    assert b is not None
    assert calls["n"] == 1
