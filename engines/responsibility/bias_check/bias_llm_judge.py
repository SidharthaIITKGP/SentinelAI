"""Provider-neutral contract for the optional second-pass LLM bias judge."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from pydantic import ValidationError

from api.schemas import LLMBiasJudgment


class LLMBiasJudge(Protocol):
    def judge(
        self,
        text: str,
        *,
        candidate_dimensions: Sequence[str],
        evidence: Sequence[dict[str, Any]],
    ) -> LLMBiasJudgment | dict[str, Any]: ...


class LLMBiasJudgeError(RuntimeError):
    """Raised when judge execution or structured-output validation fails."""


def run_llm_judge(
    judge: LLMBiasJudge,
    text: str,
    *,
    candidate_dimensions: Sequence[str],
    evidence: Sequence[dict[str, Any]],
) -> LLMBiasJudgment:
    try:
        output = judge.judge(
            text,
            candidate_dimensions=candidate_dimensions,
            evidence=evidence,
        )
    except Exception as exc:
        raise LLMBiasJudgeError("LLM bias judge is unavailable") from exc
    try:
        return LLMBiasJudgment.model_validate(output)
    except (ValidationError, TypeError, ValueError) as exc:
        raise LLMBiasJudgeError("LLM bias judge returned malformed evidence") from exc
