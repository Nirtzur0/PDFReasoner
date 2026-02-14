from __future__ import annotations

import json

import requests


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def healthcheck(self) -> None:
        resp = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama tags failed: {resp.status_code}")
        models = [m.get("name") for m in resp.json().get("models", [])]
        if self.model not in models:
            raise RuntimeError(f"Ollama model '{self.model}' not found")

    def structured_output(self, prompt: str, schema: dict, system_prompt: str) -> dict:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama chat failed: {resp.status_code} {resp.text[:300]}")
        content = resp.json().get("message", {}).get("content", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned non-JSON response: {content[:200]}") from exc

    def structured_note(self, prompt: str) -> dict:
        return self.structured_output(
            prompt=prompt,
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "evidence_used": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "uncertainties": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "title",
                    "body",
                    "key_points",
                    "evidence_used",
                    "confidence",
                    "uncertainties",
                ],
            },
            system_prompt=(
                "Return strict JSON only. Explain present text only. Do not invent theorems,"
                " derivations, or uncited facts."
            ),
        )
