"""
CITADEL L5 — Evaluation Runner.

Orchestrates a full evaluation run:
  1. Load task suite (L2)
  2. Format prompts per model (L3)
  3. Generate responses (L1)
  4. Score responses (L2)
  5. Compute metrics (L4)
  6. Sign & chain results (L7)
  7. Write results JSON

Usage:
    python -m citadel.l5_infra.runner --suite ecb_v2 --model gemma4
    python -m citadel.l5_infra.runner --suite all --model all --out results/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# ROOT = repo root. src/l5_infra/runner.py -> parents[2] is the repo root
# (both locally and on container deploys).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from l2_tasks.task_suite import get_suite, TaskItem, ScoredItem, SUITES
from l3_adapters.model_registry import MODELS, get_model, format_prompt, get_stop_sequences
from l4_metrics.metrics import (
    compute_accuracy, compute_per_category, compute_efficiency,
    compute_ece, compute_hallucination_rate, compute_refusal_rate,
    is_refusal, EnergyMonitor, ModelResult,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = ROOT / "results"


# ── Runner ────────────────────────────────────────────────────────────────────

class EvalRunner:

    def __init__(self, hardware_layer=None):
        self.hardware = hardware_layer   # L1 HardwareLayer (optional: mock for testing)
        self.energy_monitor = EnergyMonitor()

    def run_suite(
        self,
        suite_name: str,
        model_id: str,
        max_items: Optional[int] = None,
        seed: int = 42,
    ) -> dict:
        suite = get_suite(suite_name)
        model_spec = get_model(model_id)
        items = suite.load()
        if max_items:
            items = items[:max_items]

        logger.info("Running %s / %s on %d items", suite_name, model_id, len(items))

        scored: list[ScoredItem] = []
        latencies: list[float] = []
        token_counts: list[int] = []
        responses_raw: list[str] = []
        confidences: list[float] = []

        for i, item in enumerate(items):
            prompt = format_prompt(item.prompt, model_spec)
            stops = get_stop_sequences(model_spec)

            self.energy_monitor.start()
            t0 = time.perf_counter()

            if self.hardware:
                from l1_hardware.backend import GenerationConfig
                config = GenerationConfig(
                    max_new_tokens=512, temperature=0.0,
                    seed=seed, stop_sequences=stops,
                )
                result = self.hardware.generate(model_id, prompt, config)
                response = result.text
                latency_ms = result.latency_ms
                n_tokens = result.completion_tokens
            else:
                # Mock mode: return empty response (for unit testing)
                response = ""
                latency_ms = 1.0
                n_tokens = 0

            energy = self.energy_monitor.stop()

            si = suite.score_item(item, response)
            si.latency_ms = latency_ms
            si.model = model_id

            scored.append(si)
            latencies.append(latency_ms)
            token_counts.append(n_tokens)
            responses_raw.append(response)
            if si.confidence is not None:
                confidences.append(si.confidence)

            if (i + 1) % 5 == 0:
                logger.info("  %d/%d done, last latency=%.1fms", i + 1, len(items), latency_ms)

        # Aggregate
        correct_flags = [s.correct for s in scored]
        agg = suite.aggregate(scored)
        efficiency = compute_efficiency(latencies, token_counts)
        ece = compute_ece(confidences, [s.correct for s in scored[:len(confidences)]]) if confidences else None
        hall_rate = compute_hallucination_rate(confidences, [s.correct for s in scored[:len(confidences)]]) if confidences else None
        refusal_rate = compute_refusal_rate(responses_raw)

        run_id = f"{suite_name}_{model_id}_{int(time.time())}"
        result_payload = {
            "run_id": run_id,
            "suite": suite_name,
            "model": model_id,
            "model_display": MODELS[model_id].display_name,
            "n_items": len(items),
            "accuracy": compute_accuracy(correct_flags),
            "ece": ece,
            "hallucination_rate": hall_rate,
            "refusal_rate": refusal_rate,
            "efficiency": {
                "avg_latency_ms": efficiency.avg_latency_ms,
                "p99_latency_ms": efficiency.p99_latency_ms,
                "tokens_per_second": efficiency.tokens_per_second,
                "energy_joules": efficiency.energy_joules,
                "tokens_per_joule": efficiency.tokens_per_joule,
            },
            "per_category": agg.get("per_category", {}),
            "aggregate": agg,
            "run_hash": self._hash_results(scored),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [self._scored_to_dict(s) for s in scored],
        }
        return result_payload

    def _scored_to_dict(self, s: ScoredItem) -> dict:
        return {
            "id": s.item_id,
            "category": s.category,
            "expected": s.expected,
            "predicted": s.predicted[:200],   # truncate for storage
            "correct": s.correct,
            "confidence": s.confidence,
            "latency_ms": round(s.latency_ms, 2),
            "error": s.error,
        }

    def _hash_results(self, scored: list[ScoredItem]) -> str:
        """SHA-256 of sorted (id, correct) pairs — reproducibility anchor."""
        payload = json.dumps(
            sorted([(s.item_id, s.correct) for s in scored]),
            sort_keys=True
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


def save_results(payload: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{payload['run_id']}.json"
    path = out_dir / fname
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    logger.info("Results saved → %s", path)
    return path


# ── Mock runner for demo/testing ──────────────────────────────────────────────

def run_mock_suite(suite_name: str, model_id: str) -> dict:
    """
    Generates realistic mock results for demo purposes.
    Used when no API keys or GPU are available.
    """
    import random
    rng = random.Random(42)

    mock_accuracies = {
        "gemma4": 0.81,
        "llama4": 0.78,
        "claude": 0.85,
        "gpt4o_mini": 0.83,
        "qwen3": 0.76,
        "mistral7b": 0.69,
    }
    base_acc = mock_accuracies.get(model_id, 0.70)
    acc = base_acc + rng.uniform(-0.03, 0.03)

    suite = get_suite(suite_name)
    items = suite.load()

    run_id = f"{suite_name}_{model_id}_{int(time.time())}"
    return {
        "run_id": run_id,
        "suite": suite_name,
        "model": model_id,
        "model_display": MODELS[model_id].display_name,
        "n_items": len(items),
        "accuracy": round(acc, 4),
        "ece": round(rng.uniform(0.05, 0.20), 4),
        "hallucination_rate": round(rng.uniform(0.02, 0.12), 4),
        "refusal_rate": round(rng.uniform(0.01, 0.08), 4),
        "efficiency": {
            "avg_latency_ms": round(rng.uniform(200, 800), 1),
            "p99_latency_ms": round(rng.uniform(800, 2000), 1),
            "tokens_per_second": round(rng.uniform(20, 120), 1),
            "energy_joules": None,
            "tokens_per_joule": None,
        },
        "per_category": {
            cat: round(acc + rng.uniform(-0.10, 0.10), 4)
            for cat in ["calibration", "factual", "temporal", "reasoning", "novel", "refusal"]
        },
        "run_hash": hashlib.sha256(f"{run_id}".encode()).hexdigest()[:16],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mock": True,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CITADEL Evaluation Runner")
    parser.add_argument("--suite", default="ecb_v2",
                        help=f"Suite name or 'all'. Available: {list(SUITES)}")
    parser.add_argument("--model", default="gemma4",
                        help=f"Model ID or 'all'. Available: {list(MODELS)}")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock results (no GPU/API keys needed)")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    suites = list(SUITES) if args.suite == "all" else [args.suite]
    models = list(MODELS) if args.model == "all" else [args.model]

    for suite_name in suites:
        for model_id in models:
            if args.mock:
                payload = run_mock_suite(suite_name, model_id)
            else:
                runner = EvalRunner()
                payload = runner.run_suite(suite_name, model_id, max_items=args.max_items)
            save_results(payload, args.out)
            print(f"  {suite_name}/{model_id}: accuracy={payload['accuracy']:.3f}  ece={payload.get('ece')}  hall={payload.get('hallucination_rate')}")
