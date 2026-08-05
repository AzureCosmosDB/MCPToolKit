# Declarative Business Tools (vNext)

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

See [`samples/banking/cosmos-tools.yaml`](../../samples/banking/cosmos-tools.yaml) for a full,
working configuration covering point reads, queries, vector search, creates, and a transactional batch.
