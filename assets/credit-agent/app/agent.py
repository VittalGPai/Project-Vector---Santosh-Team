import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry import trace
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

THREAD_TTL_SECONDS = 3600


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    return "sap/anthropic--claude-4.5-sonnet"


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0


@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are a Credit Agent that assesses customer credit risk using SAP S/4HANA Credit Management data.

Instructions:
1. Always call get_metadata_cds_api_crdtmbusinesspartner first if the entity structure is unknown.
2. Retrieve credit account data using get_credit_management_account with the BusinessPartner and CreditSegment.
3. Retrieve business partner credit master data using get_credit_management_business_partner with the BusinessPartner.
4. Return ONLY a JSON object (no extra text) with these fields:
   - customer_id: the BusinessPartner value
   - credit_limit: credit limit amount (string or null)
   - credit_utilisation_pct: estimated utilisation percentage (number or null)
   - credit_risk_class: credit risk class code (string or null)
   - creditworthiness_score: creditworthiness score value (string or null)
   - account_blocked: whether the credit account is blocked (boolean)
   - assessment: "LOW", "MEDIUM", or "HIGH" based on risk class and block status

Assessment rules:
- If account_blocked is true: assessment = "HIGH"
- If credit_risk_class is "A" or "1" (low risk): assessment = "LOW"
- If credit_risk_class is "B" or "2" (medium risk): assessment = "MEDIUM"
- If credit_risk_class is "C", "3", or higher: assessment = "HIGH"
- If risk class is unknown: assessment = "MEDIUM"

Never hallucinate credit data. If no data is found, return:
{"assessment": "UNKNOWN", "error": "No credit data available", "customer_id": "<id>"}

Always set top to a maximum of 100 on any list tool calls."""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class SampleAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        self.llm = ChatLiteLLM(model=get_model_name(), temperature=get_temperature())
        self._checkpointer = InMemorySaver()
        self._last_active: dict[str, float] = {}
        self._summarization_middleware = SummarizationMiddleware(
            model=self.llm,
            trigger=("tokens", 100_000),
        )

    def _touch(self, thread_id: str) -> None:
        now = time.monotonic()
        expired = [tid for tid, ts in list(self._last_active.items()) if now - ts > THREAD_TTL_SECONDS]
        for tid in expired:
            self._checkpointer.delete_thread(tid)
            del self._last_active[tid]
            logger.info("Evicted inactive thread: %s", tid)
        self._last_active[thread_id] = now

    @tracer.start_as_current_span("credit_agent.evaluate_credit_risk")
    async def _run_agent(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> str:
        """Run the credit risk evaluation. Returns the agent's response string."""
        graph = create_agent(
            self.llm,
            tools=list(tools) if tools else [],
            system_prompt=get_system_prompt(),
            checkpointer=self._checkpointer,
            middleware=[self._summarization_middleware],
        )
        config = {"configurable": {"thread_id": context_id}}
        result = await graph.ainvoke({"messages": [HumanMessage(content=query)]}, config)
        response = result["messages"][-1].content

        # Parse response to extract milestone fields for logging
        try:
            data = json.loads(response) if isinstance(response, str) else {}
            credit_limit = data.get("credit_limit", "unknown")
            utilisation = data.get("credit_utilisation_pct", "unknown")
            score = data.get("creditworthiness_score", "unknown")
            assessment = data.get("assessment", "unknown")
            if assessment not in ("UNKNOWN",) and "error" not in data:
                logger.info(
                    "M2.achieved: credit risk evaluated — limit=%s, utilisation=%s, score=%s",
                    credit_limit,
                    utilisation,
                    score,
                )
            else:
                logger.warning("M2.missed: credit risk data unavailable — defaulting to block")
        except (json.JSONDecodeError, AttributeError):
            logger.warning("M2.missed: credit risk data unavailable — defaulting to block")

        return response

    async def stream(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> AsyncGenerator[dict, None]:
        self._touch(context_id)
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Evaluating credit risk...",
        }

        try:
            if tools:
                logger.info("Running credit agent with %d tool(s)", len(tools))
            else:
                logger.info("Running credit agent without tools")

            response = await self._run_agent(query, context_id, tools=tools)
            self._touch(context_id)

            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

        except Exception as e:
            logger.exception("Credit Agent stream() failed")
            logger.warning("M2.missed: credit risk data unavailable — defaulting to block")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": json.dumps({
                    "assessment": "HIGH",
                    "error": f"Agent error: {str(e)}",
                    "customer_id": "unknown",
                    "account_blocked": False,
                }),
            }

    async def invoke(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> AgentResponse:
        last: dict = {}
        async for chunk in self.stream(query, context_id, tools=tools):
            last = chunk
        if last.get("is_task_complete"):
            return AgentResponse(status="completed", message=last["content"])
        if last.get("require_user_input"):
            return AgentResponse(status="input_required", message=last["content"])
        return AgentResponse(status="error", message=last.get("content", "Unknown error"))
