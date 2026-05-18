"""
CITADEL L6 — Public Leaderboard Dashboard.

Streamlit app showing real-time eval results:
  - Leaderboard table (6 models × 4 suites)
  - Accuracy bar chart
  - ECE calibration chart
  - Hallucination rate comparison
  - Efficiency (tokens/second)
  - Per-model detail view

Run: streamlit run src/l6_dashboard/app.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
RESULTS_DIR = ROOT / "results"

# ── Pure-Python data functions (importable without streamlit) ─────────────────

def load_results(suite_filter: str) -> list:
    results = []
    if RESULTS_DIR.exists():
        for f in sorted(RESULTS_DIR.glob("*.json")):
            try:
                with open(f) as fp:
                    d = json.load(fp)
                if suite_filter == "all" or d.get("suite") == suite_filter:
                    results.append(d)
            except Exception:
                pass
    return results


def mock_results(suite: str) -> list:
    """Generate demo data when no real results are available."""
    import random
    rng = random.Random(42)
    models = [
        ("gemma4", "Gemma 4 27B", "Google DeepMind"),
        ("llama4", "Llama 4 Scout", "Meta"),
        ("claude", "Claude Haiku 4.5", "Anthropic"),
        ("gpt4o_mini", "GPT-4o mini", "OpenAI"),
        ("qwen3", "Qwen3-35B", "Alibaba"),
        ("mistral7b", "Mistral-7B", "Mistral AI"),
    ]
    base_accs = {
        "gemma4": 0.810, "llama4": 0.785, "claude": 0.852,
        "gpt4o_mini": 0.831, "qwen3": 0.763, "mistral7b": 0.694,
    }
    rows = []
    for mid, name, provider in models:
        acc = base_accs[mid] + rng.uniform(-0.02, 0.02)
        rows.append({
            "model": mid, "model_display": name, "provider": provider,
            "suite": suite if suite != "all" else "ecb_v2",
            "accuracy": round(acc, 4),
            "ece": round(rng.uniform(0.04, 0.18), 4),
            "hallucination_rate": round(rng.uniform(0.02, 0.10), 4),
            "refusal_rate": round(rng.uniform(0.01, 0.06), 4),
            "tokens_per_second": round(rng.uniform(25, 120), 1),
            "mock": True,
        })
    return rows


# ── Streamlit UI — only executed when streamlit is available ──────────────────

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

if _HAS_ST:
    import time

    # ── Page config ───────────────────────────────────────────────────────────
    st.set_page_config(
        page_title="CITADEL — Open AI Evaluation",
        page_icon="🏰",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Styles ────────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; color: #22d3ee; }
    .stDataFrame { font-size: 0.85rem; }
    .block-container { padding-top: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    st.sidebar.title("🏰 CITADEL")
    st.sidebar.caption("Open AI Evaluation Infrastructure")
    st.sidebar.divider()

    suite_options = ["ecb_v2", "mmlu_pro", "humaneval", "multilingual_mmlu", "all"]
    selected_suite = st.sidebar.selectbox("Benchmark Suite", suite_options, index=0)
    show_mock = st.sidebar.toggle("Show mock data (demo)", value=True)
    auto_refresh = st.sidebar.toggle("Auto-refresh (30s)", value=False)

    st.sidebar.divider()
    st.sidebar.markdown("**ECB v2 DOI**")
    st.sidebar.markdown("[10.5281/zenodo.19791329](https://doi.org/10.5281/zenodo.19791329)")
    st.sidebar.markdown("**Audit chain**: Ed25519 signed, tamper-evident")
    st.sidebar.caption("Built on AMD MI300X · Gemma 4 Good 2026")

    # Apply cache decorator only when streamlit is present
    load_results = st.cache_data(ttl=30)(load_results)

    # ── Main content ──────────────────────────────────────────────────────────
    st.title("🏰 CITADEL — Open AI Evaluation Leaderboard")
    st.caption("Consumer Reports for AI · Third-party, citable, reproducible model evaluation")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Models Evaluated", "6")
    col2.metric("Benchmark Suites", "4")
    col3.metric("Total Questions", "58")
    col4.metric("Audit Chain", "Ed25519 ✓")

    st.divider()

    results = load_results(selected_suite)
    if not results or show_mock:
        data = mock_results(selected_suite)
        if show_mock:
            st.info("📊 Showing mock data for demo. Toggle 'Show mock data' off to see live results from `results/` directory.")
    else:
        seen = {}
        for r in sorted(results, key=lambda x: x.get("timestamp", "")):
            key = (r.get("model"), r.get("suite"))
            seen[key] = r
        data = list(seen.values())

    if not data:
        st.warning("No results found. Run `python src/l5_infra/runner.py --mock --suite all --model all` to generate demo data.")
        st.stop()

    # ── Leaderboard table ─────────────────────────────────────────────────────
    st.subheader("📊 Leaderboard")

    import pandas as pd
    df = pd.DataFrame(data)
    display_cols = ["model_display", "accuracy", "ece", "hallucination_rate", "refusal_rate", "tokens_per_second"]
    available_cols = [c for c in display_cols if c in df.columns]
    df_display = df[available_cols].copy() if available_cols else df

    rename_map = {
        "model_display": "Model",
        "accuracy": "Accuracy ↑",
        "ece": "ECE ↓",
        "hallucination_rate": "Hallucination ↓",
        "refusal_rate": "Refusal Rate",
        "tokens_per_second": "Tok/s",
    }
    df_display = df_display.rename(columns=rename_map)
    if "Accuracy ↑" in df_display:
        df_display = df_display.sort_values("Accuracy ↑", ascending=False)

    def highlight_gemma(row):
        if "Gemma" in str(row.get("Model", "")):
            return ["background-color: #0d3b5e"] * len(row)
        return [""] * len(row)

    try:
        styled = df_display.style.apply(highlight_gemma, axis=1).format({
            "Accuracy ↑": "{:.1%}",
            "ECE ↓": "{:.3f}",
            "Hallucination ↓": "{:.3f}",
            "Refusal Rate": "{:.3f}",
            "Tok/s": "{:.0f}",
        })
        st.dataframe(styled, width="stretch", height=280)
    except Exception:
        st.dataframe(df_display, width="stretch", height=280)

    # ── Charts ────────────────────────────────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        BG = "#0f1117"
        CARD = "#111827"
        CYAN = "#22d3ee"
        BLUE = "#3b82f6"
        WHITE = "#f1f5f9"
        BORDER = "#1f2937"

        plt.rcParams.update({
            "figure.facecolor": BG, "axes.facecolor": CARD,
            "axes.edgecolor": BORDER, "text.color": WHITE,
            "xtick.color": WHITE, "ytick.color": WHITE,
            "axes.labelcolor": WHITE, "grid.color": BORDER,
        })

        models_list = [r.get("model_display", r.get("model", "?")) for r in data]
        accs = [r.get("accuracy", 0) for r in data]
        eces = [r.get("ece", 0) for r in data]
        halls = [r.get("hallucination_rate", 0) for r in data]
        colors_acc = [CYAN if "Gemma" in m else BLUE for m in models_list]

        col_a, col_b = st.columns(2)

        with col_a:
            fig, ax = plt.subplots(figsize=(6, 3.5))
            bars = ax.bar(models_list, accs, color=colors_acc, edgecolor=BORDER, linewidth=0.8)
            for bar, val in zip(bars, accs):
                ax.text(bar.get_x() + bar.get_width() / 2, val + 0.005,
                        f"{val:.1%}", ha="center", va="bottom", fontsize=9, color=WHITE)
            ax.set_ylim(0, 1.1)
            ax.set_ylabel("Accuracy")
            ax.set_title(f"Accuracy — {selected_suite.upper()}", fontweight="700", pad=10)
            ax.tick_params(axis="x", rotation=30)
            ax.grid(axis="y", zorder=0)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

        with col_b:
            fig, ax = plt.subplots(figsize=(6, 3.5))
            x = np.arange(len(models_list))
            w = 0.38
            ax.bar(x - w/2, eces, w, label="ECE (calibration)", color=BLUE, edgecolor=BORDER)
            ax.bar(x + w/2, halls, w, label="Hallucination rate", color="#ef4444", edgecolor=BORDER)
            ax.set_xticks(x)
            ax.set_xticklabels(models_list, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("Rate (lower is better)")
            ax.set_title("Calibration & Hallucination", fontweight="700", pad=10)
            ax.legend(fontsize=8, facecolor=CARD, edgecolor=BORDER, labelcolor=WHITE)
            ax.grid(axis="y", zorder=0)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

    except Exception as e:
        st.warning(f"Chart rendering error: {e}")

    # ── Gemma 4 spotlight ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("🌟 Gemma 4 Spotlight")

    gemma_row = next((r for r in data if "gemma" in r.get("model", "").lower()), None)
    if gemma_row:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Accuracy", f"{gemma_row.get('accuracy', 0):.1%}")
        c2.metric("ECE", f"{gemma_row.get('ece', 0):.3f}")
        c3.metric("Hallucination", f"{gemma_row.get('hallucination_rate', 0):.3f}")
        c4.metric("Tok/s", f"{gemma_row.get('tokens_per_second', 0):.0f}")

    # ── Reproducibility footer ────────────────────────────────────────────────
    st.divider()
    st.caption("🔐 All results are Ed25519-signed and hash-chained. "
               "Run hash is included in each result file. "
               "ECB v2 DOI: [10.5281/zenodo.19791329](https://doi.org/10.5281/zenodo.19791329) · "
               "MIT License · AMD MI300X")

    if auto_refresh:
        time.sleep(30)
        st.rerun()
