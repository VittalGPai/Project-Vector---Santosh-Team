"""Unit and integration tests for the Credit Agent."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Unit tests — tool mocks
# ---------------------------------------------------------------------------

class TestGetCreditManagementAccountTool:
    """Unit test for the get_credit_management_account MCP tool mock."""

    def test_mock_tool_returns_credit_account_data(self, add_agent_to_path):
        """Mock tool should return structured credit account data."""
        from mcp_tools import get_mcp_tools
        import asyncio

        tools = asyncio.get_event_loop().run_until_complete(get_mcp_tools())
        tool_names = [t.name for t in tools]
        # At least one credit account tool should be available
        assert any("credit" in name.lower() or "account" in name.lower() for name in tool_names), \
            f"Expected a credit account tool, got: {tool_names}"

    def test_credit_account_mock_has_expected_fields(self, add_agent_to_path):
        """Credit account mock response should have required fields."""
        import json
        from pathlib import Path
        mock_file = Path(__file__).parent.parent / "mcp-mock.json"
        assert mock_file.exists(), "mcp-mock.json must exist"
        data = json.loads(mock_file.read_text())
        
        # Get the get_credit_management_account tool from credit-mgmt server
        credit_mgmt = data["servers"].get("credit-mgmt", {})
        tool = credit_mgmt.get("tools", {}).get("get_credit_management_account", {})
        
        assert tool, "get_credit_management_account tool not found in mcp-mock.json"
        response = tool.get("mock_response", {})
        
        assert "BusinessPartner" in response
        assert "CreditLimitAmount" in response
        assert "CreditAccountIsBlocked" in response


class TestGetCreditManagementBusinessPartnerTool:
    """Unit test for the get_credit_management_business_partner MCP tool mock."""

    def test_mock_tool_returns_business_partner_data(self, add_agent_to_path):
        """Mock tool should return BP credit data with risk class."""
        import json
        from pathlib import Path
        mock_file = Path(__file__).parent.parent / "mcp-mock.json"
        data = json.loads(mock_file.read_text())
        
        credit_mgmt = data["servers"].get("credit-mgmt", {})
        tool = credit_mgmt.get("tools", {}).get("get_credit_management_business_partner", {})
        
        assert tool, "get_credit_management_business_partner tool not found"
        response = tool.get("mock_response", {})
        
        assert "BusinessPartner" in response
        assert "CreditRiskClass" in response
        assert "CreditWorthinessScoreValue" in response


# ---------------------------------------------------------------------------
# Unit tests — agent logic
# ---------------------------------------------------------------------------

class TestCreditAgentDecoratorCount:
    """Verify exactly 3 decorated functions in agent.py."""

    def test_exactly_three_decorators(self, add_agent_to_path):
        """agent.py must have exactly @agent_model, @agent_config, @prompt_section."""
        from pathlib import Path
        agent_py = Path(__file__).parent.parent / "app" / "agent.py"
        content = agent_py.read_text()
        
        decorator_lines = [line for line in content.splitlines()
                           if line.startswith("@agent_model") or
                              line.startswith("@agent_config") or
                              line.startswith("@prompt_section")]
        assert len(decorator_lines) == 3, \
            f"Expected 3 decorated functions, found {len(decorator_lines)}: {decorator_lines}"


class TestCreditAgentMilestoneInstrumentation:
    """Verify milestone log statements are present in agent code."""

    def test_m2_achieved_log_present(self, add_agent_to_path):
        """M2.achieved log statement must be in agent.py."""
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        assert "M2.achieved" in content, "M2.achieved milestone log missing from agent.py"

    def test_m2_missed_log_present(self, add_agent_to_path):
        """M2.missed log statement must be in agent.py."""
        from pathlib import Path
        content = (Path(__file__).parent.parent / "app" / "agent.py").read_text()
        assert "M2.missed" in content, "M2.missed milestone log missing from agent.py"


class TestCreditAgentMakeDecision:
    """Test the credit agent stream error handling (default to HIGH/BLOCK)."""

    @pytest.mark.asyncio
    async def test_stream_error_defaults_to_high(self, add_agent_to_path):
        """When _run_agent raises an exception, stream should yield HIGH assessment."""
        from agent import SampleAgent

        agent = SampleAgent()

        with patch.object(agent, "_run_agent", side_effect=RuntimeError("LLM error")):
            chunks = []
            async for chunk in agent.stream("test query", "ctx-001"):
                chunks.append(chunk)

        assert len(chunks) >= 1
        final = chunks[-1]
        assert final["is_task_complete"] is True
        # The error fallback should default to BLOCK/HIGH
        content = json.loads(final["content"])
        assert content.get("assessment") == "HIGH"


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestCreditAgentIntegration:
    """Integration test — runs the full agent flow with mocked LLM."""

    @pytest.mark.asyncio
    async def test_full_credit_assessment_returns_valid_json(self, add_agent_to_path):
        """Full end-to-end credit assessment should return a valid JSON assessment."""
        from agent import SampleAgent

        mock_llm_response = json.dumps({
            "customer_id": "1000001",
            "credit_limit": "50000.00",
            "credit_utilisation_pct": 42.0,
            "credit_risk_class": "B",
            "creditworthiness_score": "750",
            "account_blocked": False,
            "assessment": "MEDIUM",
        })

        agent = SampleAgent()

        # Mock the LLM response
        mock_result = {"messages": [MagicMock(content=mock_llm_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke(
                json.dumps({"customer_id": "1000001", "credit_segment": "0001"}),
                "ctx-integration-001",
            )

        assert result.status == "completed"
        data = json.loads(result.message)
        assert "assessment" in data
        assert data["assessment"] in ("LOW", "MEDIUM", "HIGH", "UNKNOWN")
        assert "customer_id" in data

    @pytest.mark.asyncio
    async def test_credit_assessment_with_no_data_defaults_to_unknown(self, add_agent_to_path):
        """If LLM returns no-data response, assessment should be UNKNOWN."""
        from agent import SampleAgent

        no_data_response = json.dumps({
            "assessment": "UNKNOWN",
            "error": "No credit data available",
            "customer_id": "9999999",
        })

        agent = SampleAgent()
        mock_result = {"messages": [MagicMock(content=no_data_response)]}
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch("agent.create_agent", return_value=mock_graph):
            result = await agent.invoke("9999999", "ctx-002")

        assert result.status == "completed"
        data = json.loads(result.message)
        assert data["assessment"] == "UNKNOWN"
