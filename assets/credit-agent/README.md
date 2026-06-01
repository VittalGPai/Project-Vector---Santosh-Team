# Credit Agent

A sub-agent that retrieves customer credit limit, utilisation, creditworthiness score, and risk class from SAP S/4HANA Credit Management to assess customer credit risk.

## Overview

Uses A2A Protocol, LangGraph, LiteLLM, and SAP Cloud SDK.

## Structure

- `app/main.py` - A2A server entry
- `app/agent_executor.py` - Request handling
- `app/agent.py` - Agent logic
