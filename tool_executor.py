"""
Tool Executor — единственная точка входа для рекомендаций AI-агента.

Реализация паттерна Proxy/Gateway: агент физически не имеет доступа
к бизнес-воркерам (send-notification, archive-documents). Он может
только сформировать RecommendationDTO, который проходит проверку
здесь. Это реализация раздела 4.1 (политики агентов) и раздела 4.2
(WIMSE-идентичность) из Enterprise Agent Orchestration Blueprint.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from pyzeebe import ZeebeWorker, Job, create_camunda_cloud_channel

from tool_contract import (
    RecommendationDTO,
    ToolName,
    CONFIDENCE_THRESHOLD,
    ALLOWED_SVIDS,
)


# ─── Audit log (append-only, как в blueprint 4.3.1) ───────────────

AUDIT_LOG: list[dict[str, Any]] = []


def audit(event: str, **fields: Any) -> None:
    """Пишет событие в append-only audit log."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    AUDIT_LOG.append(record)
    # В реальном проекте — запись в PostgreSQL с hash-цепочкой.
    # Для пет-проекта достаточно print, чтобы видеть в терминале.
    print(f"[AUDIT] {json.dumps(record, ensure_ascii=False)}")


# ─── Политики (Policy Enforcement Point) ──────────────────────────

class PolicyDecision:
    """Результат проверки рекомендации агентом."""

    def __init__(self, allowed: bool, reason: str) -> None:
        self.allowed = allowed
        self.reason = reason

    def __repr__(self) -> str:
        verdict = "ALLOW" if self.allowed else "DENY"
        return f"PolicyDecision({verdict}, reason={self.reason!r})"


def evaluate_policy(dto: RecommendationDTO) -> PolicyDecision:
    """
    Точка контроля политик. Возвращает ALLOW или DENY с обоснованием.

    Порядок проверок (fail-fast, от самого критичного):
      1. SVID агента — есть ли у него право обращаться к Tool Executor?
      2. Confidence — достаточно ли уверен агент для автономного действия?
      3. Tool name — разрешён ли запрошенный инструмент?
    """
    # 1. RBAC: проверка идентичности агента
    if dto.agent_svid not in ALLOWED_SVIDS:
        return PolicyDecision(
            allowed=False,
            reason=f"SVID not in allow-list: {dto.agent_svid}",
        )

    # 2. Confidence threshold из матрицы митигации
    if dto.confidence < CONFIDENCE_THRESHOLD:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Confidence {dto.confidence:.2f} < threshold "
                f"{CONFIDENCE_THRESHOLD:.2f}"
            ),
        )

    # 3. Tool allow-list (двойная защита: Enum + явная проверка)
    if dto.tool_name not in (ToolName.SEND_NOTIFICATION,
                              ToolName.ARCHIVE_DOCUMENTS):
        return PolicyDecision(
            allowed=False,
            reason=f"Tool not in allow-list: {dto.tool_name}",
        )

    return PolicyDecision(
        allowed=True,
        reason="All policy checks passed",
    )


# ─── Целевые воркеры (имитация вызова) ────────────────────────────

async def call_target_worker(dto: RecommendationDTO) -> dict[str, Any]:
    """
    Имитация вызова целевого воркера.

    В реальном проекте здесь был бы HTTP-вызов, gRPC или
    отправка задачи обратно в Zeebe с другим task_type.
    Для пет-проекта — заглушка с реалистичным поведением.
    """
    if dto.tool_name == ToolName.SEND_NOTIFICATION:
        await asyncio.sleep(0.5)
        return {
            "target_worker": "send-notification",
            "status": "delivered",
            "recipient": dto.parameters.get("recipient", "unknown"),
        }

    if dto.tool_name == ToolName.ARCHIVE_DOCUMENTS:
        await asyncio.sleep(0.5)
        return {
            "target_worker": "archive-documents",
            "status": "archived",
            "document_id": dto.parameters.get("document_id", "unknown"),
        }

    raise ValueError(f"Unknown tool: {dto.tool_name}")


# ─── Обработчик задачи tool-executor ──────────────────────────────

async def main() -> None:
    channel = create_camunda_cloud_channel(
        client_id="GzjcEBwafwNPHDEpuyVEh3QqLn2BEIXK",
        client_secret="Yz~dNUNr0CIuuiuvCf87bMXLA5d4udA4lqvZ05UbtfOr0UeTZJ~S6VjOQgGhxz_v",
        cluster_id="f03961fc-6194-4dc6-a3a6-7870720e0ba0",
        region="bru-2",
    )

    worker = ZeebeWorker(channel)

    @worker.task(task_type="tool-executor")
    async def handle_tool_executor(job: Job) -> dict[str, Any]:
        """
        Главный обработчик. Вход: RecommendationDTO (как variables).
        Выход: результат вызова или BPMN Error через raise.
        """
        # 1. Парсинг DTO из переменных процесса
        try:
            dto = RecommendationDTO(
                tool_name=job.variables.get("tool_name"),
                confidence=job.variables.get("confidence", 0.0),
                reasoning=job.variables.get("reasoning", ""),
                parameters=job.variables.get("parameters", {}),
                agent_svid=job.variables.get("agent_svid", ""),
            )
        except Exception as e:
            audit(
                event="dto_parse_error",
                job_key=job.key,
                error=str(e),
            )
            # BPMN Error: маршрутизация на эскалацию
            raise RuntimeError(f"Invalid RecommendationDTO: {e}")

        audit(
            event="recommendation_received",
            job_key=job.key,
            tool=dto.tool_name.value,
            confidence=dto.confidence,
            svid=dto.agent_svid,
            reasoning=dto.reasoning,
        )

        # 2. Проверка политик
        decision = evaluate_policy(dto)
        audit(
            event="policy_evaluated",
            job_key=job.key,
            allowed=decision.allowed,
            reason=decision.reason,
        )

        # 3. DENY → BPMN Error (эскалация на человека)
        if not decision.allowed:
            raise RuntimeError(
                f"Policy denied: {decision.reason}"
            )

        # 4. ALLOW → вызов целевого воркера
        result = await call_target_worker(dto)
        audit(
            event="tool_executed",
            job_key=job.key,
            tool=dto.tool_name.value,
            result=result,
        )

        return {
            "execution_result": result,
            "policy_decision": "ALLOW",
        }

    print("Tool Executor started, waiting for tasks...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
