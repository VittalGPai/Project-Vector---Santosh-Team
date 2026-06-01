import asyncio
import json
import logging
import os
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

# Sub-agent endpoints — configured via environment variables
CREDIT_AGENT_URL = os.environ.get("CREDIT_AGENT_URL", "http://localhost:5001")
COLLECTION_AGENT_URL = os.environ.get("COLLECTION_AGENT_URL", "http://localhost:5002")

# Delivery block reason used when blocking an order
DELIVERY_BLOCK_REASON_CREDIT = "01"


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
    return """You are a Sales Agent that creates SAP S/4HANA sales orders with intelligent credit and collection risk gating.

The credit_assessment and collection_assessment are provided in the query JSON.

Based on those assessments and the order data in the query, create a sales order using the available Sales Order MCP tools.

Steps:
1. Parse the input JSON to extract: order_data (SalesOrderType, SalesOrganization, DistributionChannel, OrganizationDivision, SoldToParty, items), credit_assessment, collection_assessment.
2. Determine the decision:
   - BLOCK if: credit_assessment.assessment == "HIGH" OR credit_assessment.account_blocked == true OR collection_assessment.recommendation == "BLOCK"
   - RELEASE otherwise
3. If BLOCK: set DeliveryBlockReason to "01" in the order.
4. Call get_metadata_api_sales_order_srv first if needed to understand the sales order schema.
5. Create the sales order using the POST /A_SalesOrder equivalent MCP tool with the fields from order_data and the block decision.
6. Return ONLY a JSON object with:
   - sales_order_id: the created order number (string or null if creation failed)
   - decision: "RELEASE" or "BLOCK"
   - rationale: one-sentence explanation of the decision
   - credit_assessment: the credit_assessment from input
   - collection_assessment: the collection_assessment from input
   - error: error message if order creation failed (omit if successful)

Never create an order without the credit and collection assessments. Never hallucinate order data.
Always set top to a maximum of 100 on list calls."""


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

    async def _call_sub_agent(self, agent_url: str, query: str) -> dict:
        """Call an A2A sub-agent and return its response as a parsed dict.

        Falls back to a safe default (BLOCK) if the sub-agent is unreachable.
        """
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # A2A JSON-RPC style call
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "id": 1,
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": query}],
                        }
                    },
                }
                resp = await client.post(f"{agent_url}/", json=payload)
                resp.raise_for_status()
                result = resp.json()
                # Extract text from A2A response
                artifacts = result.get("result", {}).get("artifacts", [])
                for artifact in artifacts:
                    for part in artifact.get("parts", []):
                        if part.get("type") == "text":
                            text = part.get("text", "{}")
                            try:
                                return json.loads(text)
                            except json.JSONDecodeError:
                                return {"raw": text}
                return {"error": "No artifact in sub-agent response"}
        except Exception as e:
            logger.warning("Sub-agent call to %s failed: %s", agent_url, str(e))
            return {"error": f"sub-agent-unavailable: {str(e)}"}

    async def _call_credit_agent(self, customer_id: str, credit_segment: str = "") -> dict:
        """Call the Credit Agent sub-agent and return the credit assessment."""
        query = json.dumps({"customer_id": customer_id, "credit_segment": credit_segment})
        result = await self._call_sub_agent(CREDIT_AGENT_URL, f"Assess credit risk for customer {customer_id}. Input: {query}")
        if "error" in result and "sub-agent-unavailable" in result.get("error", ""):
            logger.warning("M2.missed: credit risk data unavailable — defaulting to block")
            return {
                "assessment": "HIGH",
                "account_blocked": False,
                "credit_limit": None,
                "credit_utilisation_pct": None,
                "creditworthiness_score": None,
                "credit_risk_class": None,
                "customer_id": customer_id,
                "error": result["error"],
            }
        logger.info(
            "M2.achieved: credit risk evaluated — limit=%s, utilisation=%s, score=%s",
            result.get("credit_limit", "unknown"),
            result.get("credit_utilisation_pct", "unknown"),
            result.get("creditworthiness_score", "unknown"),
        )
        return result

    async def _call_collection_agent(self, customer_id: str) -> dict:
        """Call the Collection Agent sub-agent and return the collection assessment."""
        query = json.dumps({"customer_id": customer_id})
        result = await self._call_sub_agent(COLLECTION_AGENT_URL, f"Assess collection status for customer {customer_id}. Input: {query}")
        if "error" in result and "sub-agent-unavailable" in result.get("error", ""):
            logger.warning(
                "M3.missed: collection data unavailable — proceeding with credit-only assessment"
            )
            return {
                "collection_risk": "HIGH",
                "recommendation": "BLOCK",
                "negative_event_count": 0,
                "account_is_blocked": False,
                "account_is_critical": False,
                "customer_id": customer_id,
                "error": result["error"],
            }
        logger.info(
            "M3.achieved: collection status assessed — overdue=unknown, broken_promises=%s",
            result.get("negative_event_count", "unknown"),
        )
        return result

    def _make_decision(self, credit: dict, collection: dict) -> tuple[str, str]:
        """Return (decision, rationale) based on sub-agent assessments."""
        if credit.get("account_blocked"):
            return "BLOCK", "Customer credit account is blocked."
        if credit.get("assessment") == "HIGH":
            return "BLOCK", "Customer credit risk class is HIGH."
        if collection.get("recommendation") == "BLOCK":
            risk = collection.get("collection_risk", "elevated")
            count = collection.get("negative_event_count", 0)
            return "BLOCK", f"Customer has {count} adverse payment event(s); collection risk is {risk}."
        if credit.get("assessment") == "UNKNOWN" or collection.get("collection_risk") == "UNKNOWN":
            return "BLOCK", "Credit or collection data unavailable; defaulting to block for safety."
        return "RELEASE", "Credit risk and collection status are within acceptable thresholds."

    @tracer.start_as_current_span("sales_agent.run")
    async def _run_agent(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> str:
        """Orchestrate credit/collection assessment and create sales order."""
        # Parse the incoming order request
        try:
            order_request = json.loads(query)
        except json.JSONDecodeError:
            order_request = {"raw_query": query}

        customer_id = order_request.get("customer_id") or order_request.get("SoldToParty", "")
        if not customer_id:
            logger.warning("M1.missed: payment assessment could not be initiated — missing customer_id or input validation failed")
            return json.dumps({
                "sales_order_id": None,
                "decision": "BLOCK",
                "rationale": "Missing customer_id in order request.",
                "credit_assessment": {},
                "collection_assessment": {},
                "error": "Missing customer_id",
            })

        logger.info("M1.achieved: customer payment assessment initiated for customer %s", customer_id)

        # Call Credit Agent and Collection Agent in parallel
        credit_result, collection_result = await asyncio.gather(
            self._call_credit_agent(customer_id),
            self._call_collection_agent(customer_id),
            return_exceptions=True,
        )

        # Handle exceptions from parallel calls
        if isinstance(credit_result, Exception):
            logger.warning("M2.missed: credit risk data unavailable — defaulting to block")
            credit_result = {"assessment": "HIGH", "account_blocked": False, "error": str(credit_result)}
        if isinstance(collection_result, Exception):
            logger.warning("M3.missed: collection data unavailable — proceeding with credit-only assessment")
            collection_result = {"collection_risk": "HIGH", "recommendation": "BLOCK", "error": str(collection_result)}

        # Make release/block decision
        decision, rationale = self._make_decision(credit_result, collection_result)
        logger.info("M4.achieved: order decision=%s, rationale=%s", decision, rationale)

        # Build the enriched query for the LLM to create the order
        agent_query = json.dumps({
            "order_data": order_request,
            "credit_assessment": credit_result,
            "collection_assessment": collection_result,
            "decision": decision,
            "rationale": rationale,
            "delivery_block_reason": DELIVERY_BLOCK_REASON_CREDIT if decision == "BLOCK" else None,
        })

        # Invoke LLM agent to create the sales order via MCP tools
        graph = create_agent(
            self.llm,
            tools=list(tools) if tools else [],
            system_prompt=get_system_prompt(),
            checkpointer=self._checkpointer,
            middleware=[self._summarization_middleware],
        )
        config = {"configurable": {"thread_id": context_id}}
        result = await graph.ainvoke({"messages": [HumanMessage(content=agent_query)]}, config)
        response_text = result["messages"][-1].content

        # Parse response and emit M5
        try:
            response_data = json.loads(response_text) if isinstance(response_text, str) else {}
            order_id = response_data.get("sales_order_id")
            if order_id:
                logger.info(
                    "M5.achieved: sales order created — order_id=%s, status=%s",
                    order_id,
                    decision,
                )
            else:
                error_msg = response_data.get("error", "unknown error")
                logger.warning("M5.missed: sales order creation failed — error=%s", error_msg)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("M5.missed: sales order creation failed — error=response parse error")

        return response_text

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
            "content": "Assessing customer risk profile...",
        }

        try:
            response = await self._run_agent(query, context_id, tools=tools)
            self._touch(context_id)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

        except Exception as e:
            logger.exception("Sales Agent stream() failed")
            logger.warning("M4.missed: decision synthesis failed — sub-agent data insufficient")
            logger.warning("M5.missed: sales order creation failed — error=%s", str(e))
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": json.dumps({
                    "sales_order_id": None,
                    "decision": "BLOCK",
                    "rationale": f"Agent error prevented order creation: {str(e)}",
                    "credit_assessment": {},
                    "collection_assessment": {},
                    "error": str(e),
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
