"""
CITADEL L1 — Hardware Abstraction Layer.

Provides a unified inference interface across:
  - AMD MI300X / ROCm (primary target: Gemma 4 Good hackathon)
  - NVIDIA CUDA
  - Apple Silicon MPS
  - CPU (fallback, for testing)
  - Featherless API (remote, for models not locally available)
  - Any OpenAI-compatible API endpoint

The abstraction uses vLLM for local inference and falls back to HTTP
for API-based models. The caller sees a single `generate()` interface
regardless of backend.
"""
from __future__ import annotations

import os
import time
import logging
import platform
from dataclasses import dataclass, field
from typing import Optional, Generator
from enum import Enum

logger = logging.getLogger(__name__)


class Backend(str, Enum):
    ROCM     = "rocm"       # AMD MI300X — primary for CITADEL
    CUDA     = "cuda"       # NVIDIA GPU
    MPS      = "mps"        # Apple Silicon
    CPU      = "cpu"        # CPU fallback
    VLLM_API = "vllm_api"   # vLLM OpenAI-compatible server
    FEATHERLESS = "featherless"  # Featherless.ai cloud API
    OPENAI   = "openai"     # OpenAI API
    ANTHROPIC = "anthropic"  # Anthropic Claude API


@dataclass
class GenerationConfig:
    max_new_tokens: int = 512
    temperature: float = 0.0      # deterministic by default for eval
    top_p: float = 1.0
    seed: int = 42
    stop_sequences: list[str] = field(default_factory=list)
    timeout_seconds: float = 120.0


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    backend: str
    model: str
    energy_joules: Optional[float] = None   # L4 metrics hooks this
    error: Optional[str] = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def tokens_per_second(self) -> float:
        if self.latency_ms <= 0:
            return 0.0
        return self.completion_tokens / (self.latency_ms / 1000.0)


def detect_backend() -> Backend:
    """Auto-detect the best available local backend."""
    # ROCm check
    try:
        import torch
        if torch.cuda.is_available():
            # check if this is ROCm or CUDA
            device_name = torch.cuda.get_device_name(0)
            if "gfx" in device_name.lower() or "amd" in device_name.lower() or "radeon" in device_name.lower():
                logger.info("Detected AMD ROCm backend: %s", device_name)
                return Backend.ROCM
            logger.info("Detected CUDA backend: %s", device_name)
            return Backend.CUDA
        # MPS check
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("Detected Apple MPS backend")
            return Backend.MPS
    except ImportError:
        pass
    logger.info("No GPU detected — using CPU backend")
    return Backend.CPU


class LocalBackend:
    """
    vLLM-based local inference backend (ROCm/CUDA/MPS/CPU).
    Falls back to transformers pipeline if vLLM is not available.
    """

    def __init__(self, model_name: str, backend: Backend, gpu_memory_utilization: float = 0.9):
        self.model_name = model_name
        self.backend = backend
        self.gpu_memory_utilization = gpu_memory_utilization
        self._llm = None

    def load(self) -> None:
        try:
            from vllm import LLM, SamplingParams
            device = "cuda" if self.backend in (Backend.ROCM, Backend.CUDA) else str(self.backend.value)
            self._llm = LLM(
                model=self.model_name,
                device=device,
                gpu_memory_utilization=self.gpu_memory_utilization,
                dtype="bfloat16",
                seed=42,
            )
            self._sampling_params_cls = SamplingParams
            logger.info("vLLM backend loaded: %s on %s", self.model_name, device)
        except ImportError:
            logger.warning("vLLM not available — falling back to transformers pipeline")
            self._load_transformers()

    def _load_transformers(self) -> None:
        from transformers import pipeline
        import torch
        device_map = {"rocm": 0, "cuda": 0, "mps": "mps", "cpu": "cpu"}.get(
            self.backend.value, "cpu"
        )
        self._pipe = pipeline(
            "text-generation",
            model=self.model_name,
            device_map=device_map,
            torch_dtype="bfloat16",
        )

    def generate(self, prompt: str, config: GenerationConfig) -> GenerationResult:
        t0 = time.perf_counter()
        try:
            if self._llm is not None:
                sp = self._sampling_params_cls(
                    max_tokens=config.max_new_tokens,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    seed=config.seed,
                    stop=config.stop_sequences or None,
                )
                outputs = self._llm.generate([prompt], sp)
                text = outputs[0].outputs[0].text
                prompt_tokens = len(outputs[0].prompt_token_ids)
                completion_tokens = len(outputs[0].outputs[0].token_ids)
            else:
                out = self._pipe(
                    prompt,
                    max_new_tokens=config.max_new_tokens,
                    temperature=config.temperature if config.temperature > 0 else None,
                    do_sample=config.temperature > 0,
                    pad_token_id=self._pipe.tokenizer.eos_token_id,
                )
                text = out[0]["generated_text"][len(prompt):]
                prompt_tokens = len(prompt.split())   # approximate
                completion_tokens = len(text.split())
        except Exception as e:
            return GenerationResult(
                text="", prompt_tokens=0, completion_tokens=0,
                latency_ms=0, backend=self.backend.value, model=self.model_name,
                error=str(e)
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        return GenerationResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            backend=self.backend.value,
            model=self.model_name,
        )


