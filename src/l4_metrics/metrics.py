"""
CITADEL L4 — Evaluation Metrics.

Implements all CITADEL evaluation metrics:
  - Accuracy / per-category accuracy
  - ECE (Expected Calibration Error) — ECB-specific
  - Hallucination rate (high-confidence wrong answers)
  - Refusal rate (model refuses to answer)
  - Throughput (tokens/second)
  - Energy efficiency (tokens/joule, if power monitoring available)
  - Multi-model comparison (delta vs. baseline)
"""
from __future__ import annotations

import math
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── Calibration metrics ───────────────────────────────────────────────────────

def compute_ece(confidences: list[float], corrects: list[bool], n_bins: int = 10) -> float:
    """
    Expected Calibration Error.
    Lower is better. 0.0 = perfectly calibrated.
    """
    assert len(confidences) == len(corrects)
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for conf, ok in zip(confidences, corrects):
        idx = min(int(conf * n_bins), n_bins - 1)
        bins[idx].append((conf, ok))
    ece = 0.0
    n = len(confidences)
    for b in bins:
        if not b:
            continue
        avg_conf = sum(c for c, _ in b) / len(b)
        avg_acc  = sum(int(ok) for _, ok in b) / len(b)
        ece += (len(b) / n) * abs(avg_conf - avg_acc)
    return round(ece, 4)


def compute_brier_score(confidences: list[float], corrects: list[bool]) -> float:
    """Brier score — mean squared error of probability predictions."""
    if not confidences:
        return 0.0
    return round(
        sum((c - int(ok)) ** 2 for c, ok in zip(confidences, corrects)) / len(confidences),
        4
    )


# ── Task-level metrics ────────────────────────────────────────────────────────

def compute_accuracy(correct: list[bool]) -> float:
    if not correct:
        return 0.0
    return round(sum(correct) / len(correct), 4)


def compute_per_category(results: list[dict]) -> dict[str, float]:
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["correct"])
    return {cat: compute_accuracy(vals) for cat, vals in by_cat.items()}


# ── Hallucination & refusal ───────────────────────────────────────────────────

_REFUSAL_SIGNALS = [
    "i don't know", "i cannot", "i'm not sure", "i'm unable",
    "i don't have information", "as an ai", "i cannot provide",
    "i'm not able to", "i don't have access", "unknown", "not available",
    "cannot determine", "no way to know",
]


def is_refusal(response: str) -> bool:
    r = response.lower().strip()
    return any(sig in r for sig in _REFUSAL_SIGNALS) or len(r) < 10


def compute_hallucination_rate(
    confidences: list[float], corrects: list[bool], threshold: float = 0.8
) -> float:
    """Fraction of responses that were high-confidence but wrong."""
    high_conf_wrong = sum(
        1 for c, ok in zip(confidences, corrects) if c >= threshold and not ok
    )
    return round(high_conf_wrong / len(confidences), 4) if confidences else 0.0


def compute_refusal_rate(responses: list[str]) -> float:
    return round(sum(1 for r in responses if is_refusal(r)) / len(responses), 4) if responses else 0.0


# ── Efficiency metrics ────────────────────────────────────────────────────────

@dataclass
class EfficiencyStats:
    total_tokens: int
    total_time_ms: float
    tokens_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p99_latency_ms: float
    energy_joules: Optional[float] = None
    tokens_per_joule: Optional[float] = None


def compute_efficiency(latencies_ms: list[float], token_counts: list[int],
                       energy_joules: Optional[list[float]] = None) -> EfficiencyStats:
    if not latencies_ms:
        return EfficiencyStats(0, 0, 0, 0, 0, 0)

    sorted_lat = sorted(latencies_ms)
    total_tokens = sum(token_counts)
    total_time = sum(latencies_ms)

    def percentile(data: list[float], p: float) -> float:
        idx = max(0, int(len(data) * p / 100) - 1)
        return data[idx]

    tps = total_tokens / (total_time / 1000) if total_time > 0 else 0

    total_energy = sum(energy_joules) if energy_joules else None
    tokens_per_joule = (total_tokens / total_energy) if total_energy else None

    return EfficiencyStats(
        total_tokens=total_tokens,
        total_time_ms=total_time,
        tokens_per_second=round(tps, 2),
        avg_latency_ms=round(total_time / len(latencies_ms), 2),
        p50_latency_ms=round(percentile(sorted_lat, 50), 2),
        p99_latency_ms=round(percentile(sorted_lat, 99), 2),
        energy_joules=round(total_energy, 4) if total_energy else None,
        tokens_per_joule=round(tokens_per_joule, 4) if tokens_per_joule else None,
    )


# ── Energy monitoring (AMD ROCm) ──────────────────────────────────────────────

class EnergyMonitor:
    """
    Monitors GPU power usage for energy-efficiency reporting.
    Uses ROCm System Management Interface (rocm-smi) on AMD.
    Falls back to nvidia-smi on CUDA. Returns 0 if neither available.
    """

    def __init__(self):
        self._backend = self._detect()
        self._start_time: Optional[float] = None
        self._start_power: Optional[float] = None

    def _detect(self) -> str:
        import subprocess
        for cmd, backend in [("rocm-smi", "rocm"), ("nvidia-smi", "cuda")]:
            try:
                subprocess.run([cmd, "--version"], capture_output=True, timeout=2)
                return backend
            except Exception:
                pass
        return "none"

    def _read_power_watts(self) -> Optional[float]:
        import subprocess, re
        if self._backend == "rocm":
            try:
                out = subprocess.check_output(["rocm-smi", "--showpower"], timeout=5).decode()
                m = re.search(r"GPU Power Cap.*?:\s*([\d.]+)", out)
                return float(m.group(1)) if m else None
            except Exception:
                return None
        elif self._backend == "cuda":
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                    timeout=5
                ).decode()
                return float(out.strip())
            except Exception:
                return None
        return None

    def start(self) -> None:
        self._start_time = time.perf_counter()
        self._start_power = self._read_power_watts()

    def stop(self) -> Optional[float]:
        if self._start_time is None:
            return None
        elapsed = time.perf_counter() - self._start_time
        end_power = self._read_power_watts()
        if self._start_power is None or end_power is None:
            return None
        avg_power = (self._start_power + end_power) / 2
        return avg_power * elapsed  # joules = watts * seconds


# ── Multi-model comparison ────────────────────────────────────────────────────

@dataclass
class ModelResult:
    model_id: str
    suite: str
    accuracy: float
    per_category: dict[str, float]
    ece: Optional[float]
    hallucination_rate: Optional[float]
    refusal_rate: float
    efficiency: EfficiencyStats
    run_timestamp: str = ""
    run_hash: str = ""        # SHA-256 of sorted results for reproducibility


def compute_leaderboard(results: list[ModelResult]) -> list[dict]:
    """
    Rank models by composite score.
    Score = accuracy (60%) + (1 - ECE) * 20% + (1 - hallucination) * 20%
    """
    rows = []
    for r in results:
        ece_penalty = r.ece or 0.0
        hall_penalty = r.hallucination_rate or 0.0
        composite = (
            0.60 * r.accuracy
            + 0.20 * (1.0 - ece_penalty)
            + 0.20 * (1.0 - hall_penalty)
        )
        rows.append({
            "model_id": r.model_id,
            "accuracy": r.accuracy,
            "ece": r.ece,
            "hallucination_rate": r.hallucination_rate,
            "refusal_rate": r.refusal_rate,
            "tokens_per_second": r.efficiency.tokens_per_second,
            "composite_score": round(composite, 4),
        })
    return sorted(rows, key=lambda x: x["composite_score"], reverse=True)
