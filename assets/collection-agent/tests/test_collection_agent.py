"""Unit and integration tests for the Collection Agent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestNegativeEventToolMock:
    def test_negative_event_mock_has_expected_fields(self, add_agent_to_path):
        from pathlib import Path
        data = json.loads((Path(__file__).parent.parent / "mcp-mock.json").read_text())
        credit_mgmt = data["servers"].get("credit-mgmt", {})
        tool = credit_mgmt.get("tools", {}).get(
            "list_credit_management_business_partner_negative_event", {}
        )
        assert tool, "list_credit_management_business_partner_negative_event not found"
        response = tool.get("mock_response", {})
        assert "value" in response
        assert len(response["value"]) > 0
        event = response["value"][0]
        assert "BusinessPartner" in event
        assert "CrdtAcctInformationType" in event

    def test_credit_account_mock_has_expected_fields(self, add_agent_to_path):
        from pathlib import Path
        data = json.loads((Path(__file__).parent.parent / "mcp-mock.json").read_text())
        credit_mgmt = data["servers"].get("credit-mgmt", {})
        tool = credit_mgmt.get("tools", {}).get("list_credit_management_account", {})
        assert tool, "list_credit_management_account not found"
        response = tool.get("mock_response", {})
        assert "value" in response


class TestCollectionAgentDecoratorCount:
    def test_exactly_three_decorators(self, add_agent_to_path):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        decs = [l for l in content.splitlines()
                if l.startswith("@agent_model") or l.startswith("@agent_config") or l.startswith("@prompt_section")]
        assert len(decs) == 3, f"Expected 3, found {len(decs)}: {decs}"


class TestCollectionAgentMilestoneInstrumentation:
    def test_m3_achieved_log_present(self, add_agent_to_path):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        assert "M3.achieved" in content

    def test_m3_missed_log_present(self, add_agent_to_path):
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        assert "M3.missed" in content


class TestCollectionAgentErrorHandling:
    @pytest.mark.asyncio
    async def test_stream_error_defaults_to_block(self, add_agent_to_path):
        from agent import SampleAgent
        agent = SampleAgent()
        with patch.object(agent, "_run_agent", side_effect=RuntimeError("LLM error")):
            chunks = []
            async for chunk in agent.stream("test", "ctx-err"):
                chunks.append(chunk)
        final = chunks[-1]
        assert final["is_task_complete"] is True
        content = json.loads(final["content"])
        assert content.get("recommendation") == "BLOCK"
        assert content.get("collection_risk") == "HIGH"


class TestCollectionAgentIntegration:
    @pytest.mark.asyncio
    async def test_customer_with_events_returns_block(self, add_agent_to_path):
        from agent import SampleAgent
        block_response = json.dumps({
            "customer_id": "1000001",
            "negative_event_count": 2,
            "most_recent_event_type": "P2P",
            "most_recent_event_date": "/Date(1704067200000)/",
            "account_is_critical": False,
            "account_is_blocked": False,
            "collection_risk": "HIGH",
            "recommendation": "BLOCK",
        })
        agent = SampleAgent()
        mock_result = {"messages": [MagicMock(content=block_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)
        with patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke('{"customer_id": "1000001"}', "ctx-block")
        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["recommendation"] == "BLOCK"
        assert data["collection_risk"] == "HIGH"

    @pytest.mark.asyncio
    async def test_customer_without_events_returns_release(self, add_agent_to_path):
        from agent import SampleAgent
        release_response = json.dumps({
            "customer_id": "2000001",
            "negative_event_count": 0,
            "most_recent_event_type": None,
            "most_recent_event_date": None,
            "account_is_critical": False,
            "account_is_blocked": False,
            "collection_risk": "LOW",
            "recommendation": "RELEASE",
        })
        agent = SampleAgent()
        mock_result = {"messages": [MagicMock(content=release_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)
        with patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke('{"customer_id": "2000001"}', "ctx-release")
        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["recommendation"] == "RELEASE"
        assert data["collection_risk"] == "LOW"
