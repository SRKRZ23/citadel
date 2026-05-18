"""
CITADEL L7 — Evaluation Audit Chain.

Wraps the CITADEL Ed25519 audit chain for eval use cases:
  - Sign each model response + score with Ed25519
  - Chain all responses in a run with SHA-256 prev_hash links
  - Verify chain integrity (tamper-evident)
  - Export audit log to JSONL for regulatory compliance

Why: Evaluators need to know leaderboard numbers weren't cherry-picked.
A cryptographically signed chain of every response proves the published
accuracy number corresponds to the exact responses that were scored.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from l7_audit.audit_chain import AuditChain, SignedRecord


class EvalAuditChain:
    """
    Wraps AuditChain with eval-specific entry format.
    Each entry = {run_id, model, suite, item_id, correct, latency_ms, response_hash}
    """

    def __init__(self, run_id: str = "default", model_id: str = "", suite: str = ""):
        self.run_id = run_id
        self.model_id = model_id
        self.suite = suite
        self._chain = AuditChain()
        self._records: list[SignedRecord] = []

    def log_eval_start(self, run_id: str, suites: list[str], models: list[str]) -> SignedRecord:
        self.run_id = run_id
        return self._chain.append({
            "event": "eval_start",
            "run_id": run_id,
            "suites": suites,
            "models": models,
            "ts": int(time.time() * 1000),
        })

    def log_response(
        self,
        item_id: str,
        response: str,
        correct: bool,
        latency_ms: float,
        confidence: Optional[float] = None,
    ) -> SignedRecord:
        response_hash = hashlib.sha256(response.encode()).hexdigest()[:16]
        entry = {
            "event": "response",
            "run_id": self.run_id,
            "model": self.model_id,
            "suite": self.suite,
            "item_id": item_id,
            "correct": correct,
            "latency_ms": round(latency_ms, 3),
            "response_hash": response_hash,
            "ts": int(time.time() * 1000),
        }
        if confidence is not None:
            entry["confidence"] = round(confidence, 4)
        record = self._chain.append(entry)
        self._records.append(record)
        return record

    def log_suite_result(self, model_id: str, suite: str, accuracy: float, n: int) -> SignedRecord:
        return self._chain.append({
            "event": "suite_result",
            "run_id": self.run_id,
            "model": model_id,
            "suite": suite,
            "accuracy": round(accuracy, 4),
            "n": n,
            "ts": int(time.time() * 1000),
        })

    def verify(self) -> bool:
        return self._chain.verify_chain()

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for rec in self._records:
                f.write(json.dumps({
                    "seq": rec.seq,
                    "entry": rec.entry,
                    "prev_hash": rec.prev_hash,
                    "record_hash": rec.record_hash,
                    "signature": rec.signature.hex() if isinstance(rec.signature, bytes) else rec.signature,
                }, separators=(",", ":")) + "\n")
        logger.info("Audit chain exported → %s (%d records)", path, len(self._records))

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "model": self.model_id,
            "suite": self.suite,
            "n_records": len(self._records),
            "chain_length": self._chain._seq,
            "chain_verified": self.verify(),
        }
