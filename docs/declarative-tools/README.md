# Declarative Business Tools (vNext)

> ⚠️ **Experimental.** This declarative layer is experimental and may change in a future release.
> It is additive and opt-in (dormant unless you supply a configuration file). Review the security,
> authorization, tenant-isolation, and governance settings before using it in production.

The Azure Cosmos DB MCP Toolkit can expose **business-facing, governed MCP tools** defined in a
YAML (or JSON) file — no bespoke handler code required. This layer is **additive and opt-in**:
if you do not provide a configuration file, the toolkit exposes only its GA built-in tools and
behaves exactly as before.

## Contents

- [YAML configuration reference](./yaml-reference.md) — every field and one example per operation type
- [Security & governance](./security-governance.md) — auth, tenant isolation, RU/timeout budgets
- [GA compatibility matrix](./compatibility-matrix.md) — evidence that existing behavior is unchanged
- [Banking migration walkthrough](./banking-migration.md) — tool-by-tool classification and `bank_transfer` analysis

## What you can define

Point reads, parameterised queries, full-text/vector/hybrid search, create/replace/patch/delete,
optimistic concurrency, transactional batches, and short **Cosmos-only** bounded composition
(`sequence`) with assertions, generated ids, and system timestamps.

It is deliberately **not** a workflow engine, saga orchestrator, or scripting runtime.

## Quick start

1. Author a config file, e.g. `cosmos-tools.yaml`:

   ```yaml
   version: "1.0"
   sources:
     app:
       type: cosmos
       endpoint: "${COSMOS_ENDPOINT}"
       database: "${COSMOS_DATABASE}"
       authentication:
         type: managed-identity
   defaults:
     source: app
     governance:
       readOnly: true          # writes must be explicitly enabled per tool
       timeoutMs: 5000
       maxItems: 100
   tools:
     get_account_balance:
       description: Returns the current balance for an account.
       operation:
         type: point-read
         container: accounts
         id: "${accountId}"
         partitionKey: "${customerId}"
       input:
         type: object
         required: [customerId, accountId]
         properties:
           customerId: { type: string }
           accountId: { type: string }
       output:
         select:
           accountId: accountId
           balance: balance
   ```

2. Point the toolkit at it (either form works):

   ```powershell
   $env:COSMOS_TOOLS_CONFIG = "C:\path\to\cosmos-tools.yaml"
   ```

   or in `appsettings.json`:

   ```json
   { "CosmosMcp": { "ToolsConfigPath": "cosmos-tools.yaml" } }
   ```

3. Start the server. Configured tools appear alongside the built-in tools in `tools/list`.

## Fail-closed behavior

- Writes (`create`, `replace`, `patch`, `delete`, `transactional-batch`, `sequence`) require
  `governance.readOnly: false` on the tool. Read-only is the default.
- `delete` additionally requires `governance.allowDelete: true`.
- An invalid configuration prevents startup with a clear diagnostic — the server never starts
  with a partially valid tool set.
- If `COSMOS_TOOLS_CONFIG` points at a missing file, startup fails rather than silently ignoring it.

## A complete example

The toolkit engine is **domain-agnostic** — it executes whatever a config file describes. See the
[samples overview](../../samples/README.md), which includes two configs built on the identical engine
with no code differences:

- [`samples/banking/cosmos-tools.yaml`](../../samples/banking/cosmos-tools.yaml) — retail banking
  (hierarchical partition keys, tenant isolation, point-read, query, vector-search, create, transactional-batch).
- [`samples/ecommerce/cosmos-tools.yaml`](../../samples/ecommerce/cosmos-tools.yaml) — a different
  domain (catalog/orders) using point-read, query, hybrid-search, patch with an allow-list, and a
  bounded `sequence` with an assertion.

Anything expressible with the supported operation types works for any Cosmos-backed application.
