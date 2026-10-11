"""OpenAI-compatible chat client (reads OPENAI_API_KEY and OPENAI_BASE_URL)."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Completion:
    text: str
    usage: dict


class LLMClient:
    def __init__(self, model: str, temperature: float = 0.7, max_tokens: int = 16000,
                 io_log: str | Path | None = None, retries: int = 5) -> None:
        import httpx
        from openai import OpenAI

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries
        self.io_log = Path(io_log) if io_log else None
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"),
                             base_url=os.environ.get("OPENAI_BASE_URL") or None,
                             timeout=httpx.Timeout(900.0, connect=30.0), max_retries=3)

    def complete(self, system: str, user: str, tag: str = "") -> Completion:
        from openai import APIError

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        t0 = time.time()
        for attempt in range(self.retries):
            try:
                resp = self._create(messages)
                break
            except APIError as exc:
                if attempt == self.retries - 1:
                    raise
                wait = min(60.0, 5.0 * 2 ** attempt)
                log.warning("LLM call failed (%s); retrying in %.0fs", exc, wait)
                time.sleep(wait)
        text = resp.choices[0].message.content or ""
        u = getattr(resp, "usage", None)
        usage = {}
        if u is not None:
            usage = {"prompt_tokens": getattr(u, "prompt_tokens", None),
                     "completion_tokens": getattr(u, "completion_tokens", None),
                     "total_tokens": getattr(u, "total_tokens", None)}
            details = getattr(u, "completion_tokens_details", None)
            if details is not None:
                usage["reasoning_tokens"] = getattr(details, "reasoning_tokens", None)
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", None)
            if cached is not None:
                usage["cached_tokens"] = cached
        if self.io_log:
            self.io_log.parent.mkdir(parents=True, exist_ok=True)
            with self.io_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "tag": tag, "model": self.model,
                                    "latency_s": round(time.time() - t0, 2),
                                    "finish_reason": resp.choices[0].finish_reason,
                                    "input": messages, "output": text, "usage": usage},
                                   ensure_ascii=False) + "\n")
        return Completion(text=text, usage=usage)

    def _create(self, messages):
        from openai import BadRequestError

        kwargs = {"model": self.model, "messages": messages,
                  "max_completion_tokens": self.max_tokens, "temperature": self.temperature}
        try:
            return self.client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            msg = str(exc).lower()
            if "temperature" in msg:
                kwargs.pop("temperature")
            elif "max_completion_tokens" in msg:
                kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
            else:
                raise
            return self.client.chat.completions.create(**kwargs)
