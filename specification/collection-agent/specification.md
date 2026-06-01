# Specification: collection-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read `product-requirements-document.md` and `intent.md` for full context
- [ ] Bootstrap agent code in `assets/collection-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/collection-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## MCP Tool Integration (Path B — existing MCP server)

MCP Server ORD ID: `sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1`
Schema files: `specification/collection-agent/mcp-specs/`

Tools used by the Collection Agent:
- `list_credit_management_business_partner_negative_event` — retrieves adverse payment events (payment defaults, insolvencies, broken promises)
- `list_credit_management_account` — retrieves credit exposure to check if account is blocked or critical

- [ ] Add MCP server dependency to `assets/collection-agent/asset.yaml`:
  ```yaml
  requires:
    - name: credit-management-business-partner-mcp-demo
      kind: mcp-server
      ordId: sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1
  ```
- [ ] Wire MCP tool loading in `agent.py` using `get_mcp_tools()` from `mcp_tools.py` — lazy loading pattern

## Agent Implementation

The Collection Agent is a sub-agent that assesses customer collection status and broken payment commitments. It receives a `customer_id` (BusinessPartner) and returns a structured collection assessment.

- [ ] Implement the agent system prompt instructing it to:
  - Retrieve negative events for the business partner using `list_credit_management_business_partner_negative_event` with filter `BusinessPartner eq '{customer_id}'`
  - Retrieve credit accounts using `list_credit_management_account` with filter `BusinessPartner eq '{customer_id}'`
  - Count negative events to determine broken promise severity
  - Return a structured JSON assessment:
    ```json
    {
      "customer_id": "...",
      "negative_event_count": 0,
      "most_recent_event_type": "...",
      "most_recent_event_date": "...",
      "account_is_critical": true/false,
      "account_is_blocked": true/false,
      "collection_risk": "LOW|MEDIUM|HIGH",
      "recommendation": "RELEASE|BLOCK"
    }
    ```
  - Apply this decision logic:
    - `negative_event_count >= 2` → `collection_risk: HIGH`, `recommendation: BLOCK`
    - `negative_event_count == 1` → `collection_risk: MEDIUM`, `recommendation: BLOCK`
    - `negative_event_count == 0` and `account_is_blocked == true` → `collection_risk: HIGH`, `recommendation: BLOCK`
    - Otherwise → `collection_risk: LOW`, `recommendation: RELEASE`
  - Never hallucinate data; if no data found, return `{ "collection_risk": "UNKNOWN", "recommendation": "BLOCK", "error": "No collection data" }`
  - Always set `top` to maximum 100 on list calls

- [ ] Implement `stream()` calling `_run_agent()` helper (not a generator)
- [ ] Implement `_run_agent()` as a plain async method that loads tools, builds graph, and returns structured JSON

## Milestones & Instrumentation

- [ ] Instrument `_run_agent()` with milestone logging:
  - `M3.achieved: collection status assessed — overdue={overdue_amount}, broken_promises={broken_promise_count}`
  - `M3.missed: collection data unavailable — proceeding with credit-only assessment`
- [ ] Add OpenTelemetry span on `_run_agent()`:
  ```python
  @tracer.start_as_current_span("collection_agent.assess_collection_status")
  async def _run_agent(self, customer_id: str) -> dict:
      ...
  ```
- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## Mock Configuration

- [ ] Generate `mcp-mock.json` using `mcp-mock-config` skill after MCP specs are confirmed in `specification/collection-agent/mcp-specs/`

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=true`
- [ ] Write unit test: customer with 2 negative events → returns `collection_risk: HIGH`, `recommendation: BLOCK`
- [ ] Write unit test: customer with 0 negative events, unblocked account → returns `collection_risk: LOW`, `recommendation: RELEASE`
- [ ] Write integration test: end-to-end collection assessment returns valid JSON with `recommendation` field
- [ ] Mock LLM (ChatLiteLLM) in all tests
- [ ] Run `pytest` from `assets/collection-agent/` — coverage ≥ 70%
- [ ] Run `pytest` (no args) to generate final `test_report.json`
- [ ] Verify `test_report.json` exists in `assets/collection-agent/`
- [ ] Run validation checklist from guidelines-agent.md
