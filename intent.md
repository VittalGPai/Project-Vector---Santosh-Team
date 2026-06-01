# Sales Agent with Credit & Collection Intelligence

## Business challenge

A Sales Agent must assess customer payment behavior — including broken promises to pay — by dynamically consulting a Credit Agent and a Collection Agent before creating a sales order in SAP S/4HANA and determining whether it should be released or placed in a blocked status.

## Key Milestones

1. **Customer Payment Assessment Initiated** — Sales Agent receives a sales order request and triggers parallel consultation with Credit Agent and Collection Agent.
2. **Credit Risk Evaluated** — Credit Agent retrieves credit account data, credit limit utilisation, and creditworthiness score for the customer from S/4HANA Credit Management.
3. **Collection Status & Broken Promises Assessed** — Collection Agent retrieves open receivables, overdue items, and any broken promise-to-pay records for the customer.
4. **Release/Block Decision Made** — Sales Agent synthesises inputs from both sub-agents and determines whether the order should be released or blocked.
5. **Sales Order Created in S/4HANA** — Sales Agent creates the sales order via the Sales Order API with the appropriate delivery block or release status applied.

## Business Architecture (RBA)

### End-to-End Process
Lead to Cash (generic)

### Process Hierarchy
```
Lead to Cash (generic)
└── Order to Fulfill (generic)
    └── Manage customer orders and contracts (BPS-361)
        └── Manage customer orders
└── Invoice to Cash (generic)
    └── Process accounts receivables and collect payment (BPS-366)
        └── Manage customer credit risk
        └── Manage and process collections
```

### Summary
The challenge spans two sub-processes of Lead to Cash: order management (BPS-361) for sales order creation and release/block decision, and accounts receivable management (BPS-366) for credit risk evaluation and collection status — bridged by an AI multi-agent architecture.

## Fit Gap Analysis

| Requirement | Standard asset(s) found | API ORD ID | MCP Server ORD ID | Gap? | Notes |
|---|---|---|---|---|---|
| Assess customer credit risk & limit | SAP S/4HANA Credit Management (mandatory) | `sap.s4:apiResource:API_CRDTMBUSINESSPARTNER:v1` | `sap.mcpbuilder:apiResource:credit_management_business_partner_mcp_demo:v1` ✓ | No | Credit Agent uses MCP server |
| Retrieve promise-to-pay & broken promises | SAP S/4HANA Collections Management (mandatory) | `sap.s4:apiResource:PROMISETOPAYIDQR:v1` | — | Maybe | No MCP server found; API integration required |
| Retrieve open receivables & overdue items | SAP S/4HANA Collections Management (mandatory) | `sap.s4:apiResource:CREDITMANAGEMENTACCOUNTBYIDQU1:v1` | — | Maybe | Collection Agent calls credit account read API |
| Create sales order with release/block | SAP S/4HANA Sales Order Management (mandatory) | `sap.s4:apiResource:API_SALES_ORDER_SRV:v1` | `sap.mcpbuilder:apiResource:sales_order_mcp_demo:v1` ✓ | No | Sales Agent uses MCP server |
| Multi-agent orchestration (Sales + Credit + Collection) | — | — | — | Yes | Custom AI Agent required; no standard SAP product covers dynamic A2A agent orchestration |

### Key findings
- SAP S/4HANA Cloud (Public and Private) mandatorily covers Credit Management and Sales Order Management — the core data sources are available via standard APIs.
- MCP servers exist for both Credit Management Master Data and Sales Order (A2X), enabling direct tool-call integration without custom REST wrappers.
- The Promise-to-Pay and Collection Agency APIs exist but have no corresponding MCP server; these will require direct API calls or custom MCP tool definitions.
- The multi-agent orchestration pattern (Sales Agent dynamically delegating to Credit Agent and Collection Agent) is a gap that requires a custom AI Agent solution.
- The release/block decision logic must be custom-built inside the Sales Agent based on synthesised sub-agent responses.

## Recommendations

### Multi-Agent AI Solution for Sales Order Credit Gating

#### Executive Summary
Pro-code Python multi-agent with Credit & Collection sub-agents

#### Recommended Solution
Build a Python-based multi-agent system on SAP BTP AI Core using the A2A protocol. The Sales Agent acts as orchestrator, dynamically invoking a Credit Agent (via the Credit Management MCP server) and a Collection Agent (via Promise-to-Pay and Credit Account APIs) before creating the sales order through the Sales Order MCP server with the appropriate release or block status.

#### Recommended solution category
AI Agent

#### Intent fit
92%
