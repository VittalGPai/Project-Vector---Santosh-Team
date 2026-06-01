# Specification: credit-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read `product-requirements-document.md` and `intent.md` for full context
- [ ] Bootstrap agent code in `assets/credit-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/credit-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## MCP Tool Integration (Path B — existing MCP server)

MCP Server ORD ID: `sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1`
Schema files: `specification/credit-agent/mcp-specs/`

- [ ] Add MCP server dependency to `assets/credit-agent/asset.yaml`:
  ```yaml
  requires:
    - name: credit-management-business-partner-mcp-demo
      kind: mcp-server
      ordId: sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1
  ```
- [ ] Wire MCP tool loading in `agent.py` using `get_mcp_tools()` from `mcp_tools.py` — lazy loading pattern (see guidelines-agent.md)

## Agent Implementation

The Credit Agent is a sub-agent that assesses customer credit risk. It receives a `customer_id` (BusinessPartner) and `credit_segment` (optional, default to empty/first available), retrieves credit data, and returns a structured credit assessment.

- [ ] Implement the agent system prompt instructing it to:
  - Always call `get_metadata_cds_api_crdtmbusinesspartner` first to understand entity structure
  - Retrieve credit account using `get_credit_management_account` (BusinessPartner + CreditSegment)
  - Retrieve BP credit master data using `get_credit_management_business_partner`
  - Return a structured JSON assessment: `{ "customer_id": "...", "credit_limit": ..., "credit_utilisation_pct": ..., "credit_risk_class": "...", "creditworthiness_score": "...", "account_blocked": true/false, "assessment": "LOW|MEDIUM|HIGH" }`
  - Never hallucinate credit data; if no data found, return `{ "assessment": "UNKNOWN", "error": "No credit data available" }`
  - Always set `top` to maximum 100 on any list tool calls

- [ ] Implement `stream()` method that:
  - Accepts `query` with JSON payload `{ "customer_id": "...", "credit_segment": "..." }`
  - Calls `_run_agent()` helper (extracted from generator to allow OTel instrumentation)
  - Yields the structured credit assessment as the final response

- [ ] Implement `_run_agent()` as a plain async method (not a generator) that:
  - Loads tools lazily
  - Builds the LangGraph agent graph
  - Invokes the graph with the customer query
  - Returns the structured credit assessment JSON

## Milestones & Instrumentation

- [ ] Instrument `_run_agent()` with milestone logging (NOT inside `stream()` generator):
  - `M2.achieved: credit risk evaluated — limit={credit_limit}, utilisation={utilisation_pct}, score={credit_score}`
  - `M2.missed: credit risk data unavailable — defaulting to block`
- [ ] Add OpenTelemetry spans using decorator form on `_run_agent()`:
  ```python
  @tracer.start_as_current_span("credit_agent.evaluate_credit_risk")
  async def _run_agent(self, customer_id: str, credit_segment: str) -> dict:
      ...
  ```
- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## Mock Configuration

- [ ] Generate `mcp-mock.json` using `mcp-mock-config` skill after MCP specs are confirmed in `specification/credit-agent/mcp-specs/`

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=true`
- [ ] Write unit test for `get_credit_management_account` tool mock
- [ ] Write unit test for `get_credit_management_business_partner` tool mock
- [ ] Write integration test: end-to-end credit assessment for a mock customer ID returns valid JSON with `assessment` field
- [ ] Mock LLM (ChatLiteLLM) in all tests — no real AI Core calls
- [ ] Run `pytest` from `assets/credit-agent/` — coverage ≥ 70%
- [ ] Run `pytest` (no args) to generate final `test_report.json`
- [ ] Verify `test_report.json` exists in `assets/credit-agent/`
- [ ] Run validation checklist from guidelines-agent.md
