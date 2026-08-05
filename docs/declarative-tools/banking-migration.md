# Banking Multi-Agent Workshop — Migration Walkthrough

This document classifies the Banking workshop's MCP tools and records how each maps to the
declarative toolkit. Source analyzed: the workshop `mcp` branch
(`csharp/src/BankingAPI/Services/BankingDataService.cs`, the Semantic Kernel plugins, and
`python/src/app/tools/mcp_server.py`).

## Data model

- Container **`accounts`** — hierarchical partition key **`[tenantId, accountId]`**, `type`
  discriminator (`BankAccount`, `BankTransaction`, `ServiceRequest`).
- Container **`offers`** — partition key **`[tenantId]`**, holds `Offer` and `OfferTerm` (with a
  `Vector` embedding property).

## Tool classification

| Tool | Purpose | Backend | Uses Cosmos | Complexity | Declarative today | Target form | Recommended location | Reason |
|---|---|---|:--:|---|:--:|---|---|---|
| `bank_balance` | Read one account | Cosmos | ✅ | simple data op | ✅ | `point-read` | Cosmos MCP Toolkit | Direct point read on `[tenantId, accountId]` |
| `get_transaction_history` | List account transactions between dates | Cosmos | ✅ | simple data op | ✅ | `query` (parameterised, partition-scoped) | Cosmos MCP Toolkit | Pure parameterised query |
| `get_offer_information` | Semantic search of product offers | Cosmos (+embeddings) | ✅ | simple data op | ✅ | `vector-search` | Cosmos MCP Toolkit | Embedding + vector search on `offers` |
| `create_account` | Open a new account | Cosmos | ✅ | simple data op | ✅ | `create` (write opt-in) | Cosmos MCP Toolkit | Single document create |
| `service_request` | File a service request | Cosmos | ✅ | simple data op | ✅ | `create` (write opt-in) | Cosmos MCP Toolkit | Single document create |
| `bank_transfer` | Request a funds transfer | Cosmos | ✅ | constrained compound | ✅ (request form) | `create` (request) + `transactional-batch` demo | Cosmos MCP Toolkit | See analysis below |
| `calculate_monthly_payment` | Loan math | pure calculation | ❌ | simple calc | n/a | stays code | Banking MCP Server | No Cosmos involvement |
| `get_branch_location` | Branch lookup by state | static data | ❌ | simple data | n/a | stays code | Banking MCP Server | Static/non-Cosmos data |
| `transfer_to_*_agent` | Agent hand-off | agent framework | ❌ | orchestration | n/a | stays code | Host / agent framework | Not a data operation |
| `health_check` | Liveness | n/a | ❌ | n/a | n/a | stays code | Either server | Infra concern |

The migrated Cosmos-backed tools are implemented in
[`samples/banking/cosmos-tools.yaml`](../../samples/banking/cosmos-tools.yaml) and verified by
`BankingSampleConfigTests` and the emulator integration tests.

## `bank_transfer` — detailed analysis

`bank_transfer` is Cosmos-backed and is treated as a first-class case (not excluded for containing
business logic).

**Reads/writes involved in a "real" transfer:** read source account, validate funds, debit source,
credit destination, create a transaction record.

**Partition reality:** the `accounts` container is partitioned by `[tenantId, accountId]`. The
source and destination are **different `accountId` values → different logical partitions**.

1. **Can it be one transactional batch?** **No.** A Cosmos transactional batch is scoped to a single
   logical partition. Debit (source partition) + credit (destination partition) span two partitions,
   so they cannot be one atomic batch under this (unchanged, GA) partition design.
2. **Can it be bounded Cosmos-only composition?** Partially. A `sequence` can read-validate-debit-credit
   with optimistic concurrency and bounded compensation, but it is **not atomic** across the two
   partitions — a crash between debit and credit needs compensation, which is best-effort.
3. **What exact primitive would make it atomic?** A cross-partition (multi-partition) ACID
   transaction / two-phase commit.
4. **Is that in scope for a Cosmos toolkit?** **No.** Azure Cosmos DB does not provide cross-partition
   ACID transactions; providing one would require a cross-system saga/2PC engine, which the product
   boundary explicitly excludes.
5. **Conclusion:** the workshop's **request-based** model is the correct, fully-declarative
   representation and is what we migrate: `bank_transfer` records a `FundTransfer` service request
   (a single create in the source account's partition) that is fulfilled asynchronously. This is the
   `bank_transfer` tool in the sample.

To still demonstrate atomic multi-write capability, the sample also provides
`post_account_transaction`, a **transactional batch** that adjusts a balance **and** appends the
matching transaction record atomically — valid precisely because both writes share one logical
partition. This is exercised end-to-end against the emulator in
`EmulatorIntegrationTests.Transactional_batch_adjusts_balance_and_records_transaction`.

## Semantic differences to note

- `get_offer_information` is scoped to the tenant partition; the workshop additionally filters
  `type = 'Term'` and `accountType`. Those metadata filters can be layered on with a filtered
  `VectorDistance` query if strict parity is required.
- Identity fields (`tenantId`) are enforced from the caller's token claim (`tid`) rather than trusted
  from the model, which is a security improvement over passing `tenantId` as a plain argument.

## Single vs. multiple MCP servers

The host aggregates two sibling servers:

- **Cosmos DB MCP Toolkit** — serves the Cosmos-backed configured tools above.
- **Banking MCP Server** — retains genuinely out-of-scope tools (`calculate_monthly_payment`,
  `get_branch_location`, agent hand-offs).

The Banking server does **not** proxy the Cosmos toolkit; both are exposed to the host directly.
