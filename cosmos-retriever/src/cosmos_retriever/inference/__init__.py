"""Inference-model adapters that drive the agent loop."""

from __future__ import annotations

from cosmos_retriever.inference.base import (
    AgentInferenceModel,
    InferenceContext,
)
from cosmos_retriever.inference.vllm import VLLMHarmonyInferenceModel

__all__ = [
    "AgentInferenceModel",
    "InferenceContext",
    "VLLMHarmonyInferenceModel",
]
