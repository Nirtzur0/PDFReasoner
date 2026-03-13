from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from urllib import error, request

from papercoach.config import ServiceConfig

_REQUEST_TIMEOUT_SECONDS = 300


@dataclass(slots=True)
class TraceWriter:
    path: Path

    def write(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")


class ChatMockClient:
    def __init__(self, config: ServiceConfig, trace_writer: TraceWriter) -> None:
        self._config = config
        self._trace_writer = trace_writer
        self._validate_config()

    @property
    def model(self) -> str:
        return self._config.model

    def healthcheck(self) -> None:
        response = self._request_json("GET", "/models", None)
        raw_models = response.get("data", [])
        available_models = {model.get("id") for model in raw_models if isinstance(model, dict)}
        if self._config.model not in available_models:
            raise RuntimeError(f"Required model '{self._config.model}' is not available via ChatMock")

    def create_json_response(
        self,
        prompt_name: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 1200,
    ) -> dict[str, Any]:
        payload = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "max_tokens": max_output_tokens,
        }
        self._trace_writer.write({"type": "request", "prompt_name": prompt_name, "payload": payload})
        response = self._request_json("POST", "/chat/completions", payload)
        output_text = self._extract_output_text(response)
        self._trace_writer.write({"type": "response", "prompt_name": prompt_name, "body": output_text})
        try:
            return json.loads(output_text)
        except json.JSONDecodeError as exc:
            repaired = self._repair_invalid_json_escapes(output_text)
            if repaired != output_text:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(f"Model returned non-JSON output for {prompt_name}") from exc

    def _validate_config(self) -> None:
        if not self._config.base_url:
            raise ValueError("PAPERCOACH_BASE_URL or OPENAI_BASE_URL must resolve to an OpenAI-compatible endpoint")
        if not self._config.api_key:
            raise ValueError("PAPERCOACH_API_KEY or OPENAI_API_KEY must resolve to a non-empty value")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        if self._config.base_url is None:
            raise RuntimeError("Missing base URL")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        url = self._config.base_url.rstrip("/") + path
        req = request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise RuntimeError(f"ChatMock request failed for {path}: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach ChatMock at {url}") from exc

    def _extract_output_text(self, response: dict[str, Any]) -> str:
        if isinstance(response.get("output_text"), str):
            return self._clean_output_text(response["output_text"])
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return self._clean_output_text(content["text"])
        for choice in response.get("choices", []):
            message = choice.get("message", {})
            if isinstance(message.get("content"), str):
                return self._clean_output_text(message["content"])
        raise RuntimeError("Response did not contain assistant text")

    def _clean_output_text(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _repair_invalid_json_escapes(self, text: str) -> str:
        return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
