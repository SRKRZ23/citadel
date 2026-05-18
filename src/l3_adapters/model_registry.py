"""
CITADEL L3 — Model Adapters + Registry.

Registers all 6 models for head-to-head evaluation:
  1. Gemma 4            — Google DeepMind (primary: Gemma 4 Good)
  2. Llama 4 Scout      — Meta (17B MoE, 10M context)
  3. Claude Haiku 4.5   — Anthropic (via API)
  4. GPT-4o-mini        — OpenAI (via API)
  5. Qwen3-35B-A22B     — Alibaba (via Featherless)
  6. Mistral-7B-v0.3    — Mistral AI (via Featherless)

Each adapter normalizes:
  - Prompt formatting (chat template vs. raw completion)
  - Stop sequences
  - Temperature clamping for eval (0.0 for deterministic)
  - Token counting

The registry is the single source of truth for model IDs used across
L4 (metrics), L6 (dashboard), L7 (audit), and L11 (router).
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelSpec:
    model_id: str              # CITADEL internal ID (e.g., "gemma4")
    display_name: str          # shown on leaderboard
    provider: str              # google / meta / anthropic / openai / featherless
    hf_model_name: str         # HuggingFace / API model name
    context_window: int        # tokens
    is_open_source: bool
    license: str
    backend_type: str          # "local" | "api" | "featherless"
    api_env_key: Optional[str] = None  # env var for API key
    base_url: Optional[str] = None
    chat_template: str = "chatml"      # chatml | gemma | llama3 | plain
    system_prompt: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    @property
    def leaderboard_label(self) -> str:
        return f"{self.display_name} ({self.provider})"


# ── Model definitions ─────────────────────────────────────────────────────────

MODELS: dict[str, ModelSpec] = {

    "gemma4": ModelSpec(
        model_id="gemma4",
        display_name="Gemma 4 27B",
        provider="Google DeepMind",
        hf_model_name="google/gemma-4-27b-it",
        context_window=131072,
        is_open_source=True,
        license="Gemma Terms of Use",
        backend_type="local",          # runs on AMD MI300X
        chat_template="gemma",
        tags=["primary", "gemma4good", "amd_mi300x"],
    ),

    "llama4": ModelSpec(
        model_id="llama4",
        display_name="Llama 4 Scout",
        provider="Meta",
        hf_model_name="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        context_window=10_000_000,
        is_open_source=True,
        license="Llama 4 Community License",
        backend_type="featherless",
        api_env_key="FEATHERLESS_API_KEY",
        base_url="https://api.featherless.ai/v1",
        chat_template="llama3",
        tags=["competitor", "moe"],
    ),

    "claude": ModelSpec(
        model_id="claude",
        display_name="Claude Haiku 4.5",
        provider="Anthropic",
        hf_model_name="claude-haiku-4-5-20251001",
        context_window=200_000,
        is_open_source=False,
        license="Anthropic Commercial",
        backend_type="api",
        api_env_key="ANTHROPIC_API_KEY",
        chat_template="plain",
        tags=["competitor", "proprietary"],
    ),

    "gpt4o_mini": ModelSpec(
        model_id="gpt4o_mini",
        display_name="GPT-4o mini",
        provider="OpenAI",
        hf_model_name="gpt-4o-mini",
        context_window=128_000,
        is_open_source=False,
        license="OpenAI Commercial",
        backend_type="api",
        api_env_key="OPENAI_API_KEY",
        chat_template="chatml",
        tags=["competitor", "proprietary"],
    ),

    "qwen3": ModelSpec(
        model_id="qwen3",
        display_name="Qwen3-35B-A22B",
        provider="Alibaba",
        hf_model_name="Qwen/Qwen3-35B-A22B",
        context_window=131_072,
        is_open_source=True,
        license="Apache 2.0",
        backend_type="featherless",
        api_env_key="FEATHERLESS_API_KEY",
        base_url="https://api.featherless.ai/v1",
        chat_template="chatml",
        tags=["competitor", "open_source", "moe"],
    ),

    "mistral7b": ModelSpec(
        model_id="mistral7b",
        display_name="Mistral-7B-v0.3",
        provider="Mistral AI",
        hf_model_name="mistralai/Mistral-7B-Instruct-v0.3",
        context_window=32_768,
        is_open_source=True,
        license="Apache 2.0",
        backend_type="featherless",
        api_env_key="FEATHERLESS_API_KEY",
        base_url="https://api.featherless.ai/v1",
        chat_template="chatml",
        tags=["competitor", "open_source", "efficient"],
    ),
}


# ── Chat template formatters ──────────────────────────────────────────────────

def format_prompt(prompt: str, spec: ModelSpec) -> str:
    """Apply the model's chat template to a plain text prompt."""
    template = spec.chat_template
    sys = spec.system_prompt or "You are a helpful and accurate assistant."

    if template == "gemma":
        if spec.system_prompt:
            return f"<start_of_turn>user\n{sys}\n\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
        return f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"

    elif template == "llama3":
        return (
            f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            f"{sys}<|eot_id|>\n"
            f"<|start_header_id|>user<|end_header_id|>\n"
            f"{prompt}<|eot_id|>\n"
            f"<|start_header_id|>assistant<|end_header_id|>\n"
        )

    elif template == "chatml":
        return f"<|im_start|>system\n{sys}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

    else:  # plain
        return prompt


def get_stop_sequences(spec: ModelSpec) -> list[str]:
    """Return model-specific stop sequences."""
    if spec.chat_template == "gemma":
        return ["<end_of_turn>"]
    elif spec.chat_template == "llama3":
        return ["<|eot_id|>"]
    elif spec.chat_template == "chatml":
        return ["<|im_end|>"]
    return []


# ── Registry API ─────────────────────────────────────────────────────────────

def get_model(model_id: str) -> ModelSpec:
    if model_id not in MODELS:
        raise ValueError(f"Unknown model {model_id!r}. Available: {list(MODELS)}")
    return MODELS[model_id]


def list_models(tags: Optional[list[str]] = None) -> list[ModelSpec]:
    models = list(MODELS.values())
    if tags:
        models = [m for m in models if any(t in m.tags for t in tags)]
    return models


def healthcheck() -> dict:
    available_keys = []
    for model_id, spec in MODELS.items():
        if spec.api_env_key and os.environ.get(spec.api_env_key):
            available_keys.append(model_id)
    return {
        "layer": "L3_adapters",
        "total_models": len(MODELS),
        "models_with_api_keys": available_keys,
        "models": {mid: m.display_name for mid, m in MODELS.items()},
    }
