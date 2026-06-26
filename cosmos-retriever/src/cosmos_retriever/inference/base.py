"""Inference-model abstraction used by the agent loop."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from cosmos_retriever.tools import ToolSet
from cosmos_retriever.trajectory import Action, Trajectory


@dataclass
class InferenceContext:
    """Inputs to one model call."""

    trajectory: Trajectory
    toolset: ToolSet
    max_tokens: int | None = None


class AgentInferenceModel(ABC):
    """Translate an :class:`InferenceContext` into the next :class:`Action`."""

    @abstractmethod
    def __call__(self, context: InferenceContext) -> Action | None:
        """Sample the next action from the model. Return ``None`` to stop."""


__all__ = ["AgentInferenceModel", "InferenceContext"]
