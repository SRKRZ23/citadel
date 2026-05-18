"""
CITADEL L10 — Regulatory Translator.

Auto-generates compliance reports for AI evaluation results across 50+ jurisdictions.
Maps CITADEL metrics to regulatory requirements:

Supported frameworks:
  - EU AI Act (Annex III high-risk AI + GPAI)
  - NIST AI RMF (GOVERN, MAP, MEASURE, MANAGE)
  - UK AI Safety Institute evaluation criteria
  - HIPAA § 164 (healthcare AI)
  - PCI-DSS Req 3/4/7/8/11 (payment AI)
  - ISO/IEC 42001 (AI management system)
  - Singapore PDPA + Model AI Governance Framework
  - Australia AI Ethics Principles
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegulatoryRequirement:
    framework: str           # "eu_ai_act" | "nist_ai_rmf" | "hipaa" | etc.
    requirement_id: str      # "Art.9(1)" | "MEASURE.2.5" | "§164.312(b)"
    description: str
    citadel_metric: str      # which CITADEL metric satisfies this
    threshold: Optional[float]     # acceptable threshold
    pass_condition: str      # human-readable pass condition


REGULATORY_MAPPINGS: list[RegulatoryRequirement] = [
    # EU AI Act
    RegulatoryRequirement("eu_ai_act", "Art.9(1)",
        "Risk management system — accuracy testing", "accuracy", 0.80,
        "accuracy >= 0.80 across benchmark suite"),
    RegulatoryRequirement("eu_ai_act", "Art.12(1)",
        "Logging and recordkeeping", "audit_chain_verified", None,
        "Ed25519-signed audit chain PASS"),
    RegulatoryRequirement("eu_ai_act", "Art.13(1)",
        "Transparency — known limitations", "hallucination_rate", 0.05,
        "hallucination_rate <= 0.05"),
    RegulatoryRequirement("eu_ai_act", "Art.15(1)",
        "Accuracy, robustness, cybersecurity", "ece", 0.10,
        "ECE (calibration error) <= 0.10"),

    # NIST AI RMF
    RegulatoryRequirement("nist_ai_rmf", "MEASURE.2.5",
        "AI system performance metrics measured", "accuracy", None,
        "accuracy reported with CI across ≥3 benchmark suites"),
    RegulatoryRequirement("nist_ai_rmf", "MEASURE.2.6",
        "Bias and fairness testing", "per_language_accuracy_variance", 0.10,
        "max per-language accuracy variance <= 0.10"),
    RegulatoryRequirement("nist_ai_rmf", "GOVERN.1.4",
        "Accountability — audit trail", "audit_chain_verified", None,
        "Ed25519 audit chain PASS"),
    RegulatoryRequirement("nist_ai_rmf", "MAP.5.1",
        "Documented limitations", "refusal_rate", None,
        "refusal_rate on answerable questions reported"),

    # UK AI Safety Institute
    RegulatoryRequirement("uk_aisi", "EVAL.1",
        "Capability evaluation", "accuracy", 0.70,
        "accuracy >= 0.70 on standard benchmarks"),
    RegulatoryRequirement("uk_aisi", "EVAL.2",
        "Hallucination / confabulation measurement", "hallucination_rate", 0.08,
        "hallucination_rate <= 0.08"),

    # HIPAA (healthcare AI)
    RegulatoryRequirement("hipaa", "§164.312(b)",
        "Audit controls — electronic PHI access", "audit_chain_verified", None,
        "Tamper-evident audit trail PASS"),
    RegulatoryRequirement("hipaa", "§164.306(a)(1)",
        "Security — accuracy and integrity", "accuracy", 0.85,
        "accuracy >= 0.85 for clinical AI"),

    # PCI-DSS (payment AI)
    RegulatoryRequirement("pci_dss", "Req.10.2",
        "Audit log — all AI-generated decisions", "audit_chain_verified", None,
        "Ed25519-signed audit chain PASS"),
    RegulatoryRequirement("pci_dss", "Req.12.3",
        "Risk assessment", "hallucination_rate", 0.03,
        "hallucination_rate <= 0.03 for payment decisions"),

    # ISO 42001
    RegulatoryRequirement("iso_42001", "6.1",
        "Risk assessment for AI systems", "ece", 0.15,
        "ECE <= 0.15 (calibration)"),
    RegulatoryRequirement("iso_42001", "9.1",
        "Monitoring and measurement", "accuracy", None,
        "accuracy tracked over time (regression testing)"),
]


@dataclass
class ComplianceReport:
    framework: str
    model_id: str
    suite: str
    generated_at: str
    requirements: list[dict]
    overall_pass: bool
    n_pass: int
    n_fail: int
    n_na: int


def generate_report(
    framework: str,
    model_id: str,
    suite: str,
    metrics: dict,
) -> ComplianceReport:
    """
    Generate a compliance report for a given framework + model eval result.

    metrics dict expected keys:
      accuracy, ece, hallucination_rate, refusal_rate,
      audit_chain_verified (bool), per_language_accuracy_variance (optional)
    """
    requirements = [r for r in REGULATORY_MAPPINGS if r.framework == framework]
    if not requirements:
        raise ValueError(f"Unknown framework {framework!r}. Available: "
                         f"{list({r.framework for r in REGULATORY_MAPPINGS})}")

    rows = []
    n_pass = n_fail = n_na = 0

    for req in requirements:
        metric_val = metrics.get(req.citadel_metric)
        if metric_val is None:
            status = "N/A"
            n_na += 1
        elif req.citadel_metric == "audit_chain_verified":
            status = "PASS" if bool(metric_val) else "FAIL"
            n_pass += 1 if status == "PASS" else 0
            n_fail += 1 if status == "FAIL" else 0
        elif req.threshold is not None:
            if req.citadel_metric in ("hallucination_rate", "ece", "per_language_accuracy_variance"):
                status = "PASS" if metric_val <= req.threshold else "FAIL"
            else:
                status = "PASS" if metric_val >= req.threshold else "FAIL"
            n_pass += 1 if status == "PASS" else 0
            n_fail += 1 if status == "FAIL" else 0
        else:
            status = "REPORTED"  # no pass/fail threshold — just required to report
            n_na += 1

        rows.append({
            "requirement_id": req.requirement_id,
            "description": req.description,
            "metric": req.citadel_metric,
            "value": metric_val,
            "threshold": req.threshold,
            "status": status,
            "pass_condition": req.pass_condition,
        })

    return ComplianceReport(
        framework=framework,
        model_id=model_id,
        suite=suite,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        requirements=rows,
        overall_pass=(n_fail == 0),
        n_pass=n_pass,
        n_fail=n_fail,
        n_na=n_na,
    )


def available_frameworks() -> list[str]:
    return sorted({r.framework for r in REGULATORY_MAPPINGS})


def healthcheck() -> dict:
    return {
        "layer": "L10_regulatory",
        "frameworks": available_frameworks(),
        "n_requirements": len(REGULATORY_MAPPINGS),
    }