class APIBackend:
    """
    OpenAI-compatible API backend (Featherless, OpenAI, Anthropic, vLLM server).
    """

    def __init__(
        self,
        model_name: str,
        backend: Backend,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.backend = backend
        self.base_url = base_url
        self.api_key = api_key or os.environ.get("CITADEL_API_KEY", "")

    def generate(self, prompt: str, config: GenerationConfig) -> GenerationResult:
        import httpx

        if self.backend == Backend.ANTHROPIC:
            return self._anthropic_generate(prompt, config)

        # OpenAI-compatible endpoint
        url = (self.base_url or "https://api.openai.com") + "/v1/chat/completions"
        if self.backend == Backend.FEATHERLESS:
            url = "https://api.featherless.ai/v1/chat/completions"
            key = os.environ.get("FEATHERLESS_API_KEY", self.api_key)
        else:
            key = os.environ.get("OPENAI_API_KEY", self.api_key)

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config.max_new_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "seed": config.seed,
        }

        t0 = time.perf_counter()
        try:
            resp = httpx.post(url, headers=headers, json=payload,
                              timeout=config.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except Exception as e:
            return GenerationResult(
                text="", prompt_tokens=0, completion_tokens=0,
                latency_ms=0, backend=self.backend.value, model=self.model_name,
                error=str(e)
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        return GenerationResult(
            text=text,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            backend=self.backend.value,
            model=self.model_name,
        )

    def _anthropic_generate(self, prompt: str, config: GenerationConfig) -> GenerationResult:
        import httpx
        url = "https://api.anthropic.com/v1/messages"
        key = os.environ.get("ANTHROPIC_API_KEY", self.api_key)
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "max_tokens": config.max_new_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.temperature,
        }
        t0 = time.perf_counter()
        try:
            resp = httpx.post(url, headers=headers, json=payload,
                              timeout=config.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
        except Exception as e:
            return GenerationResult(
                text="", prompt_tokens=0, completion_tokens=0,
                latency_ms=0, backend=self.backend.value, model=self.model_name,
                error=str(e)
            )
        latency_ms = (time.perf_counter() - t0) * 1000
        return GenerationResult(
            text=text,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            latency_ms=latency_ms,
            backend=self.backend.value,
            model=self.model_name,
        )


class HardwareLayer:
    """
    Registry of model backends. Central access point for all inference in CITADEL.
    """

    def __init__(self):
        self._backends: dict[str, LocalBackend | APIBackend] = {}

    def register_local(self, model_id: str, model_name: str,
                       backend: Optional[Backend] = None,
                       gpu_memory_utilization: float = 0.9) -> None:
        b = backend or detect_backend()
        lb = LocalBackend(model_name, b, gpu_memory_utilization)
        lb.load()
        self._backends[model_id] = lb
        logger.info("Registered local model %s → %s", model_id, model_name)

    def register_api(self, model_id: str, model_name: str,
                     backend: Backend, base_url: Optional[str] = None,
                     api_key: Optional[str] = None) -> None:
        self._backends[model_id] = APIBackend(model_name, backend, base_url, api_key)
        logger.info("Registered API model %s → %s (%s)", model_id, model_name, backend.value)

    def generate(self, model_id: str, prompt: str,
                 config: Optional[GenerationConfig] = None) -> GenerationResult:
        if model_id not in self._backends:
            return GenerationResult(
                text="", prompt_tokens=0, completion_tokens=0,
                latency_ms=0, backend="none", model=model_id,
                error=f"Model {model_id!r} not registered"
            )
        return self._backends[model_id].generate(prompt, config or GenerationConfig())

    def list_models(self) -> list[str]:
        return list(self._backends.keys())

    def healthcheck(self) -> dict:
        return {
            "layer": "L1_hardware",
            "detected_backend": detect_backend().value,
            "registered_models": self.list_models(),
            "platform": platform.platform(),
        }
