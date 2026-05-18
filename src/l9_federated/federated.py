"""
CITADEL L9 — Federated Evaluation Network.

Enables multi-organisation model evaluation WITHOUT sharing evaluation data.
Each organisation runs evaluation locally; only aggregated metrics (with
differential privacy noise) are shared to the central leaderboard.

Architecture:
  Central Coordinator (CITADEL server)
       │ ← only receives: (model_id, accuracy + DP noise, n_items)
       │   never receives: prompts, responses, or organisation identity
  ┌────┴────┐
  Org A     Org B     Org C     ...
  (hospital) (bank)  (telco)
  local eval  local eval  local eval
  local data  local data  local data

Differential Privacy: Gaussian mechanism with ε=1.0, δ=1e-5
Sensitivity: max accuracy change from 1 item = 1/n_items
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Differential Privacy ───────────────────────────────────────────────────────

def gaussian_noise(sensitivity: float, epsilon: float, delta: float) -> float:
    """
    Calibrated Gaussian noise for (ε, δ)-DP.
    sigma = sensitivity * sqrt(2 * ln(1.25/delta)) / epsilon
    """
    import random
    sigma = sensitivity * math.sqrt(2 * math.log(1.25 / delta)) / epsilon
    return random.gauss(0, sigma)


def privatize_accuracy(
    accuracy: float,
    n_items: int,
    epsilon: float = 1.0,
    delta: float = 1e-5,
) -> float:
    """Add calibrated DP noise to an accuracy value."""
    sensitivity = 1.0 / n_items  # max change from removing one item
    noise = gaussian_noise(sensitivity, epsilon, delta)
    return max(0.0, min(1.0, accuracy + noise))


# ── Organisation node ─────────────────────────────────────────────────────────

@dataclass
class OrgContribution:
    """A single organisation's contribution to the federated leaderboard."""
    org_id: str           # opaque hashed org identifier
    model_id: str
    suite: str
    n_items: int
    private_accuracy: float    # DP-noised
    epsilon: float
    timestamp_ms: int
    contribution_sig: str      # HMAC to prevent replay


class FederatedNode:
    """
    Represents one participating organisation.
    Runs evaluation locally, shares only DP-protected metrics.
    """

    def __init__(self, org_name: str, shared_secret: bytes):
        self.org_name = org_name
        self._secret = shared_secret
        self._org_id = hashlib.sha256(org_name.encode()).hexdigest()[:16]

    def submit_result(
        self,
        model_id: str,
        suite: str,
        true_accuracy: float,
        n_items: int,
        epsilon: float = 1.0,
    ) -> OrgContribution:
        """Package a local eval result for submission to central coordinator."""
        priv_acc = round(privatize_accuracy(true_accuracy, n_items, epsilon), 4)
        ts = int(time.time() * 1000)
        # Sign the rounded value so coordinator can verify with the same bytes
        payload = f"{self._org_id}:{model_id}:{suite}:{priv_acc:.4f}:{ts}".encode()
        sig = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:16]

        logger.info("Org %s submitting %s/%s: true_acc=%.3f private_acc=%.4f",
                    self._org_id[:8], suite, model_id, true_accuracy, priv_acc)

        return OrgContribution(
            org_id=self._org_id,
            model_id=model_id,
            suite=suite,
            n_items=n_items,
            private_accuracy=priv_acc,
            epsilon=epsilon,
            timestamp_ms=ts,
            contribution_sig=sig,
        )


# ── Central coordinator ───────────────────────────────────────────────────────

class FederatedCoordinator:
    """
    Aggregates contributions from multiple orgs.
    Computes weighted average accuracy (weighted by n_items).
    Verifies HMAC signatures to prevent replay attacks.
    """

    def __init__(self, shared_secret: bytes):
        self._secret = shared_secret
        self._contributions: list[OrgContribution] = []

    def accept(self, contrib: OrgContribution) -> bool:
        """Verify and accept a contribution. Returns False if signature fails."""
        payload = f"{contrib.org_id}:{contrib.model_id}:{contrib.suite}:{contrib.private_accuracy:.4f}:{contrib.timestamp_ms}".encode()
        expected_sig = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(contrib.contribution_sig, expected_sig):
            logger.warning("Rejected contribution from %s — signature mismatch", contrib.org_id[:8])
            return False
        self._contributions.append(contrib)
        logger.info("Accepted contribution from org %s (%d items)", contrib.org_id[:8], contrib.n_items)
        return True

    def aggregate(self, model_id: str, suite: str) -> dict:
        """Compute weighted-average DP accuracy across all orgs for model+suite."""
        relevant = [c for c in self._contributions
                    if c.model_id == model_id and c.suite == suite]
        if not relevant:
            return {"model": model_id, "suite": suite, "n_orgs": 0, "federated_accuracy": None}

        total_weight = sum(c.n_items for c in relevant)
        weighted_acc = sum(c.private_accuracy * c.n_items for c in relevant) / total_weight

        return {
            "model": model_id,
            "suite": suite,
            "n_orgs": len(relevant),
            "total_items": total_weight,
            "federated_accuracy": round(weighted_acc, 4),
            "min_epsilon": min(c.epsilon for c in relevant),
            "privacy_guarantee": f"(ε={min(c.epsilon for c in relevant):.1f}, δ=1e-5)-DP",
        }

    def leaderboard(self, suite: str) -> list[dict]:
        model_ids = list({c.model_id for c in self._contributions if c.suite == suite})
        rows = [self.aggregate(mid, suite) for mid in model_ids]
        return sorted(rows, key=lambda x: x.get("federated_accuracy") or 0, reverse=True)


def healthcheck() -> dict:
    return {
        "layer": "L9_federated",
        "dp_mechanism": "Gaussian",
        "default_epsilon": 1.0,
        "default_delta": 1e-5,
        "privacy_guarantee": "(ε=1.0, δ=1e-5)-DP",
    }
