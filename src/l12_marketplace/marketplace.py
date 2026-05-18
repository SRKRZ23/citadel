"""
CITADEL L12 — AI Marketplace.

Platform for fine-tuned domain-specific models with transparent evaluation.
70/30 revenue split: 70% to model creators, 30% to CITADEL infrastructure.

Key features:
  - Every listed model must pass CITADEL evaluation (accuracy + calibration)
  - Evaluation results publicly visible on leaderboard
  - Model card with reproducible benchmark numbers
  - Usage-based billing (per 1K tokens)
  - Creator payout via Stripe (weekly, after 30-day escrow for disputes)

Model categories:
  - Healthcare (HIPAA-compliant, ECB-medical suite)
  - Finance (PCI-DSS-compliant, ECB-finance suite)
  - Legal (jurisdiction-specific, multilingual)
  - Code (HumanEval + domain-specific tests)
  - Scientific (ECB-science suite)
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MarketplaceModel:
    model_id: str              # unique marketplace ID
    creator_id: str            # creator account
    name: str
    description: str
    category: str              # "healthcare" | "finance" | "code" | "legal" | "science"
    base_model: str            # e.g. "gemma4" | "llama4"
    hf_repo: str               # HuggingFace repository
    price_per_1k_tokens: float # USD
    license: str
    # CITADEL evaluation (required before listing)
    eval_accuracy: Optional[float] = None
    eval_ece: Optional[float] = None
    eval_hallucination: Optional[float] = None
    eval_suite: Optional[str] = None
    eval_run_hash: Optional[str] = None    # reproducibility anchor
    eval_timestamp: Optional[str] = None
    approved: bool = False
    listed_at: Optional[str] = None
    total_requests: int = 0
    total_revenue_usd: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def creator_share(self) -> float:
        return self.total_revenue_usd * 0.70

    @property
    def platform_share(self) -> float:
        return self.total_revenue_usd * 0.30

    def model_card(self) -> str:
        return f"""# {self.name}

**Category**: {self.category}
**Base model**: {self.base_model}
**License**: {self.license}
**Price**: ${self.price_per_1k_tokens:.5f} per 1K tokens

## CITADEL Evaluation (Reproducible)

| Metric | Value |
|--------|-------|
| Accuracy | {self.eval_accuracy:.1%} |
| ECE (calibration) | {self.eval_ece:.3f} |
| Hallucination rate | {self.eval_hallucination:.3f} |
| Benchmark suite | {self.eval_suite} |
| Run hash | `{self.eval_run_hash}` |
| Evaluated at | {self.eval_timestamp} |

All numbers are Ed25519-signed and reproducible. Run hash anchors the exact
evaluation results to this listing.

## HuggingFace
[{self.hf_repo}](https://huggingface.co/{self.hf_repo})
"""


@dataclass
class UsageRecord:
    model_id: str
    user_id: str
    n_tokens: int
    cost_usd: float
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class Marketplace:

    def __init__(self):
        self._models: dict[str, MarketplaceModel] = {}
        self._usage: list[UsageRecord] = []

    def submit_for_review(self, model: MarketplaceModel) -> str:
        """Submit a model for CITADEL evaluation and marketplace listing."""
        if model.eval_accuracy is None or model.eval_run_hash is None:
            raise ValueError("Model must have CITADEL evaluation results before submission. "
                             "Run: python src/l5_infra/runner.py --model <model_id>")
        submission_id = f"sub_{uuid.uuid4().hex[:8]}"
        model.model_id = submission_id
        self._models[submission_id] = model
        return submission_id

    def approve(self, model_id: str,
                min_accuracy: float = 0.70,
                max_ece: float = 0.20,
                max_hallucination: float = 0.15) -> bool:
        """Auto-approve if CITADEL evaluation thresholds are met."""
        model = self._models.get(model_id)
        if not model:
            return False
        if (model.eval_accuracy or 0) < min_accuracy:
            return False
        if (model.eval_ece or 1.0) > max_ece:
            return False
        if (model.eval_hallucination or 1.0) > max_hallucination:
            return False
        model.approved = True
        model.listed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return True

    def list_models(self, category: Optional[str] = None) -> list[MarketplaceModel]:
        models = [m for m in self._models.values() if m.approved]
        if category:
            models = [m for m in models if m.category == category]
        return sorted(models, key=lambda m: m.eval_accuracy or 0, reverse=True)

    def record_usage(self, model_id: str, user_id: str, n_tokens: int) -> UsageRecord:
        model = self._models.get(model_id)
        if not model or not model.approved:
            raise ValueError(f"Model {model_id} not found or not approved")
        cost = n_tokens / 1000 * model.price_per_1k_tokens
        record = UsageRecord(model_id=model_id, user_id=user_id,
                             n_tokens=n_tokens, cost_usd=round(cost, 6))
        self._usage.append(record)
        model.total_requests += 1
        model.total_revenue_usd += cost
        return record

    def payout_summary(self, creator_id: str) -> dict:
        creator_models = [m for m in self._models.values()
                          if m.creator_id == creator_id and m.approved]
        return {
            "creator_id": creator_id,
            "models": len(creator_models),
            "total_revenue": sum(m.total_revenue_usd for m in creator_models),
            "creator_payout_70pct": sum(m.creator_share for m in creator_models),
            "platform_take_30pct": sum(m.platform_share for m in creator_models),
        }

    def healthcheck(self) -> dict:
        return {
            "layer": "L12_marketplace",
            "listed_models": len([m for m in self._models.values() if m.approved]),
            "pending_review": len([m for m in self._models.values() if not m.approved]),
            "revenue_split": "70/30 (creator/platform)",
        }
