"""
CITADEL L3 — Ollama adapter for local Gemma 4 inference.

Enables CITADEL to evaluate Gemma 4 (and other models) running locally via
Ollama, with zero cloud dependency. This is the privacy-preserving evaluation
path: a hospital, legal firm, or government lab can run CITADEL evaluations
on Gemma 4 27B entirely on-premises and still produce signed, hash-committed
audit chains compatible with the L7 audit chain layer.

Submitted to the Ollama Special Technology Track of the Gemma 4 Good Hackathon.

Author: Sardor Razikov (sole author).
Gemma is a trademark of Google LLC.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib import request as urlrequest
from urllib.error import URLError

logger = logging.getLogger(__name__)


@dataclass
class OllamaResponse:
    """Normalized output from an Ollama generate call."""
    model: str
    prompt: str
    response: str
    eval_count: int
    eval_duration_ns: int
    total_duration_ns: int
    done: bool

    @property
    def tokens_per_second(self) -> float:
        if self.eval_duration_ns <= 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)

    @property
    def total_duration_ms(self) -> float:
        return self.total_duration_ns / 1e6


class OllamaAdapter:
    """
    Talks to a local Ollama daemon at the configured base URL.

    Default base URL is http://localhost:11434 (Ollama's standard port).
    Override with `OLLAMA_BASE_URL` env var or constructor arg.

    Usage::

        adapter = OllamaAdapter(model="gemma-4:27b")
        result = adapter.generate("What is the boiling point of water?")
        print(result.response, result.tokens_per_second)

    The adapter is intentionally dependency-free: it uses urllib instead of
    `requests` so CITADEL can be evaluated on air-gapped Ollama setups
    without pip installs beyond the standard library.
    """

    def __init__(
        self,
        model: str = "gemma-4:27b",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        seed: int = 42,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.seed = seed

    def is_alive(self) -> bool:
        """Probe the Ollama daemon. Returns False if unreachable."""
        try:
            req = urlrequest.Request(f"{self.base_url}/api/tags")
            with urlrequest.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except (URLError, TimeoutError, ConnectionError):
            return False

    def list_local_models(self) -> list[str]:
        """Return names of all locally pulled Ollama models."""
        req = urlrequest.Request(f"{self.base_url}/api/tags")
        with urlrequest.urlopen(req, timeout=10.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in payload.get("models", [])]

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 512,
    ) -> OllamaResponse:
        """
        Single-prompt generation against the local Ollama daemon.

        Deterministic by default (temperature=0.0, fixed seed) for
        reproducible CITADEL benchmark runs.
        """
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_predict": max_tokens,
            },
        }
        if system is not None:
            body["system"] = system

        data = json.dumps(body).encode("utf-8")
        req = urlrequest.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.perf_counter()
        with urlrequest.urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        wall_ns = int((time.perf_counter() - start) * 1e9)

        return OllamaResponse(
            model=raw.get("model", self.model),
            prompt=prompt,
            response=raw.get("response", ""),
            eval_count=int(raw.get("eval_count", 0)),
            eval_duration_ns=int(raw.get("eval_duration", 0)),
            total_duration_ns=int(raw.get("total_duration", wall_ns)),
            done=bool(raw.get("done", False)),
        )

    def batch_generate(
        self,
        prompts: list[str],
        system: Optional[str] = None,
        max_tokens: int = 512,
    ) -> list[OllamaResponse]:
        """Sequential batch — Ollama serves one inference at a time per
        process by default. For CITADEL benchmark runs we want strict
        ordering for hash-committed audit chain entries anyway."""
        return [
            self.generate(p, system=system, max_tokens=max_tokens) for p in prompts
        ]


def smoke_test(model: str = "gemma-4:27b") -> bool:
    """
    Quick connectivity + inference test. Returns True if Ollama is alive
    and the named model is available locally.

    Useful inside CITADEL's L1 hardware/backend detection flow:

        if smoke_test("gemma-4:27b"):
            backend = "ollama-local"
    """
    adapter = OllamaAdapter(model=model)
    if not adapter.is_alive():
        logger.info("Ollama daemon not reachable at %s", adapter.base_url)
        return False
    locals_ = adapter.list_local_models()
    if not any(model in m for m in locals_):
        logger.info(
            "Model %s not found locally. Pull it with: ollama pull %s",
            model,
            model,
        )
        return False
    return True
