# Collection Agent

A sub-agent that retrieves customer collection status, overdue receivables context, and adverse payment events including broken promises to pay from SAP S/4HANA Credit Management.

## Overview

Uses A2A Protocol, LangGraph, LiteLLM, and SAP Cloud SDK.

## Structure

- `app/main.py` - A2A server entry
- `app/agent_executor.py` - Request handling
- `app/agent.py` - Agent logic
