# CITADEL Usage Guide

**Author:** Sardor Razikov  
**Version:** 1.0.0  
**Last Updated:** May 2026

This guide provides comprehensive instructions for using CITADEL, the open AI evaluation infrastructure. CITADEL evaluates Gemma 4 alongside 5 competitor models with provable, tamper-evident audit trails.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Running Individual Layers](#running-individual-layers)
3. [Adding a New Model Adapter](#adding-a-new-model-adapter)
4. [Using the OllamaAdapter for Local Gemma Evaluation](#using-the-ollamaadapter-for-local-gemma-evaluation)
5. [Generating Compliance Reports](#generating-compliance-reports)
6. [Reading Audit Chain JSONL Files](#reading-audit-chain-jsonl-files)
7. [Advanced Usage](#advanced-usage)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

- Python 3.9 or higher
- pip package manager
- (Optional) Ollama for local model inference
- (Optional) AMD MI300X or NVIDIA GPU for accelerated inference

### Installation

```bash
# Clone the repository
git clone https://github.com/SRKRZ23/citadel
cd citadel

# Install dependencies
pip install -r requirements.txt
```

### Your First Evaluation

Run a mock evaluation across all models and suites:

```bash
# Run mock evaluation (no API calls, instant results)
python src/l5_infra/runner.py --mock --suite all --model all

# View results in the dashboard
streamlit run src/l6_dashboard/app.py
```

The dashboard will open at `http://localhost:8501` showing:
- Leaderboard with accuracy, ECE, and composite scores
- Per-model calibration charts
- Efficiency metrics (tokens/second)

### Run a Real Evaluation

```bash
# Evaluate Gemma 4 on ECB v2 benchmark
python src/l5_infra/runner.py --suite ecb_v2 --model gemma4

# Evaluate all models on MMLU-Pro
python src/l5_infra/runner.py --suite mmlu_pro --model all

# Evaluate with custom output directory
python src/l5_infra/runner.py --suite humaneval --model gemma4 --output results/custom_run/
```

Results are saved to `results/` with:
- `{suite}_{model}_{timestamp}.json` — Full evaluation results
- `audit_chain.jsonl` — Tamper-evident audit trail
- `summary.json` — Aggregate metrics

---

## Running Individual Layers

CITADEL's 13 layers (L0–L12) can be tested and used independently.

### L0: Network / TLS Scaffold

```python
from src.l0_network.tls_scaffold import generate_self_signed_cert, healthcheck

# Generate self-signed certificate for mTLS
cert, key = generate_self_signed_cert(
    common_name="citadel.local",
    days_valid=365
)

# Check layer health
status = healthcheck()
print(status)  # {'status': 'ok', 'layer': 'L0_network'}
```

### L1: Hardware Abstraction

```python
from src.l1_hardware.backend import detect_backend, HardwareLayer

# Auto-detect available backend
backend = detect_backend()
print(f"Detected backend: {backend}")  # cuda, rocm, mps, or cpu

# Initialize hardware layer
hw = HardwareLayer()
info = hw.get_backend_info(backend)
print(f"Backend info: {info}")
```

### L2: Task Suites

```python
from src.l2_tasks.task_suite import get_suite

# Load ECB v2 benchmark
ecb = get_suite("ecb_v2")
items = ecb.load()
print(f"Loaded {len(items)} ECB v2 items")

# Inspect first item
item = items[0]
print(f"Prompt: {item.prompt}")
print(f"Expected: {item.expected}")
print(f"Category: {item.category}")

# Load multilingual suite
ml_suite = get_suite("ecb_v2_multilingual")
ml_items = ml_suite.load()
print(f"Languages: {set(item.language for item in ml_items)}")
```

Available suites:
- `ecb_v2` — Epistemic Curie Benchmark v2 (DOI:10.5281/zenodo.19791329)
- `mmlu_pro` — MMLU-Pro (12K questions)
- `humaneval` — HumanEval (164 code problems)
- `ecb_v2_multilingual` — Multilingual ECB v2 (5 languages, 4 domains)

### L3: Model Adapters

```python
from src.l3_adapters.model_registry import get_model, list_models

# List all registered models
models = list_models()
for m in models:
    print(f"{m.model_id}: {m.provider} ({m.context_length} tokens)")

# Get a specific model
gemma = get_model("gemma-4-9b")
print(f"Model: {gemma.model_id}")
print(f"Provider: {gemma.provider}")
print(f"Open source: {gemma.is_open_source}")
```

### L4: Metrics Engine

```python
from src.l4_metrics.metrics import (
    compute_accuracy,
    compute_ece,
    compute_brier_score,
    compute_hallucination_rate,
    compute_refusal_rate
)

# Compute accuracy
corrects = [True, True, False, True, True]
accuracy = compute_accuracy(corrects)
print(f"Accuracy: {accuracy:.2%}")

# Compute ECE (calibration)
confidences = [0.9, 0.8, 0.4, 0.6, 0.95]
ece = compute_ece(confidences, corrects)
print(f"ECE: {ece:.3f}")

# Compute Brier score
brier = compute_brier_score(confidences, corrects)
print(f"Brier score: {brier:.3f}")

# Detect hallucinations
responses = [
    "The capital of France is Paris.",
    "The capital of France is London.",  # hallucination
    "I don't know the capital of France.",
    "The capital of France is Paris, established in 508 CE."
]
hallucination_rate = compute_hallucination_rate(responses)
print(f"Hallucination rate: {hallucination_rate:.2%}")

# Detect refusals
refusal_rate = compute_refusal_rate(responses)
print(f"Refusal rate: {refusal_rate:.2%}")
```

### L5: Eval Infrastructure

```python
from src.l5_infra.runner import EvalRunner, run_mock_suite

# Run mock evaluation (instant, no API calls)
result = run_mock_suite("ecb_v2", "gemma4")
print(f"Accuracy: {result['accuracy']:.2%}")
print(f"ECE: {result['ece']:.3f}")

# Run real evaluation
runner = EvalRunner()
result = runner.run(
    suite="ecb_v2",
    model_id="gemma4",
    output_dir="results/my_run/"
)
```

### L6: Dashboard

```bash
# Launch Streamlit dashboard
streamlit run src/l6_dashboard/app.py

# Or use programmatically
python -c "
from src.l6_dashboard.app import load_results, mock_results

# Load real results
results = load_results('ecb_v2')
print(f'Loaded {len(results)} result files')

# Generate mock results for testing
mock = mock_results('ecb_v2')
print(f'Generated {len(mock)} mock results')
"
```

### L7: Audit Chain

```python
from src.l7_audit.audit_chain import AuditChain
from src.l7_audit.eval_auditor import EvalAuditChain

# Create audit chain
chain = AuditChain()

# Append entries
chain.append({
    "model": "gemma4",
    "suite": "ecb_v2",
    "item_id": "ECB-001",
    "correct": True,
    "latency_ms": 245.3
})

chain.append({
    "model": "gemma4",
    "suite": "ecb_v2",
    "item_id": "ECB-002",
    "correct": False,
    "latency_ms": 312.1
})

# Verify chain integrity
is_valid = chain.verify_chain()
print(f"Chain valid: {is_valid}")

# Get all records
records = chain.records()
for rec in records:
    print(f"Seq {rec.seq}: hash={rec.record_hash[:16]}...")

# Use evaluation-specific audit chain
eval_chain = EvalAuditChain(
    run_id="citadel_20260518_001",
    model_id="gemma4",
    suite="ecb_v2"
)
summary = eval_chain.summary()
print(summary)
```

### L8: Multi-Cloud Arbitrage

```python
from src.l8_multicloud.arbitrage import select_backend, ArbitrageRequest

# Request backend selection
req = ArbitrageRequest(
    model_id="gemma4",
    is_open_source=True,
    max_latency_ms=500.0,
    max_cost_per_1k_tokens=0.01,
    require_compliance=["eu_ai_act", "hipaa"]
)

decision = select_backend(req)
print(f"Selected provider: {decision.provider}")
print(f"Estimated cost: ${decision.estimated_cost_per_1k:.4f}")
print(f"Reason: {decision.reason}")
```

### L9: Federated Evaluation

```python
from src.l9_federated.federated import FederatedCoordinator, FederatedNode

# Coordinator setup
shared_secret = b"citadel_federation_key_2026"
coordinator = FederatedCoordinator(shared_secret=shared_secret)

# Node setup (each organization runs this)
node = FederatedNode(
    org_name="hospital_example",
    shared_secret=shared_secret
)

# Submit local evaluation results (DP-noised)
node.submit_result(
    model_id="gemma4",
    suite="ecb_v2",
    accuracy=0.82,
    n_items=100
)

# Coordinator aggregates (without seeing raw data)
aggregate = coordinator.aggregate_results("gemma4", "ecb_v2")
print(f"Federated accuracy: {aggregate['accuracy']:.2%}")
print(f"Participating orgs: {aggregate['n_contributors']}")
```

### L10: Regulatory Translator

```python
from src.l10_regulatory.translator import (
    generate_report,
    available_frameworks
)

# List available frameworks
frameworks = available_frameworks()
print(f"Supported frameworks: {frameworks}")

# Generate compliance report
metrics = {
    "accuracy": 0.85,
    "ece": 0.054,
    "hallucination_rate": 0.034,
    "refusal_rate": 0.02,
    "audit_chain_verified": True
}

report = generate_report(
    framework="eu_ai_act",
    model_id="gemma4",
    suite="ecb_v2",
    metrics=metrics
)

print(f"Framework: {report.framework}")
print(f"Overall pass: {report.overall_pass}")
print(f"Pass: {report.n_pass}, Fail: {report.n_fail}, N/A: {report.n_na}")

for req in report.requirements:
    print(f"  {req['requirement_id']}: {req['status']}")
    print(f"    {req['description']}")
    print(f"    Value: {req['value']}, Threshold: {req['threshold']}")
```

### L11: Intelligent Router

```python
from src.l11_router.router import route, RoutingRequest

# Route by task type
req = RoutingRequest(
    task_type="code",
    max_cost_per_1k=0.01,
    min_accuracy=0.70
)

decision = route(req)
print(f"Recommended model: {decision.model_id}")
print(f"Reason: {decision.reason}")
print(f"Estimated cost: ${decision.estimated_cost:.4f}")

# Route by compliance requirements
req = RoutingRequest(
    task_type="medical",
    require_compliance=["hipaa", "eu_ai_act"],
    max_latency_ms=1000.0
)

decision = route(req)
print(f"Compliant model: {decision.model_id}")
```

### L12: Model Marketplace

```python
from src.l12_marketplace.marketplace import Marketplace, MarketplaceModel

# Initialize marketplace
mp = Marketplace()

# List available models
models = mp.list_models()
for model in models:
    print(f"{model.model_id}: ${model.price_per_1k_tokens:.4f}")
    print(f"  Domain: {model.domain}")
    print(f"  Creator: {model.creator}")

# Register a new model (70/30 revenue split)
mp.register_model(
    model_id="gemma4-medical-pilot",
    creator="hospital_example",
    domain="medical",
    price_per_1k_tokens=0.005,
    base_model="gemma-4-9b"
)
```

---

## Adding a New Model Adapter

CITADEL uses a standardized `ModelSpec` interface. Here's how to add a new model:

### Step 1: Define Model Specification

```python
# src/l3_adapters/model_registry.py

from dataclasses import dataclass

@dataclass
class ModelSpec:
    model_id: str
    provider: str
    api_endpoint: str
    context_length: int
    is_open_source: bool
    cost_per_1k_tokens: float
```

### Step 2: Create Adapter Class

```python
# src/l3_adapters/my_adapter.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class MyModelResponse:
    model: str
    prompt: str
    response: str
    tokens_generated: int
    latency_ms: float

class MyModelAdapter:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.0
    ) -> MyModelResponse:
        # Implement your API call here
        # Return MyModelResponse with results
        pass
    
    def is_alive(self) -> bool:
        # Check if API is reachable
        pass
```

### Step 3: Register Model

```python
# src/l3_adapters/model_registry.py

MODELS = [
    # ... existing models ...
    ModelSpec(
        model_id="my-model-7b",
        provider="my-provider",
        api_endpoint="https://api.myprovider.com/v1",
        context_length=8192,
        is_open_source=True,
        cost_per_1k_tokens=0.0005
    ),
]
```

### Step 4: Test Your Adapter

```python
# Test script
from src.l3_adapters.my_adapter import MyModelAdapter

adapter = MyModelAdapter(model="my-model-7b", api_key="your-key")

# Test connectivity
assert adapter.is_alive(), "API not reachable"

# Test generation
response = adapter.generate("What is 2+2?")
print(f"Response: {response.response}")
print(f"Latency: {response.latency_ms:.1f}ms")
```

### Step 5: Integrate with Runner

```python
# src/l5_infra/runner.py

def get_adapter(model_id: str):
    if model_id == "my-model-7b":
        from src.l3_adapters.my_adapter import MyModelAdapter
        return MyModelAdapter(model=model_id, api_key=os.getenv("MY_API_KEY"))
    # ... other models ...
```

---

## Using the OllamaAdapter for Local Gemma Evaluation

The OllamaAdapter enables privacy-preserving, on-premises evaluation of Gemma 4 with zero cloud dependency.

### Prerequisites

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
ollama serve

# Pull Gemma 4 model
ollama pull gemma-4:27b
```

### Basic Usage

```python
from src.l3_adapters.ollama_adapter import OllamaAdapter, smoke_test

# Check if Ollama is ready
if smoke_test("gemma-4:27b"):
    print("Ollama ready with Gemma 4")
else:
    print("Ollama not available or model not pulled")
    exit(1)

# Initialize adapter
adapter = OllamaAdapter(
    model="gemma-4:27b",
    base_url="http://localhost:11434",
    temperature=0.0,  # Deterministic for benchmarks
    seed=42
)

# Single generation
result = adapter.generate(
    prompt="What is the boiling point of water at sea level?",
    max_tokens=200
)

print(f"Response: {result.response}")
print(f"Speed: {result.tokens_per_second:.1f} tok/s")
print(f"Latency: {result.total_duration_ms:.1f}ms")
```

### Batch Evaluation

```python
# Batch generation (sequential for audit chain ordering)
prompts = [
    "What is 2+2?",
    "Explain photosynthesis in one sentence.",
    "What is the capital of France?"
]

results = adapter.batch_generate(prompts, max_tokens=100)

for i, result in enumerate(results):
    print(f"\nPrompt {i+1}: {prompts[i]}")
    print(f"Response: {result.response}")
    print(f"Speed: {result.tokens_per_second:.1f} tok/s")
```

### Full ECB v2 Evaluation

```python
from src.l3_adapters.ollama_adapter import OllamaAdapter
from src.l2_tasks.task_suite import get_suite
from src.l7_audit.audit_chain import AuditChain
import hashlib
import json

# Initialize
adapter = OllamaAdapter(model="gemma-4:27b")
suite = get_suite("ecb_v2")
items = suite.load()
chain = AuditChain()

# Evaluate
results = []
for item in items:
    response = adapter.generate(item.prompt, max_tokens=200)
    
    # Check correctness (simplified)
    correct = item.expected.lower() in response.response.lower()
    
    # Add to audit chain
    chain.append({
        "model": "gemma-4:27b",
        "suite": "ecb_v2",
        "item_id": item.item_id,
        "correct": correct,
        "latency_ms": response.total_duration_ms,
        "response_hash": hashlib.sha256(response.response.encode()).hexdigest()
    })
    
    results.append({
        "item_id": item.item_id,
        "correct": correct,
        "response": response.response
    })

# Verify audit chain
assert chain.verify_chain(), "Audit chain verification failed"

# Compute metrics
accuracy = sum(r["correct"] for r in results) / len(results)
print(f"Accuracy: {accuracy:.2%}")
print(f"Audit chain: {len(chain.records())} entries, verified ✓")
```

### Remote Ollama Instance

```python
# Connect to Ollama on a different machine
adapter = OllamaAdapter(
    model="gemma-4:27b",
    base_url="http://192.168.1.100:11434",
    timeout_seconds=300.0
)

# Check connectivity
if adapter.is_alive():
    models = adapter.list_local_models()
    print(f"Available models: {models}")
```

### Environment Variables

```bash
# Override default Ollama URL
export OLLAMA_BASE_URL=http://my-server:11434

# Run evaluation
python src/l5_infra/runner.py --suite ecb_v2 --model gemma4 --adapter ollama
```

---

## Generating Compliance Reports

CITADEL auto-generates compliance reports for 6 regulatory frameworks.

### Supported Frameworks

1. **EU AI Act** — Articles 9, 12, 13, 15, 17
2. **NIST AI RMF** — GOVERN, MAP, MEASURE, MANAGE
3. **ISO/IEC 42001:2023** — AI management system
4. **HIPAA §164.312(b)** — Audit controls for healthcare AI
5. **PCI-DSS 10.x** — Logging requirements for payment AI
6. **UK AISI** — AI Safety Institute evaluation criteria

### Generate Single Report

```python
from src.l10_regulatory.translator import generate_report

# Evaluation metrics
metrics = {
    "accuracy": 0.858,
    "ece": 0.054,
    "hallucination_rate": 0.034,
    "refusal_rate": 0.023,
    "audit_chain_verified": True,
    "per_language_accuracy_variance": 0.08
}

# Generate EU AI Act report
report = generate_report(
    framework="eu_ai_act",
    model_id="gemma4",
    suite="ecb_v2",
    metrics=metrics
)

# Print summary
print(f"Framework: {report.framework}")
print(f"Model: {report.model_id}")
print(f"Suite: {report.suite}")
print(f"Generated: {report.generated_at}")
print(f"\nOverall: {'PASS' if report.overall_pass else 'FAIL'}")
print(f"Pass: {report.n_pass}, Fail: {report.n_fail}, N/A: {report.n_na}")

# Print detailed requirements
print("\nRequirements:")
for req in report.requirements:
    status_icon = "✓" if req["status"] == "PASS" else "✗" if req["status"] == "FAIL" else "○"
    print(f"{status_icon} {req['requirement_id']}: {req['status']}")
    print(f"  {req['description']}")
    print(f"  Metric: {req['metric']} = {req['value']}")
    if req['threshold'] is not None:
        print(f"  Threshold: {req['threshold']}")
    print()
```

### Generate All Reports

```python
from src.l10_regulatory.translator import available_frameworks, generate_report

frameworks = available_frameworks()
reports = {}

for framework in frameworks:
    report = generate_report(
        framework=framework,
        model_id="gemma4",
        suite="ecb_v2",
        metrics=metrics
    )
    reports[framework] = report
    print(f"{framework}: {'PASS' if report.overall_pass else 'FAIL'}")

# Save reports
import json
from pathlib import Path

output_dir = Path("results/compliance_reports/")
output_dir.mkdir(parents=True, exist_ok=True)

for framework, report in reports.items():
    output_file = output_dir / f"{framework}_gemma4_ecb_v2.json"
    output_file.write_text(json.dumps({
        "framework": report.framework,
        "model_id": report.model_id,
        "suite": report.suite,
        "generated_at": report.generated_at,
        "overall_pass": report.overall_pass,
        "n_pass": report.n_pass,
        "n_fail": report.n_fail,
        "n_na": report.n_na,
        "requirements": report.requirements
    }, indent=2))
    print(f"Saved: {output_file}")
```

### Custom Thresholds

```python
# Override default thresholds for stricter compliance
from src.l10_regulatory.translator import REGULATORY_MAPPINGS

# Find and modify EU AI Act accuracy requirement
for req in REGULATORY_MAPPINGS:
    if req.framework == "eu_ai_act" and req.requirement_id == "Art.9(1)":
        req.threshold = 0.90  # Increase from 0.80 to 0.90

# Generate report with custom thresholds
report = generate_report("eu_ai_act", "gemma4", "ecb_v2", metrics)
```

---

## Reading Audit Chain JSONL Files

Audit chains are stored in JSONL (JSON Lines) format for efficient streaming and verification.

### File Format

Each line is a JSON object representing one audit entry:

```json
{"prompt_id": "ecb_real_001", "domain": "physics", "prompt": "...", "response": "...", "response_hash": "0def98d7...", "tokens_per_second": 73.04, "wall_clock_seconds": 6.61, "prev_hash": "0000000000...", "entry_hash": "7f37aa54..."}
```

### Read Audit Chain

```python
import json
from pathlib import Path

# Read JSONL file
audit_file = Path("results/gemma4_real_run/audit_chain.jsonl")
entries = []

with audit_file.open("r") as f:
    for line in f:
        entry = json.loads(line)
        entries.append(entry)

print(f"Loaded {len(entries)} audit entries")

# Inspect first entry
first = entries[0]
print(f"Prompt ID: {first['prompt_id']}")
print(f"Domain: {first['domain']}")
print(f"Response hash: {first['response_hash'][:16]}...")
print(f"Speed: {first['tokens_per_second']:.1f} tok/s")
```

### Verify Chain Integrity

```python
import hashlib

def verify_audit_chain(entries):
    """Verify SHA-256 hash chain integrity."""
    GENESIS = "0" * 64
    prev_hash = GENESIS
    
    for i, entry in enumerate(entries):
        # Check prev_hash matches
        if entry["prev_hash"] != prev_hash:
            print(f"❌ Chain broken at entry {i}")
            print(f"   Expected prev_hash: {prev_hash[:16]}...")
            print(f"   Got: {entry['prev_hash'][:16]}...")
            return False
        
        # Recompute entry hash
        payload = json.dumps({
            "seq": i,
            "prompt_id": entry["prompt_id"],
            "domain": entry["domain"],
            "model": entry.get("model", "unknown"),
            "response_hash": entry["response_hash"],
            "prev_hash": entry["prev_hash"],
            "tokens_per_second": entry["tokens_per_second"]
        }, sort_keys=True)
        
        computed_hash = hashlib.sha256(payload.encode()).hexdigest()
        
        if computed_hash != entry["entry_hash"]:
            print(f"❌ Hash mismatch at entry {i}")
            return False
        
        prev_hash = entry["entry_hash"]
    
    print(f"✓ Chain verified: {len(entries)} entries")
    return True

# Verify
verify_audit_chain(entries)
```

### Extract Statistics

```python
import statistics

# Compute statistics from audit chain
speeds = [e["tokens_per_second"] for e in entries]
latencies = [e["wall_clock_seconds"] for e in entries]

print(f"Performance Statistics:")
print(f"  Mean speed: {statistics.mean(speeds):.1f} tok/s")
print(f"  Median speed: {statistics.median(speeds):.1f} tok/s")
print(f"  Std dev: {statistics.stdev(speeds):.1f} tok/s")
print(f"  Total time: {sum(latencies):.1f}s")

# Group by domain
from collections import defaultdict
by_domain = defaultdict(list)
for e in entries:
    by_domain[e["domain"]].append(e["tokens_per_second"])

print(f"\nSpeed by domain:")
for domain, speeds in sorted(by_domain.items()):
    print(f"  {domain:12s}: {statistics.mean(speeds):6.1f} tok/s")
```

### Stream Large Files

```python
def stream_audit_chain(filepath, chunk_size=1000):
    """Stream large audit chains without loading into memory."""
    with open(filepath, "r") as f:
        chunk = []
        for line in f:
            entry = json.loads(line)
            chunk.append(entry)
            
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        
        if chunk:
            yield chunk

# Process in chunks
for chunk in stream_audit_chain("results/large_audit_chain.jsonl"):
    # Process chunk
    speeds = [e["tokens_per_second"] for e in chunk]
    print(f"Chunk: {len(chunk)} entries, mean speed: {statistics.mean(speeds):.1f} tok/s")
```

---

## Advanced Usage

### Custom Benchmark Suite

```python
from src.l2_tasks.task_suite import TaskSuite, TaskItem

class MyCustomSuite(TaskSuite):
    def load(self) -> list[TaskItem]:
        return [
            TaskItem(
                item_id="CUSTOM-001",
                prompt="What is the capital of ?",
                expected="",
                category="geography"
            ),
            TaskItem(
                item_id="CUSTOM-002",
                prompt="What is 15 * 23?",
                expected="345",
                category="math"
            ),
            # Add more items...
        ]

# Use custom suite
suite = MyCustomSuite()
items = suite.load()
```

### Parallel Evaluation

```python
from concurrent.futures import ThreadPoolExecutor
from src.l3_adapters.ollama_adapter import OllamaAdapter

adapter = OllamaAdapter(model="gemma-4:27b")
prompts = ["prompt1", "prompt2", "prompt3"]

def evaluate_one(prompt):
    return adapter.generate(prompt)

# Parallel execution (note: breaks audit chain ordering)
with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(evaluate_one, prompts))
```

### Export to CSV

```python
import csv
from pathlib import Path

# Export audit chain to CSV
audit_file = Path("results/gemma4_real_run/audit_chain.jsonl")
csv_file = Path("results/gemma4_real_run/audit_chain.csv")

with audit_file.open("r") as f_in, csv_file.open("w", newline="") as f_out:
    entries = [json.loads(line) for line in f_in]
    
    if entries:
        writer = csv.DictWriter(f_out, fieldnames=entries[0].keys())
        writer.writeheader()
        writer.writerows(entries)

print(f"Exported to {csv_file}")
```

---

## Troubleshooting

### Ollama Connection Issues

```python
# Check if Ollama is running
from src.l3_adapters.ollama_adapter import OllamaAdapter

adapter = OllamaAdapter()
if not adapter.is_alive():
    print("Ollama not reachable. Start with: ollama serve")
else:
    print("Ollama is running")
    models = adapter.list_local_models()
    print(f"Available models: {models}")
```

### Missing Dependencies

```bash
# Reinstall all dependencies
pip install -r requirements.txt --force-reinstall

# Install specific missing package
pip install pynacl  # For Ed25519 signatures
pip install streamlit  # For dashboard
```

### Audit Chain Verification Fails

```python
# Debug audit chain
from src.l7_audit.audit_chain import AuditChain

chain = AuditChain()
chain.load("results/audit_chain.jsonl")

# Check each record
for i, rec in enumerate(chain.records()):
    is_valid = rec.verify(chain.verify_key)
    if not is_valid:
        print(f"Record {i} failed verification")
        print(f"  Entry: {rec.entry}")
        print(f"  Prev hash: {rec.prev_hash[:16]}...")
```

### Performance Issues

```bash
# Use GPU acceleration
export CUDA_VISIBLE_DEVICES=0  # NVIDIA
export HIP_VISIBLE_DEVICES=0   # AMD

# Reduce batch size
python src/l5_infra/runner.py --suite ecb_v2 --model gemma4 --batch-size 1

# Use smaller model
ollama pull gemma-4:9b  # Instead of 27b
```

---

## Additional Resources

- **GitHub Repository:** https://github.com/SRKRZ23/citadel
- **ECB v2 DOI:** https://doi.org/10.5281/zenodo.19791329
- **Test Suite:** Run `python src/test_citadel.py` for 76/76 passing tests
- **Reproducibility Guide:** See `docs/REPRODUCIBILITY.md`
- **Compliance Guide:** See `docs/COMPLIANCE_FRAMEWORKS.md`

---

**Author:** Sardor Razikov · razikovsardor1@gmail.com · 

**Trademark Attribution:** Gemma is a trademark of Google LLC. CITADEL evaluates Gemma 4 alongside other frontier models; this project is not affiliated with or endorsed by Google.

**License:** MIT — All code, benchmarks, and results are open source.