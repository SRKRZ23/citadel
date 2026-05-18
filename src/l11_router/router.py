"""
CITADEL L11 — Intelligent Model Router.

Auto-routes inference requests to the optimal model based on:
  - Task type (code / medical / multilingual / general)
  - Cost budget (max USD per request)
  - Latency SLA (max ms)
  - Compliance requirements (HIPAA / PCI-DSS)
  - Quality threshold (min accuracy from CITADEL leaderboard)

Routing uses CITADEL leaderboard data to pick the best model
for each task dimension. This closes the loop: evaluation → routing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RoutingRequest:
    task_type: str             # "code" | "medical" | "multilingual" | "general" | "math"
    max_cost_per_1k: float = 0.01    # USD per 1K tokens
    max_latency_ms: float = 1000.0
    min_accuracy: float = 0.70
    compliance: list[str] = None     # ["hipaa", "pci_dss"]
    language: str = "en"

    def __post_init__(self):
        if self.compliance is None:
            self.compliance = []


@dataclass
class RoutingDecision:
    model_id: str
    reason: str
    estimated_cost_per_1k: float
    expected_accuracy: float
    fallback_model_id: Optional[str] = None


# Static routing table (populated from CITADEL leaderboard results)
# In production: loaded dynamically from L6 dashboard results
ROUTING_TABLE: dict[str, dict] = {
    "general": {
        "primary": "gemma4",
        "fallback": "mistral7b",
        "reason": "Best accuracy/cost ratio for general tasks",
    },
    "code": {
        "primary": "gpt4o_mini",
        "fallback": "gemma4",
        "reason": "HumanEval-optimised; GPT-4o-mini leads code benchmarks",
    },
    "medical": {
        "primary": "claude",
        "fallback": "gemma4",
        "reason": "HIPAA-compliant API; best hallucination_rate for clinical queries",
    },
    "multilingual": {
        "primary": "gemma4",
        "fallback": "qwen3",
        "reason": "Gemma 4 leads multilingual MMLU; Qwen3 fallback for CJK",
    },
    "math": {
        "primary": "gemma4",
        "fallback": "llama4",
        "reason": "Gemma 4 MathOlympics training; Llama 4 as fallback",
    },
}

# Model cost catalog (USD per 1K tokens, approximate)
MODEL_COSTS: dict[str, float] = {
    "gemma4": 0.002,       # AMD MI300X self-hosted
    "llama4": 0.0,         # Featherless free tier
    "claude": 0.00025,     # Haiku 4.5
    "gpt4o_mini": 0.00015,
    "qwen3": 0.0,          # Featherless free tier
    "mistral7b": 0.0,      # Featherless free tier
}

# Model accuracy estimates (from CITADEL mock leaderboard)
MODEL_ACCURACY: dict[str, float] = {
    "gemma4": 0.810,
    "llama4": 0.785,
    "claude": 0.852,
    "gpt4o_mini": 0.831,
    "qwen3": 0.763,
    "mistral7b": 0.694,
}

# HIPAA/PCI compliant models (have signed DPAs)
COMPLIANT_MODELS: dict[str, list[str]] = {
    "hipaa": ["claude", "gpt4o_mini"],     # Anthropic + OpenAI have BAAs
    "pci_dss": ["claude", "gpt4o_mini"],
}


def route(req: RoutingRequest) -> RoutingDecision:
    """Select the optimal model for the given routing request."""
    table_entry = ROUTING_TABLE.get(req.task_type, ROUTING_TABLE["general"])
    primary = table_entry["primary"]
    fallback = table_entry.get("fallback")

    # Compliance filter
    for framework in req.compliance:
        allowed = COMPLIANT_MODELS.get(framework, [])
        if primary not in allowed:
            logger.info("Routing: %s not compliant with %s, switching to %s",
                        primary, framework, allowed[0] if allowed else fallback)
            primary = allowed[0] if allowed else fallback

    # Cost filter
    cost = MODEL_COSTS.get(primary, 0.0)
    if cost > req.max_cost_per_1k:
        # Find cheapest model that meets accuracy
        candidates = [
            (mid, acc) for mid, acc in MODEL_ACCURACY.items()
            if MODEL_COSTS.get(mid, 0) <= req.max_cost_per_1k
            and acc >= req.min_accuracy
        ]
        if candidates:
            primary = max(candidates, key=lambda x: x[1])[0]
            cost = MODEL_COSTS.get(primary, 0)

    # Accuracy filter
    acc = MODEL_ACCURACY.get(primary, 0)
    if acc < req.min_accuracy and fallback:
        fallback_acc = MODEL_ACCURACY.get(fallback, 0)
        if fallback_acc >= req.min_accuracy:
            primary, fallback = fallback, primary

    return RoutingDecision(
        model_id=primary,
        reason=f"{table_entry['reason']} | compliance={req.compliance} | cost≤{req.max_cost_per_1k}",
        estimated_cost_per_1k=MODEL_COSTS.get(primary, 0),
        expected_accuracy=MODEL_ACCURACY.get(primary, 0),
        fallback_model_id=fallback,
    )


def healthcheck() -> dict:
    return {
        "layer": "L11_router",
        "task_types": list(ROUTING_TABLE),
        "n_models": len(MODEL_COSTS),
        "compliance_frameworks": list(COMPLIANT_MODELS),
    }
