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
    return """You are a Collection Agent that assesses customer collection risk using SAP S/4HANA Credit Management data.

Instructions:
1. Retrieve negative events for the business partner using list_credit_management_business_partner_negative_event
   with filter: BusinessPartner eq '<customer_id>' and top set to 100.
2. Retrieve credit accounts using list_credit_management_account
   with filter: BusinessPartner eq '<customer_id>' and top set to 100.
3. Count the number of negative events returned.
4. Check if any credit account has CreditAccountIsBlocked=true or BusinessPartnerIsCritical=true.
5. Return ONLY a JSON object (no extra text) with these fields:
   - customer_id: the BusinessPartner value
   - negative_event_count: total count of negative events found (integer)
   - most_recent_event_type: CrdtAcctInformationType of most recent event (string or null)
   - most_recent_event_date: ValidityStartDate of most recent event (string or null)
   - account_is_critical: whether any account has BusinessPartnerIsCritical=true (boolean)
   - account_is_blocked: whether any account has CreditAccountIsBlocked=true (boolean)
   - collection_risk: "LOW", "MEDIUM", or "HIGH"
   - recommendation: "RELEASE" or "BLOCK"

Decision rules:
- negative_event_count >= 2: collection_risk = "HIGH", recommendation = "BLOCK"
- negative_event_count == 1: collection_risk = "MEDIUM", recommendation = "BLOCK"
- negative_event_count == 0 and (account_is_blocked or account_is_critical): collection_risk = "HIGH", recommendation = "BLOCK"
- negative_event_count == 0 and not blocked and not critical: collection_risk = "LOW", recommendation = "RELEASE"

Never hallucinate data. If no data found:
{"collection_risk": "UNKNOWN", "recommendation": "BLOCK", "customer_id": "<id>", "negative_event_count": 0,
 "most_recent_event_type": null, "most_recent_event_date": null, "account_is_critical": false,
 "account_is_blocked": false, "error": "No collection data available"}

Always set top to a maximum of 100 on all list calls."""


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

    @tracer.start_as_current_span("collection_agent.assess_collection_status")
    async def _run_agent(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> str:
        """Run the collection status assessment. Returns the agent's response string."""
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

        # Extract milestone fields for logging
        try:
            data = json.loads(response) if isinstance(response, str) else {}
            negative_count = data.get("negative_event_count", 0)
            # Use negative_event_count as proxy for overdue/broken promises
            if "error" not in data and data.get("collection_risk") != "UNKNOWN":
                logger.info(
                    "M3.achieved: collection status assessed — overdue=unknown, broken_promises=%s",
                    negative_count,
                )
            else:
                logger.warning(
                    "M3.missed: collection data unavailable — proceeding with credit-only assessment"
                )
        except (json.JSONDecodeError, AttributeError):
            logger.warning(
                "M3.missed: collection data unavailable — proceeding with credit-only assessment"
            )

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
            "content": "Assessing collection status...",
        }

        try:
            if tools:
                logger.info("Running collection agent with %d tool(s)", len(tools))
            else:
                logger.info("Running collection agent without tools")

            response = await self._run_agent(query, context_id, tools=tools)
            self._touch(context_id)

            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

        except Exception as e:
            logger.exception("Collection Agent stream() failed")
            logger.warning(
                "M3.missed: collection data unavailable — proceeding with credit-only assessment"
            )
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": json.dumps({
                    "collection_risk": "HIGH",
                    "recommendation": "BLOCK",
                    "customer_id": "unknown",
                    "negative_event_count": 0,
                    "most_recent_event_type": None,
                    "most_recent_event_date": None,
                    "account_is_critical": False,
                    "account_is_blocked": False,
                    "error": f"Agent error: {str(e)}",
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
