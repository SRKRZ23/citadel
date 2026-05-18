"""L3: Model Adapters — Gemma 4, Llama 4, Claude, GPT, Qwen3-35B, Mistral.

Includes local-first adapters for edge/mobile Gemma 4 evaluation:
- OllamaAdapter: on-premises evaluation (Special Technology Track: Ollama)
- CactusAdapter: mobile/wearable evaluation (Special Technology Track: Cactus)
- LiteRTAdapter: edge devices with Google AI Edge LiteRT (Special Technology Track: LiteRT)
"""

from .ollama_adapter import OllamaAdapter, OllamaResponse, smoke_test as ollama_smoke_test
from .cactus_adapter import CactusAdapter, CactusResponse, smoke_test as cactus_smoke_test
from .litert_adapter import LiteRTAdapter, LiteRTResponse, smoke_test as litert_smoke_test

__all__ = [
    "OllamaAdapter", "OllamaResponse", "ollama_smoke_test",
    "CactusAdapter", "CactusResponse", "cactus_smoke_test",
    "LiteRTAdapter", "LiteRTResponse", "litert_smoke_test",
]
