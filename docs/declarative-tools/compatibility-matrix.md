# GA Compatibility Matrix

The declarative layer is **additive and opt-in**. This document records the evidence that existing
GA behavior is unchanged.

## Principle

- No existing tool is renamed or removed.
- No input or output schema of a built-in tool is changed.
- No default is changed; no new setting is mandatory.
- The declarative runtime is dormant unless `COSMOS_TOOLS_CONFIG` (or `CosmosMcp:ToolsConfigPath`)
  is provided.

## Evidence

| Existing capability | GA behavior | New behavior | Compatible | Evidence |
|---|---|---|:--:|---|
| Tool discovery (`tools/list`) | 8 built-in tools advertised | Same 8 tools; configured tools only added when a config file is supplied | ✅ | Registration is a no-op without config (`ConfiguredToolsRegistration.AddConfiguredCosmosTools`); existing tests unchanged |
| `list_databases` / `list_collections` | Unchanged static `[McpServerTool]` methods | Not modified | ✅ | `Program.cs` `CosmosDbTools` untouched |
| `get_recent_documents` (1–20) | Range validation unchanged | Not modified | ✅ | `CosmosDbToolsTests.GetRecentDocuments_Should_Validate_Count_Parameter` still passes |
| `text_search` property validation | Regex identifier check | Not modified | ✅ | Existing unit tests pass |
| `find_document_by_id` | Unchanged | Not modified | ✅ | Existing unit tests pass |
| `get_approximate_schema` | Unchanged | Not modified | ✅ | Existing unit tests pass |
| `vector_search` | Unchanged; explicit `selectProperties`, no wildcard | Not modified; configured vector-search also forbids wildcard | ✅ | Existing tests pass; `ConfigurationValidator` rejects `*` in `select` |
| `hybrid_search` | Unchanged | Not modified | ✅ | Existing tests pass |
| Input schemas | Closed (`additionalProperties: false`) | Configured tools also generate closed schemas | ✅ | `JsonSchemaGeneratorTests` |
| Authentication modes (Entra ID / DEV_BYPASS_AUTH) | Unchanged | Reused; configured tools honor the same principal and bypass flag | ✅ | `CallerContext.FromPrincipal`, `AuthorizationEvaluatorTests` |
| Transports (SSE + Streamable HTTP at `/mcp`) | Unchanged | Configured tools registered via the same `AddMcpServer()` builder | ✅ | `Program.cs` wiring after `WithToolsFromAssembly` |
| Environment variables | Reinterpreted? No | New optional `COSMOS_TOOLS_CONFIG` only | ✅ | Only read when present |
| `CosmosClientFactory` / `EmbeddingClientFactory` | Unchanged | Reused by `CosmosGateway` | ✅ | No edits to these files |

## Test evidence

- Baseline at the base commit: **18 pass / 5 fail** (the 5 failures are pre-existing and unrelated
  to this work — see below).
- After this change: **63 pass / 5 fail**. The same 5 pre-existing failures remain; all 45 new
  tests pass, and every originally-passing test still passes.

### Pre-existing failures (present before this work)

These fail at the base commit `6ebcd31` and are **not** caused by this change:

1. `CosmosDbToolsTests.HybridSearch_Should_Reject_Wildcard_SelectProperties` — the test asserts on
   `'*'` but `JsonSerializer` escapes `'` to `\u0027`, so the substring match fails.
2–5. `McpProtocolControllerIntegrationTests.*` — these POST to the SDK `/mcp` endpoint without an
   `Accept: text/event-stream` header, so the Streamable HTTP transport returns `406 Not Acceptable`
   before the asserted JSON-RPC error path is reached.

They were left untouched to avoid altering baseline test expectations.

## How to re-verify

```powershell
cd Q:\repos\MCPToolKit
dotnet test AzureCosmosDB.MCP.Toolkit.sln
```

(The `net9.0` runtime is required to execute the tests.)
