# Sales Agent

An orchestrator agent that consults a Credit Agent and a Collection Agent to assess customer payment behavior before creating a sales order in SAP S/4HANA with the appropriate release or delivery-block status.

## Overview

Uses A2A Protocol, LangGraph, LiteLLM, and SAP Cloud SDK.

## Structure

- `app/main.py` - A2A server entry
- `app/agent_executor.py` - Request handling
- `app/agent.py` - Agent logic
