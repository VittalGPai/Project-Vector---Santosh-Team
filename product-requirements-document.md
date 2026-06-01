# Product Requirements Document (PRD)

**Title:** Sales Agent with Credit & Collection Intelligence  
**Date:** 2026-05-30  
**Owner:** Sales Operations / Order Management  
**Solution Category:** AI Agent

---

## Product Purpose & Value Proposition

**Elevator Pitch:**  
A Sales Agent autonomously assesses a customer's creditworthiness and collection history — including broken promises to pay — by delegating to a Credit Agent and a Collection Agent before creating a sales order in SAP S/4HANA. The order is automatically released or blocked based on the synthesised risk signal, removing manual credit-check friction from the sales process.

**Business Need:**  
Sales representatives currently create orders without a real-time view of a customer's credit exposure or collection history. Credit blocks are often applied after the fact, causing downstream fulfilment delays and disputes. Broken promises to pay are rarely surfaced at order entry time.

**Expected Value:**  
- Reduce post-creation credit blocks and associated rework.  
- Surface broken promise-to-pay records at the moment of order creation.  
- Accelerate order-to-fulfillment cycle by applying release/block decisions at creation time.

**Product Objectives (Prioritized):**  
1. Dynamically assess credit risk and collection status before every sales order is created.  
2. Create the sales order in SAP S/4HANA with the correct release or delivery-block status in a single agent interaction.  
3. Provide a transparent, auditable rationale for the release/block decision.

---

## Requirements

### Must-Have Requirements

**R1: Credit Risk Consultation**  
- **User Story**: As a Sales Agent, I need to query the Credit Agent for a customer's credit limit, utilisation, and creditworthiness so that I can factor credit exposure into the order decision.  
- **Acceptance Criteria**:  
  - Given a customer ID, when the Credit Agent is invoked, then credit limit, utilised amount, and credit score are returned.  
- **Priority Rank**: 1

**R2: Collection Status & Broken Promises Consultation**  
- **User Story**: As a Sales Agent, I need to query the Collection Agent for open receivables, overdue items, and broken promise-to-pay records so that repeated non-payment behaviour is detected before order creation.  
- **Acceptance Criteria**:  
  - Given a customer ID, when the Collection Agent is invoked, then overdue balance, number of broken promises, and most recent promise date are returned.  
- **Priority Rank**: 2

**R3: Release / Block Decision Logic**  
- **User Story**: As a Sales Agent, I need to synthesise Credit Agent and Collection Agent outputs into a single release or block recommendation so that the sales order is created with the correct status.  
- **Acceptance Criteria**:  
  - Given both sub-agent responses, when the Sales Agent evaluates them, then it returns either "release" or "block" with a one-sentence rationale.  
- **Priority Rank**: 3

**R4: Sales Order Creation in SAP S/4HANA**  
- **User Story**: As a Sales Agent, I need to create a sales order via the Sales Order MCP server with the release or delivery-block flag applied so that no manual follow-up is needed.  
- **Acceptance Criteria**:  
  - Given the release/block decision, when the order is created, then the S/4HANA order number is returned and the correct block status is set.  
- **Priority Rank**: 4

---

## Solution Architecture

**Architecture Overview:**  
Three Python-based A2A agents deployed on SAP BTP AI Core. The Sales Agent is the orchestrator; it invokes the Credit Agent and Collection Agent as sub-agents, then calls the Sales Order MCP server to create the order.

**Key Components:**
- **Sales Agent** — Orchestrator; receives order request, delegates to sub-agents, decides release/block, creates order.
- **Credit Agent** — Sub-agent; calls the Credit Management MCP server (`sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1`) to retrieve credit account data.
- **Collection Agent** — Sub-agent; calls the Promise-to-Pay API (`sap.s4:apiResource:PROMISETOPAYIDQR:v1`) and Credit Account Read API (`sap.s4:apiResource:CREDITMANAGEMENTACCOUNTBYIDQU1:v1`) to retrieve overdue items and broken promises.
- **Sales Order MCP Server** (`sap.mcpbuilder:apiResource:sales_order_mcp_demo:v1`) — Used by Sales Agent to create the order with the correct status.

