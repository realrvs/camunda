"""
Контракт между AI-агентом и Tool Executor.

AI-агент НЕ вызывает бизнес-воркеры напрямую. Он формирует
RecommendationDTO — формальную рекомендацию, которая проходит
проверку в Tool Executor перед исполнением.

Это реализация принципа "наименьших привилегий" (Least Privilege)
из раздела 4.1 Enterprise Agent Orchestration Blueprint.
"""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class ToolName(str, Enum):
    """Allow-list инструментов, которые агент может рекомендовать."""
    SEND_NOTIFICATION = "send-notification"
    ARCHIVE_DOCUMENTS = "archive-documents"


class RecommendationDTO(BaseModel):
    """
    Формальная рекомендация от AI-агента.

    Агент НЕ выполняет действие — он только рекомендует.
    Tool Executor решает, можно ли эту рекомендацию исполнить.
    """

    tool_name: ToolName = Field(
        ...,
        description="Имя инструмента из allow-list",
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Уверенность агента в рекомендации (0.0 - 1.0)",
    )

    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Обоснование рекомендации (для аудита)",
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Параметры для целевого воркера",
    )

    agent_svid: str = Field(
        ...,
        description="SPIFFE ID агента (идентичность для RBAC)",
    )

    @field_validator("agent_svid")
    @classmethod
    def validate_svid_format(cls, v: str) -> str:
        """Проверяет формат SPIFFE ID: spiffe://<trust-domain>/<path>."""
        if not v.startswith("spiffe://"):
            raise ValueError("agent_svid must start with 'spiffe://'")
        if len(v) < 15:
            raise ValueError("agent_svid is too short to be valid")
        return v


# ─── Матрица политик (пороги из плана митигации) ──────────────────

CONFIDENCE_THRESHOLD = 0.85
"""Минимальная уверенность для автономного исполнения."""

ALLOWED_SVIDS = {
    "spiffe://test.ru/agents/procurement_agent_v1",
}
"""White-list SVID'ов, имеющих право вызывать Tool Executor."""


if __name__ == "__main__":
    # Демонстрация: валидный DTO
    valid = RecommendationDTO(
        tool_name="send-notification",
        confidence=0.92,
        reasoning="Заявка одобрена пользователем, требуется уведомление",
        parameters={"recipient": "ivanov@test.ru"},
        agent_svid="spiffe://test.ru/agents/procurement_agent_v1",
    )
    print("✅ Valid DTO:")
    print(valid.model_dump_json(indent=2))

    # Демонстрация: невалидный DTO (confidence > 1.0)
    try:
        RecommendationDTO(
            tool_name="send-notification",
            confidence=1.5,
            reasoning="Test invalid confidence",
            agent_svid="spiffe://test.ru/agents/procurement_agent_v1",
        )
    except Exception as e:
        print("\n❌ Invalid DTO rejected:")
        print(e)

    # Демонстрация: невалидный DTO (tool_name вне allow-list)
    try:
        RecommendationDTO(
            tool_name="delete-everything",  # type: ignore
            confidence=0.9,
            reasoning="Test invalid tool",
            agent_svid="spiffe://test.ru/agents/procurement_agent_v1",
        )
    except Exception as e:
        print("\n❌ Invalid tool_name rejected:")
        print(e)
