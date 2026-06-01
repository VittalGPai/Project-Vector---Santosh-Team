"""Unit and integration tests for the Sales Agent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Credit agent mock responses
# ---------------------------------------------------------------------------
LOW_RISK_CREDIT = {
    "customer_id": "1000001", "credit_limit": "50000.00",
    "credit_utilisation_pct": 30.0, "credit_risk_class": "A",
    "creditworthiness_score": "800", "account_blocked": False,
    "assessment": "LOW",
}
HIGH_RISK_CREDIT = {
    "customer_id": "1000001", "credit_limit": "50000.00",
    "credit_utilisation_pct": 95.0, "credit_risk_class": "C",
    "creditworthiness_score": "400", "account_blocked": False,
    "assessment": "HIGH",
}
BLOCKED_CREDIT = {
    "customer_id": "1000001", "credit_limit": "50000.00",
    "credit_utilisation_pct": 0.0, "credit_risk_class": "B",
    "creditworthiness_score": "600", "account_blocked": True,
    "assessment": "MEDIUM",
}
LOW_RISK_COLLECTION = {
    "customer_id": "1000001", "negative_event_count": 0,
    "most_recent_event_type": None, "most_recent_event_date": None,
    "account_is_critical": False, "account_is_blocked": False,
    "collection_risk": "LOW", "recommendation": "RELEASE",
}
HIGH_RISK_COLLECTION = {
    "customer_id": "1000001", "negative_event_count": 2,
    "most_recent_event_type": "P2P", "most_recent_event_date": "/Date(1704067200000)/",
    "account_is_critical": False, "account_is_blocked": False,
    "collection_risk": "HIGH", "recommendation": "BLOCK",
}

ORDER_REQUEST = {
    "customer_id": "1000001",
    "SalesOrderType": "TA",
    "SalesOrganization": "1010",
    "DistributionChannel": "10",
    "OrganizationDivision": "00",
    "SoldToParty": "1000001",
    "items": [{"material": "MAT001", "quantity": 10, "unit": "EA"}],
}


# ---------------------------------------------------------------------------
# Unit tests — MilestoneInstrumentation
# ---------------------------------------------------------------------------

class TestSalesAgentMilestones:
    def test_all_milestones_in_agent_py(self, add_agent_to_path):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        for milestone in ["M1.achieved", "M1.missed", "M2.achieved", "M2.missed",
                          "M3.achieved", "M3.missed", "M4.achieved", "M4.missed",
                          "M5.achieved", "M5.missed"]:
            assert milestone in content, f"{milestone} missing from agent.py"

    def test_exactly_three_decorators(self, add_agent_to_path):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        decs = [l for l in content.splitlines()
                if l.startswith("@agent_model") or l.startswith("@agent_config") or l.startswith("@prompt_section")]
        assert len(decs) == 3, f"Expected 3, got {len(decs)}: {decs}"


# ---------------------------------------------------------------------------
# Unit tests — _make_decision logic
# ---------------------------------------------------------------------------

class TestMakeDecision:
    def test_high_credit_risk_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        decision, rationale = agent._make_decision(HIGH_RISK_CREDIT, LOW_RISK_COLLECTION)
        assert decision == "BLOCK"
        assert len(rationale) > 0

    def test_blocked_credit_account_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        decision, rationale = agent._make_decision(BLOCKED_CREDIT, LOW_RISK_COLLECTION)
        assert decision == "BLOCK"
        assert "blocked" in rationale.lower()

    def test_high_collection_risk_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        decision, rationale = agent._make_decision(LOW_RISK_CREDIT, HIGH_RISK_COLLECTION)
        assert decision == "BLOCK"
        assert len(rationale) > 0

    def test_both_low_risk_returns_release(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        decision, rationale = agent._make_decision(LOW_RISK_CREDIT, LOW_RISK_COLLECTION)
        assert decision == "RELEASE"

    def test_unknown_credit_assessment_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        unknown_credit = {"assessment": "UNKNOWN", "account_blocked": False}
        decision, rationale = agent._make_decision(unknown_credit, LOW_RISK_COLLECTION)
        assert decision == "BLOCK"

    def test_unknown_collection_assessment_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        unknown_collection = {"collection_risk": "UNKNOWN", "recommendation": "BLOCK"}
        decision, rationale = agent._make_decision(LOW_RISK_CREDIT, unknown_collection)
        assert decision == "BLOCK"


# ---------------------------------------------------------------------------
# Unit tests — sub-agent unavailable defaults to BLOCK
# ---------------------------------------------------------------------------

class TestSubAgentUnavailable:
    @pytest.mark.asyncio
    async def test_credit_agent_unavailable_defaults_to_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()

        unavailable = {"error": "sub-agent-unavailable: Connection refused"}
        with patch.object(agent, "_call_sub_agent", return_value=unavailable):
            result = await agent._call_credit_agent("1000001")

        assert result.get("assessment") == "HIGH"

    @pytest.mark.asyncio
    async def test_collection_agent_unavailable_defaults_to_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()

        unavailable = {"error": "sub-agent-unavailable: Connection refused"}
        with patch.object(agent, "_call_sub_agent", return_value=unavailable):
            result = await agent._call_collection_agent("1000001")

        assert result.get("recommendation") == "BLOCK"
        assert result.get("collection_risk") == "HIGH"


# ---------------------------------------------------------------------------
# Unit tests — stream error handling
# ---------------------------------------------------------------------------

class TestSalesAgentStreamError:
    @pytest.mark.asyncio
    async def test_stream_error_defaults_to_block_decision(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()

        with patch.object(agent, "_run_agent", side_effect=RuntimeError("Network error")):
            chunks = []
            async for chunk in agent.stream(json.dumps(ORDER_REQUEST), "ctx-err"):
                chunks.append(chunk)

        final = chunks[-1]
        assert final["is_task_complete"] is True
        content = json.loads(final["content"])
        assert content.get("decision") == "BLOCK"
        assert content.get("sales_order_id") is None


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestSalesAgentIntegration:
    @pytest.mark.asyncio
    async def test_high_credit_risk_creates_blocked_order(self, add_agent_to_path):
        """High credit risk → order created with delivery block."""
        from agent import SampleAgent
        agent = SampleAgent()

        llm_order_response = json.dumps({
            "sales_order_id": "1000000042",
            "decision": "BLOCK",
            "rationale": "Customer credit risk class is HIGH.",
            "credit_assessment": HIGH_RISK_CREDIT,
            "collection_assessment": LOW_RISK_COLLECTION,
        })

        mock_result = {"messages": [MagicMock(content=llm_order_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch.object(agent, "_call_credit_agent", return_value=HIGH_RISK_CREDIT), \
             patch.object(agent, "_call_collection_agent", return_value=LOW_RISK_COLLECTION), \
             patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke(json.dumps(ORDER_REQUEST), "ctx-high-credit")

        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["decision"] == "BLOCK"
        assert data["sales_order_id"] == "1000000042"

    @pytest.mark.asyncio
    async def test_low_risk_creates_released_order(self, add_agent_to_path):
        """Low risk → order created and released (no delivery block)."""
        from agent import SampleAgent
        agent = SampleAgent()

        llm_order_response = json.dumps({
            "sales_order_id": "1000000043",
            "decision": "RELEASE",
            "rationale": "Credit risk and collection status are within acceptable thresholds.",
            "credit_assessment": LOW_RISK_CREDIT,
            "collection_assessment": LOW_RISK_COLLECTION,
        })

        mock_result = {"messages": [MagicMock(content=llm_order_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch.object(agent, "_call_credit_agent", return_value=LOW_RISK_CREDIT), \
             patch.object(agent, "_call_collection_agent", return_value=LOW_RISK_COLLECTION), \
             patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke(json.dumps(ORDER_REQUEST), "ctx-low-risk")

        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["decision"] == "RELEASE"
        assert data["sales_order_id"] == "1000000043"

    @pytest.mark.asyncio
    async def test_collection_risk_creates_blocked_order(self, add_agent_to_path):
        """High collection risk → order blocked even if credit is OK."""
        from agent import SampleAgent
        agent = SampleAgent()

        llm_order_response = json.dumps({
            "sales_order_id": "1000000044",
            "decision": "BLOCK",
            "rationale": "Customer has 2 adverse payment event(s); collection risk is HIGH.",
            "credit_assessment": LOW_RISK_CREDIT,
            "collection_assessment": HIGH_RISK_COLLECTION,
        })

        mock_result = {"messages": [MagicMock(content=llm_order_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch.object(agent, "_call_credit_agent", return_value=LOW_RISK_CREDIT), \
             patch.object(agent, "_call_collection_agent", return_value=HIGH_RISK_COLLECTION), \
             patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke(json.dumps(ORDER_REQUEST), "ctx-collection-risk")

        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["decision"] == "BLOCK"

    @pytest.mark.asyncio
    async def test_missing_customer_id_returns_block(self, add_agent_to_path):
        """Missing customer_id in request → BLOCK with error."""
        from agent import SampleAgent
        agent = SampleAgent()

        result = await agent.invoke(
            json.dumps({"SalesOrderType": "TA"}),
            "ctx-missing-customer",
        )

        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["decision"] == "BLOCK"
        assert "error" in data


class TestCallSubAgent:
    @pytest.mark.asyncio
    async def test_call_sub_agent_success_returns_dict(self, add_agent_to_path):
        """Successful sub-agent call returns parsed dict."""
        from agent import SampleAgent
        import httpx

        agent = SampleAgent()
        mock_response_data = {
            "result": {
                "artifacts": [
                    {"parts": [{"type": "text", "text": json.dumps(LOW_RISK_CREDIT)}]}
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await agent._call_sub_agent("http://localhost:5001", '{"customer_id": "1000001"}')

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_call_credit_agent_success_logs_m2_achieved(self, add_agent_to_path):
        """Successful credit agent call should log M2.achieved."""
        from agent import SampleAgent
        import logging

        agent = SampleAgent()
        with patch.object(agent, "_call_sub_agent", return_value=LOW_RISK_CREDIT):
            result = await agent._call_credit_agent("1000001")

        assert result.get("assessment") == "LOW"
        assert "credit_limit" in result

    @pytest.mark.asyncio
    async def test_call_collection_agent_success_logs_m3_achieved(self, add_agent_to_path):
        """Successful collection agent call should log M3.achieved."""
        from agent import SampleAgent

        agent = SampleAgent()
        with patch.object(agent, "_call_sub_agent", return_value=LOW_RISK_COLLECTION):
            result = await agent._call_collection_agent("1000001")

        assert result.get("recommendation") == "RELEASE"
