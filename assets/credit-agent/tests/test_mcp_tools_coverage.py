"""Tests to increase coverage of mcp_tools.py and util.py."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class TestBuildMockTools:
    def test_build_mock_tools_returns_list(self, add_agent_to_path):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_build_mock_tools_tool_names_nonempty(self, add_agent_to_path):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        for tool in tools:
            assert tool.name

    def test_build_mock_tools_missing_file_returns_empty(self, add_agent_to_path, tmp_path):
        import mcp_tools
        original = mcp_tools._MOCK_FILE
        try:
            mcp_tools._MOCK_FILE = tmp_path / "nonexistent.json"
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original

    def test_build_mock_tools_invalid_json_returns_empty(self, add_agent_to_path, tmp_path):
        import mcp_tools
        bad_file = tmp_path / "mcp-mock.json"
        bad_file.write_text("NOT VALID JSON {{{")
        original = mcp_tools._MOCK_FILE
        try:
            mcp_tools._MOCK_FILE = bad_file
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original

    @pytest.mark.asyncio
    async def test_mock_tool_invoke_returns_json_string(self, add_agent_to_path):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        assert len(tools) > 0
        tool = tools[0]
        result = await tool.coroutine()
        assert isinstance(result, str)


class TestGetMcpToolsIbdTesting:
    @pytest.mark.asyncio
    async def test_get_mcp_tools_returns_mock_tools(self, add_agent_to_path):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_get_mcp_tools_no_cache(self, add_agent_to_path):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools(use_cache=False)
        assert isinstance(tools, list)


class TestEnhanceToolFunctions:
    def test_enhance_tool_name_returns_string(self, add_agent_to_path):
        from util import enhance_tool_name
        mock_tool = MagicMock()
        mock_tool.namespaced_name = "credit_server__get_account"
        mock_tool.name = "get_account"
        result = enhance_tool_name(mock_tool)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_enhance_tool_description_returns_string(self, add_agent_to_path):
        from util import enhance_tool_description
        mock_tool = MagicMock()
        mock_tool.description = "Get credit account"
        mock_tool.server_name = "credit-server"
        mock_tool.namespaced_name = "credit_server__get_account"
        result = enhance_tool_description(mock_tool)
        assert isinstance(result, str)


class TestConvertMcpToolToLangchain:
    def test_convert_creates_structured_tool(self, add_agent_to_path):
        from mcp_tools import _convert_mcp_tool_to_langchain
        from langchain_core.tools import StructuredTool

        mock_tool = MagicMock()
        mock_tool.name = "get_account"
        mock_tool.namespaced_name = "credit__get_account"
        mock_tool.description = "Get account data"
        mock_tool.server_name = "credit"
        mock_tool.input_schema = {
            "type": "object",
            "properties": {
                "businesspartner": {"type": "string", "description": "BP ID"},
                "top": {"type": "integer", "description": "Max results"},
            },
            "required": ["businesspartner"],
        }

        mock_agw_client = MagicMock()
        result = _convert_mcp_tool_to_langchain(mock_tool, mock_agw_client)
        assert isinstance(result, StructuredTool)
        assert result.name == "credit__get_account"

    def test_convert_raises_on_none_tool(self, add_agent_to_path):
        from mcp_tools import _convert_mcp_tool_to_langchain
        with pytest.raises(ValueError, match="cannot be None"):
            _convert_mcp_tool_to_langchain(None, MagicMock())

    @pytest.mark.asyncio
    async def test_converted_tool_calls_agw(self, add_agent_to_path):
        from mcp_tools import _convert_mcp_tool_to_langchain

        mock_tool = MagicMock()
        mock_tool.name = "get_account"
        mock_tool.namespaced_name = "credit__get_account"
        mock_tool.description = "Get account"
        mock_tool.server_name = "credit"
        mock_tool.input_schema = {"type": "object", "properties": {}, "required": []}

        mock_agw_client = MagicMock()

        from util import call_mcp_tool_with_retry
        with patch("mcp_tools.call_mcp_tool_with_retry", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = '{"result": "ok"}'
            lc_tool = _convert_mcp_tool_to_langchain(mock_tool, mock_agw_client)
            result = await lc_tool.coroutine()
            assert result == '{"result": "ok"}'


class TestCallMcpToolWithRetry:
    @pytest.mark.asyncio
    async def test_call_mcp_tool_with_retry_success(self, add_agent_to_path):
        from util import call_mcp_tool_with_retry

        mock_tool = MagicMock()
        mock_tool.name = "get_account"
        mock_agw_client = AsyncMock()
        mock_agw_client.call_mcp_tool = AsyncMock(return_value='{"data": "test"}')

        result = await call_mcp_tool_with_retry(mock_agw_client, mock_tool, businesspartner="1000001")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_call_mcp_tool_with_retry_none_tool_raises(self, add_agent_to_path):
        from util import call_mcp_tool_with_retry
        with pytest.raises((ValueError, Exception)):
            await call_mcp_tool_with_retry(MagicMock(), None)
