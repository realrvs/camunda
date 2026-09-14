"""
LLM Agent — вызывает Groq API с tool definition.

Заменяет нативный AI Agent Task из Camunda 8.9, который
в SaaS-версии содержит баги с OpenAI Compatible provider.

Этот воркер:
1. Получает approved и comment из переменных процесса.
2. Отправляет запрос в Groq API с tool definition для tool-executor.
3. Парсит tool call из ответа LLM.
4. Возвращает RecommendationDTO в переменные процесса.

Реализация раздела 3.6.1 (LLM as a Service) и 4.1 (политики агентов)
из Enterprise Agent Orchestration Blueprint.
"""

import asyncio
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from pyzeebe import ZeebeWorker, Job, create_camunda_cloud_channel

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

AGENT_SVID = "spiffe://test.ru/agents/procurement_agent_v1"


# ─── Tool definition (OpenAI-совместимый формат) ─────────────────

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "tool_executor",
        "description": (
            "Выполнить рекомендованное действие по обработке заявки. "
            "Используй send-notification при approved=true, "
            "archive-documents при approved=false."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "enum": ["send-notification", "archive-documents"],
                    "description": "Действие для выполнения",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Уверенность агента в решении",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Обоснование решения",
                },
                "parameters": {
                    "type": "object",
                    "description": "Параметры для целевого воркера",
                },
            },
            "required": ["tool_name", "confidence", "reasoning"],
        },
    },
}


SYSTEM_PROMPT = (
    "Ты — агент обработки заявок на закупку. "
    "Всегда вызывай инструмент tool_executor. "
    "Если approved=true → tool_name='send-notification'. "
    "Если approved=false → tool_name='archive-documents'. "
    "confidence выставляй 0.95 при ясных данных, ниже — при неясных."
)


# ─── Вызов Groq API ──────────────────────────────────────────────

async def call_groq(approved: bool, comment: str) -> dict[str, Any]:
    """Отправляет запрос в Groq и возвращает tool call arguments."""
    user_message = (
        f"Обработай заявку. "
        f"approved={str(approved).lower()}, comment='{comment}'"
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "tools": [TOOL_DEFINITION],
        "tool_choice": {
            "type": "function",
            "function": {"name": "tool_executor"},
        },
        "temperature": 0.0,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GROQ_API_URL, json=payload, headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    message = data["choices"][0]["message"]
    tool_calls = message.get("tool_calls", [])
    if not tool_calls:
        raise RuntimeError(
            f"LLM did not return tool call. Response: {message}"
        )

    arguments = json.loads(tool_calls[0]["function"]["arguments"])
    return arguments


# ─── Обработчик задачи llm-agent ─────────────────────────────────

async def main() -> None:
    channel = create_camunda_cloud_channel(
        client_id="GzjcEBwafwNPHDEpuyVEh3QqLn2BEIXK",
        client_secret="Yz~dNUNr0CIuuiuvCf87bMXLA5d4udA4lqvZ05UbtfOr0UeTZJ~S6VjOQgGhxz_v",
        cluster_id="f03961fc-6194-4dc6-a3a6-7870720e0ba0",
        region="bru-2",
    )

    worker = ZeebeWorker(channel)

    @worker.task(task_type="llm-agent")
    async def handle_llm_agent(job: Job) -> dict[str, Any]:
        approved = job.variables.get("approved", False)
        comment = job.variables.get("comment", "")

        print(f"[llm-agent] approved={approved}, comment='{comment}'")

        try:
            dto_args = await call_groq(approved, comment)
        except Exception as e:
            print(f"[llm-agent] ERROR: {e}")
            raise RuntimeError(f"LLM call failed: {e}")

        print(f"[llm-agent] LLM returned: {dto_args}")

        return {
            "tool_name": dto_args["tool_name"],
            "confidence": dto_args["confidence"],
            "reasoning": dto_args["reasoning"],
            "parameters": dto_args.get("parameters", {}),
            "agent_svid": AGENT_SVID,
        }

    print("LLM Agent started, waiting for tasks...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