**Integration Points:**
- SAP S/4HANA Credit Management — read credit limit, utilisation, score (via MCP server).
- SAP S/4HANA Collections — read promise-to-pay and overdue items (via direct API, no MCP server available).
- SAP S/4HANA Sales Order API — create order with release or delivery block (via MCP server).

### Agent Extensibility & Instrumentation

**Agent Extensibility:**
- The Sales Agent must expose extension points so that additional risk checks (e.g. compliance holds, trade sanctions) can be plugged in without modifying core orchestration logic.
- The Credit Agent and Collection Agent must be independently replaceable to allow future integration with external credit bureaus or collection platforms.

**Business Step Instrumentation:**
All milestones emit structured logs following the pattern `[MILESTONE_ID].[achieved|missed]: [description]`.

### Automation & Agent Behaviour

**Automation Level:** Autonomous agent with deterministic rule-based decision for release/block.

**Actions the system performs without human approval:**
- Query credit account data for a customer.
- Query promise-to-pay and overdue receivables for a customer.
- Create a sales order with release or delivery-block status.

**Actions that require human review or approval:**
- Override of an agent-recommended block (out of scope for this release; escalation path TBD).

**Model or engine used:** LLM via SAP Generative AI Hub (GPT-4o or equivalent) for orchestration reasoning; deterministic rule application for release/block threshold.

**Tools or connectors invoked:**
- Credit Management MCP server — read-only, retrieves credit account.
- Promise-to-Pay API — read-only, retrieves P2P records and broken promise history.
- Credit Account Read API — read-only, retrieves overdue open items.
- Sales Order MCP server — write, creates sales order with status flag.

**Guardrails & fail-safes:**
- If Credit Agent returns no data, default to block and log `credit-data-unavailable`.
- If Collection Agent returns no data, proceed with credit-only assessment and log `collection-data-unavailable`.
- The agent must never modify existing sales orders or financial records.
- If the S/4HANA order creation fails, the agent must surface the error without silent retry.

---

## Milestones

### M1: Customer Payment Assessment Initiated
- **Description**: Sales Agent receives an order request and begins parallel consultation.
- **Achieved when**: Credit Agent and Collection Agent calls are both dispatched.
- **Log on achievement**: `M1.achieved: customer payment assessment initiated for customer {customer_id}`
- **Log on miss**: `M1.missed: payment assessment could not be initiated — missing customer_id or input validation failed`

### M2: Credit Risk Evaluated
- **Description**: Credit Agent has returned credit limit, utilisation, and creditworthiness score.
- **Achieved when**: Credit Agent response is received with non-empty credit data.
- **Log on achievement**: `M2.achieved: credit risk evaluated — limit={credit_limit}, utilisation={utilisation_pct}, score={credit_score}`
- **Log on miss**: `M2.missed: credit risk data unavailable — defaulting to block`

### M3: Collection Status & Broken Promises Assessed
- **Description**: Collection Agent has returned overdue balance and broken promise-to-pay count.
- **Achieved when**: Collection Agent response is received with receivables data.
- **Log on achievement**: `M3.achieved: collection status assessed — overdue={overdue_amount}, broken_promises={broken_promise_count}`
- **Log on miss**: `M3.missed: collection data unavailable — proceeding with credit-only assessment`

### M4: Release / Block Decision Made
- **Description**: Sales Agent synthesises sub-agent outputs and produces a release or block decision with rationale.
- **Achieved when**: A decision of "release" or "block" is emitted with a non-empty rationale string.
- **Log on achievement**: `M4.achieved: order decision={decision}, rationale={rationale}`
- **Log on miss**: `M4.missed: decision synthesis failed — sub-agent data insufficient`

### M5: Sales Order Created in SAP S/4HANA
- **Description**: Sales order is successfully created in S/4HANA with the correct status.
- **Achieved when**: Sales Order MCP server returns a valid order number.
- **Log on achievement**: `M5.achieved: sales order created — order_id={order_id}, status={release_or_block}`
- **Log on miss**: `M5.missed: sales order creation failed — error={error_message}`
