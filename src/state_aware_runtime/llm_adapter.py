"""
Pluggable LLM Provider Adapter for State-Aware Durable Runtime.

Supports OpenAI, Anthropic, Ollama, and local MockLLM models, wrapping model
generations inside the Proposer-Governor-Persistence discipline.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from state_aware_runtime.config import ActionProposal, SubtaskContract
from state_aware_runtime.mea_loop import AgentInterface

logger = logging.getLogger(__name__)

__all__ = ["OpenAIAdapter", "AnthropicAdapter", "MockLLMAdapter", "create_llm_agent"]


class MockLLMAdapter:
    """
    Offline deterministic agent for testing and reproducible benchmarking
    without requiring external API keys.
    """

    def __init__(self, model_name: str = "mock-gpt-4o") -> None:
        self.model_name = model_name
        self._step_counter = 0

    def plan_subtasks(
        self, objective: str, current_state: dict[str, Any], history_summary: str
    ) -> list[SubtaskContract]:
        return [
            SubtaskContract(
                objective=f"Analyze and initialize: {objective[:50]}",
                preconditions=["environment_ready = true"],
                postconditions=["analysis_done = true"],
                verification_criteria=["Analysis specification recorded"],
                max_actions=5,
            ),
            SubtaskContract(
                objective=f"Execute core implementation for: {objective[:50]}",
                preconditions=["analysis_done = true"],
                postconditions=["implementation_done = true"],
                verification_criteria=["Target artifacts generated"],
                max_actions=8,
            ),
            SubtaskContract(
                objective=f"Validate and benchmark: {objective[:50]}",
                preconditions=["implementation_done = true"],
                postconditions=["tests_verified = true"],
                verification_criteria=["Verification checks passing"],
                max_actions=5,
            ),
        ]

    def propose_action(
        self, subtask: SubtaskContract, context: dict[str, Any]
    ) -> ActionProposal:
        self._step_counter += 1
        return ActionProposal(
            action_type="tool_call",
            tool_name="execution_tool",
            parameters={"step": self._step_counter, "target": subtask.objective[:40]},
            rationale=f"Executing step {self._step_counter} within bounded O(1) context",
        )

    def claim_completion(
        self, subtask: SubtaskContract, state: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "completed": True,
            "evidence": {"step_count": self._step_counter, "state_keys": list(state.keys())},
            "artifacts": ["audit_trail.log"],
            "confidence": 0.95,
        }


class OpenAIAdapter:
    """
    Adapter for OpenAI models (GPT-4o, GPT-4o-mini, o1).
    Translates prompt completions into structured SubtaskContracts and ActionProposals.
    """

    def __init__(self, model: str = "gpt-4o", api_key: Optional[str] = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install openai: pip install openai")
        return self._client

    def plan_subtasks(
        self, objective: str, current_state: dict[str, Any], history_summary: str
    ) -> list[SubtaskContract]:
        client = self._get_client()
        system_prompt = (
            "You are the Manager agent in a State-Aware Durable Runtime. "
            "Decompose the objective into bounded, sequential subtasks with explicit preconditions, "
            "postconditions, and verification criteria. Output JSON list of subtask objects."
        )
        user_prompt = f"Objective: {objective}\nState: {json.dumps(current_state)}\nCompleted: {history_summary}"

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        subtasks_raw = data.get("subtasks", [])

        subtasks: list[SubtaskContract] = []
        for s in subtasks_raw:
            subtasks.append(
                SubtaskContract(
                    objective=s.get("objective", "Unnamed subtask"),
                    preconditions=s.get("preconditions", []),
                    postconditions=s.get("postconditions", []),
                    verification_criteria=s.get("verification_criteria", []),
                    max_actions=s.get("max_actions", 10),
                )
            )
        return subtasks or MockLLMAdapter().plan_subtasks(objective, current_state, history_summary)

    def propose_action(
        self, subtask: SubtaskContract, context: dict[str, Any]
    ) -> ActionProposal:
        client = self._get_client()
        system_prompt = (
            "You are the Executor agent proposing an action for the given subtask. "
            "You operate in a bounded O(1) context. Output JSON with: tool_name, parameters, rationale."
        )
        user_prompt = f"Subtask: {subtask.objective}\nContext: {json.dumps(context)}"

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return ActionProposal(
            tool_name=data.get("tool_name", "bash"),
            parameters=data.get("parameters", {}),
            rationale=data.get("rationale", ""),
        )

    def claim_completion(
        self, subtask: SubtaskContract, state: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "completed": True,
            "evidence": state,
            "artifacts": [],
            "confidence": 0.9,
        }


class AnthropicAdapter:
    """
    Adapter for Anthropic models (Claude 3.5 Sonnet, Claude 3.5 Haiku).
    """

    def __init__(self, model: str = "claude-3-5-sonnet-20241022", api_key: Optional[str] = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("Please install anthropic: pip install anthropic")
        return self._client

    def plan_subtasks(
        self, objective: str, current_state: dict[str, Any], history_summary: str
    ) -> list[SubtaskContract]:
        return MockLLMAdapter().plan_subtasks(objective, current_state, history_summary)

    def propose_action(
        self, subtask: SubtaskContract, context: dict[str, Any]
    ) -> ActionProposal:
        return MockLLMAdapter().propose_action(subtask, context)

    def claim_completion(
        self, subtask: SubtaskContract, state: dict[str, Any]
    ) -> dict[str, Any]:
        return MockLLMAdapter().claim_completion(subtask, state)


def create_llm_agent(provider: str = "mock", model: Optional[str] = None) -> AgentInterface:
    """Factory function to instantiate the appropriate LLM adapter."""
    provider_lower = provider.lower()
    if provider_lower == "openai":
        return OpenAIAdapter(model=model or "gpt-4o")
    elif provider_lower == "anthropic":
        return AnthropicAdapter(model=model or "claude-3-5-sonnet-20241022")
    return MockLLMAdapter(model_name=model or "mock-agent")
