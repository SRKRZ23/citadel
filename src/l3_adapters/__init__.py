"""L3: Model Adapters — Gemma 4, Llama 4, Claude, GPT, Qwen3-35B, Mistral.

Includes the local-first OllamaAdapter for on-premises Gemma 4 evaluation
(Special Technology Track: Ollama).
"""

from .ollama_adapter import OllamaAdapter, OllamaResponse, smoke_test

__all__ = ["OllamaAdapter", "OllamaResponse", "smoke_test"]
