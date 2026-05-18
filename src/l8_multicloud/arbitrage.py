"""
CITADEL L8 — Multi-cloud Arbitrage.

Auto-places inference workloads on the cheapest infrastructure that meets
latency and compliance constraints.

Supported backends:
  - AMD MI300X (Vultr / DigitalOcean)  — $2.50/GPU-hr ROCm
  - NVIDIA H100 (RunPod / Lambda)      — $3.89/GPU-hr CUDA
  - Featherless API                    — $0 inference credits (hackathon)
  - Anthropic / OpenAI API             — pay-per-token

Decision logic:
  1. If model is Gemma 4 → AMD MI300X (primary)
  2. If model is open-source ≤ 13B → Featherless (zero cost)
  3. If model is proprietary → API (cheapest: Haiku < GPT-4o-mini)
  4. If latency SLA < 200ms → nearest region
  5. If data_sovereignty=EU → EU-region only
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CloudProvider(str, Enum):
    AMD_MI300X = "amd_mi300x"
    NVIDIA_H100 = "nvidia_h100"
    FEATHERLESS = "featherless"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass
class InfraOption:
    provider: CloudProvider
    region: str
    cost_per_1k_tokens: float   # USD
    avg_latency_ms: float
    gpu_memory_gb: float
    data_sovereignty: list[str]  # ["US", "EU", "GLOBAL"]
    available: bool = True


INFRA_CATALOG: list[InfraOption] = [
    InfraOption(CloudProvider.AMD_MI300X, "us-east-1",   0.002, 120, 192, ["US", "GLOBAL"]),
    InfraOption(CloudProvider.AMD_MI300X, "eu-west-1",   0.0022, 140, 192, ["EU", "GLOBAL"]),
    InfraOption(CloudProvider.NVIDIA_H100, "us-east-1",  0.004, 100, 80,  ["US", "GLOBAL"]),
    InfraOption(CloudProvider.FEATHERLESS, "global",     0.0,   350, 0,   ["GLOBAL"]),
    InfraOption(CloudProvider.ANTHROPIC,   "global",     0.00025, 400, 0, ["GLOBAL"]),
    InfraOption(CloudProvider.OPENAI,      "global",     0.00015, 300, 0, ["GLOBAL"]),
]


@dataclass
class ArbitrageRequest:
    model_id: str
    is_open_source: bool
    max_latency_ms: float = 500.0
    data_sovereignty: str = "GLOBAL"   # "US" | "EU" | "GLOBAL"
    preferred_provider: Optional[CloudProvider] = None


def select_backend(req: ArbitrageRequest) -> InfraOption:
    """
    Select optimal infrastructure for a given model/constraint combination.
    Priority: compliance → latency → cost.
    """
    candidates = [
        opt for opt in INFRA_CATALOG
        if opt.available
        and opt.avg_latency_ms <= req.max_latency_ms
        and req.data_sovereignty in opt.data_sovereignty
    ]

    if not candidates:
        # Relax latency constraint
        candidates = [o for o in INFRA_CATALOG if req.data_sovereignty in o.data_sovereignty]

    if req.preferred_provider:
        preferred = [c for c in candidates if c.provider == req.preferred_provider]
        if preferred:
            candidates = preferred

    # Gemma 4 → AMD MI300X preferred
    if req.model_id == "gemma4":
        amd = [c for c in candidates if c.provider == CloudProvider.AMD_MI300X]
        if amd:
            return min(amd, key=lambda x: x.cost_per_1k_tokens)

    # Open-source small → Featherless (free)
    if req.is_open_source:
        fl = [c for c in candidates if c.provider == CloudProvider.FEATHERLESS]
        if fl:
            return fl[0]

    # Otherwise: cheapest that meets constraints
    return min(candidates, key=lambda x: x.cost_per_1k_tokens)


def estimate_cost(
    n_tokens: int,
    option: InfraOption,
    n_requests: int = 1,
) -> float:
    """Estimate USD cost for a workload."""
    return round(n_tokens / 1000 * option.cost_per_1k_tokens * n_requests, 6)


def healthcheck() -> dict:
    return {
        "layer": "L8_multicloud",
        "infra_options": len(INFRA_CATALOG),
        "providers": list({o.provider.value for o in INFRA_CATALOG}),
    }
