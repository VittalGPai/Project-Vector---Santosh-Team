# Specification

> **Guidelines**: Read [guidelines.md](./guidelines.md) before executing ANY tasks below.

Check off items as completed.

## Solution Setup

- [x] Create asset directories:
  ```bash
  mkdir -p assets/credit-agent assets/collection-agent assets/sales-agent
  ```
- [x] Invoke `setup-solution` skill to create `solution.yaml` and `asset.yaml` files for all three agents:
  - `credit-agent` (AI Agent)
  - `collection-agent` (AI Agent)
  - `sales-agent` (AI Agent, orchestrator)
- [x] Validate all `asset.yaml` and `solution.yaml` files exist and are well-formed

## Asset Implementation

Execute in this order (Credit Agent and Collection Agent first — they are dependencies of Sales Agent):

- [x] Execute specification/credit-agent/specification.md (all items)
- [x] Execute specification/collection-agent/specification.md (all items)
- [x] Execute specification/sales-agent/specification.md (all items)

## Cross-Implementation Compatibility Check

After all three agents are implemented:

- [x] Verify Credit Agent A2A endpoint is reachable at `/.well-known/agent.json` and accepts `{"customer_id": "...", "credit_segment": "..."}` input
- [ ] Verify Collection Agent A2A endpoint is reachable at `/.well-known/agent.json` and accepts `{"customer_id": "..."}` input
- [ ] Verify Sales Agent calls Credit Agent via `CREDIT_AGENT_URL` env var and Collection Agent via `COLLECTION_AGENT_URL` env var
- [ ] Verify Sales Agent structured response contains `sales_order_id`, `decision`, `rationale`, `credit_assessment`, `collection_assessment`
- [ ] Verify all milestone log statements (M1–M5) are emitted in a full end-to-end invocation
- [ ] Verify `test_report.json` exists in all three asset roots
