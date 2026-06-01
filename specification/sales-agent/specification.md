# Specification: sales-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read `product-requirements-document.md` and `intent.md` for full context
- [ ] Bootstrap agent code in `assets/sales-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/sales-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## MCP Tool Integration

### Path B — Existing MCP server (Sales Order read)

MCP Server ORD ID: `sap.mcpbuilder:apiResource:sales_order_mcp_demo:v1`
Schema files: `specification/sales-agent/mcp-specs/`

- [ ] Add MCP server dependencies to `assets/sales-agent/asset.yaml`:
  ```yaml
  requires:
    - name: sales-order-mcp-demo
      kind: mcp-server
      ordId: sap.mcpbuilder:apiResource:sales_order_mcp_demo:v1
  ```

### Path A — API spec for Sales Order creation (POST)

API spec file: `specification/sales-agent/api-specs/sales-order-create.json`
API ORD ID: `sap.s4:apiResource:API_SALES_ORDER_SRV:v1`

The existing Sales Order MCP server only exposes read operations. Sales order creation requires a custom MCP translation.

- [ ] Invoke `mcp-translation-file` skill with `specification/sales-agent/api-specs/sales-order-create.json` to generate MCP translation file for POST /A_SalesOrder
  - If `mcp-translation-file` is unavailable or fails Gate 0, log: `[MCP-SKILL] mcp-translation-file unavailable — skipping MCP server asset generation. Agent will use existing MCP servers only.` and proceed to testing without the create capability
- [ ] If `mcp-translation-file` succeeded: invoke `setup-solution` skill to register the new MCP server asset
- [ ] Add the new MCP server asset to `assets/sales-agent/asset.yaml` `requires` section
- [ ] Wire MCP tool loading in `agent.py` using `get_mcp_tools()` from `mcp_tools.py` — lazy loading pattern

## Sub-Agent Integration (A2A)

The Sales Agent is the orchestrator. It calls the Credit Agent and Collection Agent as A2A sub-agents using the `sap_cloud_sdk.agentgateway` A2A client.

- [ ] Wire sub-agent calls via A2A client:
  - Credit Agent endpoint: configurable via env var `CREDIT_AGENT_URL`
  - Collection Agent endpoint: configurable via env var `COLLECTION_AGENT_URL`
- [ ] Implement sub-agent invocation helpers:
  ```python
  async def _call_credit_agent(self, customer_id: str, credit_segment: str = "") -> dict:
      """Calls Credit Agent and returns structured credit assessment."""

  async def _call_collection_agent(self, customer_id: str) -> dict:
      """Calls Collection Agent and returns structured collection assessment."""
  ```
- [ ] Sub-agent calls must be made in parallel (using `asyncio.gather`) to minimise latency
- [ ] If a sub-agent is unreachable or returns an error, default to BLOCK and log `sub-agent-unavailable`

## Agent Implementation

The Sales Agent orchestrates the full flow: receive order request → consult Credit Agent and Collection Agent in parallel → decide release/block → create sales order.

- [ ] Implement the agent system prompt instructing it to:
  1. Parse the incoming order request: `customer_id`, `sales_order_type`, `sales_organization`, `distribution_channel`, `division`, `requested_delivery_date`, `items` (array of `{material, quantity, unit}`)
  2. Call Credit Agent and Collection Agent in parallel with the `customer_id`
  3. Apply this release/block decision logic:
     - If Credit Agent `assessment == HIGH` → BLOCK with `DeliveryBlockReason: "01"` (credit block)
     - If Collection Agent `recommendation == BLOCK` → BLOCK with `DeliveryBlockReason: "01"`
     - If Credit Agent `account_blocked == true` → BLOCK
     - Otherwise → RELEASE (no delivery block)
  4. Create the sales order via MCP (POST /A_SalesOrder) with:
     - `SalesOrderType`, `SalesOrganization`, `DistributionChannel`, `OrganizationDivision`, `SoldToParty` from input
     - `DeliveryBlockReason: "01"` if BLOCK, omit if RELEASE
     - `to_Item`: order line items
  5. Return a structured response:
     ```json
     {
       "sales_order_id": "...",
       "decision": "RELEASE|BLOCK",
       "rationale": "...",
       "credit_assessment": {...},
       "collection_assessment": {...}
     }
     ```
  - Never create an order without first consulting both sub-agents (unless explicitly overridden)
  - Never hallucinate order data — only create orders from user-provided input
  - Always set `top` ≤ 100 on list tool calls

- [ ] Implement `stream()` calling `_run_agent()` and yielding the final structured response
- [ ] Implement `_run_agent()` as a plain async method

## Milestones & Instrumentation

- [ ] Instrument `_run_agent()` with all 5 milestones (M1–M5):
  - `M1.achieved: customer payment assessment initiated for customer {customer_id}`
  - `M1.missed: payment assessment could not be initiated — missing customer_id or input validation failed`
  - `M2.achieved: credit risk evaluated — limit={credit_limit}, utilisation={utilisation_pct}, score={credit_score}` (from credit agent response)
  - `M2.missed: credit risk data unavailable — defaulting to block`
  - `M3.achieved: collection status assessed — overdue={overdue_amount}, broken_promises={broken_promise_count}` (from collection agent response)
  - `M3.missed: collection data unavailable — proceeding with credit-only assessment`
  - `M4.achieved: order decision={decision}, rationale={rationale}`
  - `M4.missed: decision synthesis failed — sub-agent data insufficient`
  - `M5.achieved: sales order created — order_id={order_id}, status={release_or_block}`
  - `M5.missed: sales order creation failed — error={error_message}`
- [ ] Add OTel spans using `@tracer.start_as_current_span("sales_agent.run")` on `_run_agent()`
- [ ] Verify `auto_instrument()` is called at top of `main.py`

## Mock Configuration

- [ ] Generate `mcp-mock.json` using `mcp-mock-config` skill after all MCP specs (Path A and Path B) are confirmed

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=true`
- [ ] Write unit test: mock both sub-agents returning HIGH credit risk → sales order created with `DeliveryBlockReason: "01"`
- [ ] Write unit test: mock both sub-agents returning LOW risk → sales order created with no delivery block
- [ ] Write unit test: collection agent unavailable → defaults to BLOCK
- [ ] Write unit test: credit agent account blocked → defaults to BLOCK
- [ ] Write integration test: full end-to-end flow with mocked sub-agents and mocked LLM — verify `sales_order_id` is returned
- [ ] Mock LLM (ChatLiteLLM) in all tests
- [ ] Mock sub-agent A2A calls (`_call_credit_agent`, `_call_collection_agent`) to return canned responses
- [ ] Run `pytest` from `assets/sales-agent/` — coverage ≥ 70%
- [ ] Run `pytest` (no args) to generate final `test_report.json`
- [ ] Verify `test_report.json` exists in `assets/sales-agent/`
- [ ] Run validation checklist from guidelines-agent.md
