# Spec: Emit per-tool identifier via CosmosClient `ApplicationName`

Status: **Proposed**
Owner: (assign on merge)
Related issue: (link on file)

## Problem

`DailyUserAgentSummary.UserAgent` in our telemetry pipeline is the only field
downstream dashboards can bucket by. Today the dashboard cannot break down
Cosmos DB MCP Toolkit calls by tool, because every one of the 8 tools in
`[McpServerToolType] CosmosDbTools` constructs its `CosmosClient` with the
same hardcoded `ApplicationName`:

```csharp
using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
{
    ApplicationName = "AzureCosmosDBMCP"
});
```

The tool name is only present in `ILogger` messages (e.g.
`_logger.LogInformation("Listing databases from Cosmos DB")` in
[`CosmosDbToolsService.cs`](../../src/AzureCosmosDB.MCP.Toolkit/Services/CosmosDbToolsService.cs))
and in the MCP protocol receive log (`"Received MCP tool call: {ToolName}"`).
Those go to stdout / Container Apps logs / App Insights — **not** into the
Cosmos SDK UserAgent that surfaces in `DailyUserAgentSummary.UserAgent`.

**Result:** the per-tool signal simply is not present in the telemetry the
dashboard reads, so the page cannot break down by tool.

## Goal

Make each Cosmos DB call from an MCP tool carry a tool-specific
`ApplicationName` so `DailyUserAgentSummary.UserAgent` becomes parseable per
tool. Enable a dashboard tile like "requests per tool per day".

## Non-goals

- Refactoring the 8 tool methods to share a helper (out of scope; keeping
  diff minimal for cherry-pick).
- Adding a new logging pipeline or App Insights custom dimension.
- Changing the singleton `CosmosClient` built by
  [`CosmosClientFactory`](../../src/AzureCosmosDB.MCP.Toolkit/Services/CosmosClientFactory.cs).
  That client is used by `CosmosDbToolsService` (not by the shipped
  `[McpServerTool]` methods), and a singleton fundamentally cannot carry a
  per-tool `ApplicationName`. See "Limitations" below.

## Format

**`ApplicationName = "AzureCosmosDBMCP-<tool>"`**

- Base: `AzureCosmosDBMCP` (unchanged; preserves back-compat for any legacy
  KQL still matching the substring).
- Separator: `-` (dash). Avoids collision with `/` and `,` which the Cosmos
  SDK already uses in its own UA segments, and produces an unambiguous regex.
- Tool: lower-kebab-case (MCP-idiomatic), derived from the C# method name.

### Mapping (C# method → `ApplicationName` value)

| Method (`Program.cs`) | `ApplicationName` |
|---|---|
| `ListDatabases`         | `AzureCosmosDBMCP-list-databases` |
| `ListCollections`       | `AzureCosmosDBMCP-list-collections` |
| `GetRecentDocuments`    | `AzureCosmosDBMCP-get-recent-documents` |
| `TextSearch`            | `AzureCosmosDBMCP-text-search` |
| `FindDocumentByID`      | `AzureCosmosDBMCP-find-document-by-id` |
| `GetApproximateSchema`  | `AzureCosmosDBMCP-get-approximate-schema` |
| `VectorSearch`          | `AzureCosmosDBMCP-vector-search` |
| `HybridSearch`          | `AzureCosmosDBMCP-hybrid-search` |

## Implementation

Change one line in each of the 8 `[McpServerTool]` methods in
[`Program.cs`](../../src/AzureCosmosDB.MCP.Toolkit/Program.cs) — replace the
hardcoded `"AzureCosmosDBMCP"` string with the tool-specific value from the
table above. No new files, no helper extraction, no signature changes. The
`using var client = new CosmosClient(...)` pattern stays as-is.

Adding a new `[McpServerTool]` in the future requires appending its
kebab-case name to the `ApplicationName` at its construction site. A brief
comment near the first modified site documents the convention.

## KQL

Once the change ships, the parseable tile query is:

```kusto
DailyUserAgentSummary
| where UserAgent has "AzureCosmosDBMCP-"
| extend Tool = extract(@"AzureCosmosDBMCP-([a-z][a-z0-9-]*)", 1, UserAgent)
| where isnotempty(Tool)
| summarize Requests = sum(Count) by Tool, bin(Date, 1d)
| render columnchart
```

The regex `AzureCosmosDBMCP-([a-z][a-z0-9-]*)` is anchored to the
lower-kebab tool segment and stops at the next non-`[a-z0-9-]` character
(SDK UA segments are typically delimited by `|` or `/`).

## Limitations

- **Singleton client in `CosmosClientFactory`** — the DI-registered
  `CosmosClient` built in
  [`CosmosClientFactory.BuildClientOptions`](../../src/AzureCosmosDB.MCP.Toolkit/Services/CosmosClientFactory.cs)
  keeps its base `ApplicationName = "AzureCosmosDBMCP"` (no tool suffix).
  This is used by `CosmosDbToolsService`, which is not on the MCP tool path
  today. If those code paths are ever wired to `[McpServerTool]` methods,
  the singleton must be replaced with a factory that mints a per-tool client
  (or a per-tool `RequestOptions.ApplicationName`, if the SDK exposes it) —
  otherwise the per-tool telemetry signal will disappear again.
- **UA length budget** — the Cosmos SDK truncates or drops overly long UA
  strings. `AzureCosmosDBMCP-<longest tool>` is well under any practical
  limit today, but new tool names should stay short.

## Rollout

1. Land this change on `main`.
2. Wait for one Container Apps deployment cycle so telemetry starts flowing
   with the new UA suffixes.
3. Add the dashboard tile using the KQL above.
4. Backfill / merge-out any old dashboard queries that assumed
   `UserAgent == "AzureCosmosDBMCP"` exact-match.
