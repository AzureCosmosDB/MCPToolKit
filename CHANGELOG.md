# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-06-18

### Added
- **`agentic_search` tool**: Runs a multi-turn retrieval agent against a Cosmos
  DB corpus and returns ranked, curated documents that best answer the query.
  Given a query, the agent will (1) issue hybrid (vector + full-text) RRF
  searches, (2) optionally rerank the hits with Qwen3-Reranker-8B, (3) read full
  documents, and (4) prune its context across multiple turns. Implemented as a
  subprocess call into the companion [`cosmos-retriever/`](cosmos-retriever/)
  Python package; see [`docs/AGENTIC_SEARCH.md`](docs/AGENTIC_SEARCH.md) for the
  deployment story.
- Optional `database` and `container` arguments on `agentic_search` so a
  single MCP server can target multiple Cosmos corpora at request time. When
  the corpus registry (`CORPUS_REGISTRY` / `CORPUS_REGISTRY_FILE`) is set
  in the host environment, the matching account, database, and embedding
  model are picked automatically per call.
- New service: `AgenticSearchExecutor` (subprocess lifecycle, timeout, error
  envelope generation).
- New env vars: `COSMOS_RETRIEVER_PYTHON`, `COSMOS_RETRIEVER_DIR`,
  `COSMOS_RETRIEVER_TIMEOUT_S` — see [`.env.example`](.env.example).

### Changed
- `AppState` now also exposes `ILoggerFactory` so static `[McpServerTool]`
  methods can obtain a properly-named logger.

## [1.1.2] - 2026-05-29

### Added
- **Hybrid search tool** (`hybrid_search`): Combines vector similarity and full-text keyword search using Cosmos DB's Reciprocal Rank Fusion (RRF) ranking. Requires both a vector index and a full-text index on the target container (issue #89).
- Added `hybrid_search` to the web testing UI dropdown.

### Changed
- Default `topN`/`n` for `text_search`, `vector_search`, and `hybrid_search` is now 10 (parameter is optional; existing callers unaffected).
- Updated NuGet dependencies:
  - ModelContextProtocol.AspNetCore 0.3.0-preview.4 → 1.3.0
  - Microsoft.Azure.Cosmos 3.53.0 → 3.60.0
  - Azure.Identity 1.12.0 → 1.21.0
  - Azure.AI.OpenAI 2.0.0 → 2.1.0
  - OpenAI 2.0.0 → 2.1.0
  - Microsoft.AspNetCore.Authentication.JwtBearer 9.0.0 → 9.0.16
  - Microsoft.IdentityModel.JsonWebTokens 8.1.2 → 8.18.0
  - Microsoft.IdentityModel.Protocols.OpenIdConnect 8.1.2 → 8.18.0
  - Microsoft.IdentityModel.Tokens 8.1.2 → 8.18.0
  - System.IdentityModel.Tokens.Jwt 8.1.2 → 8.18.0
  - Microsoft.NET.Test.Sdk 17.8.0 → 18.5.1
  - Microsoft.AspNetCore.Mvc.Testing 9.0.0 → 9.0.16
  - FluentAssertions 6.12.0 → 8.10.0

## [1.1.1] - 2026-05-20

### Changed
- Updated release workflow trigger so all `v*` tag pushes reliably create GitHub Releases.
- Added `CONTRIBUTING.md` and linked contribution guidance from the README.

### Fixed
- Added bug-fix issue tracking entries for the latest fixes (excluding issue #89).

## [1.1.0] - 2026-05-20

### Added
- **Multi-provider embedding support**: Vector search now supports Azure AI Services (Cognitive Services), Azure AI Foundry projects, and OpenAI native API.
- **Automatic endpoint detection**: System automatically identifies the embedding endpoint type based on URL pattern.
- New `IEmbeddingClient` abstraction layer with provider-specific implementations.

### Changed
- Enhanced `OPENAI_ENDPOINT` configuration to accept multiple endpoint formats (Azure AI Services, Azure AI Foundry, OpenAI native).
- Updated documentation and environment examples to reflect multi-provider support.

### Fixed
- Fixed token retrieval issues with Azure CLI usage (issue #83).
- Corrected README Client ID field reference in `deployment-info.json` guidance (issue #82).
- Fixed parsing failure in `Assign-Role-To-Users.ps1` query escaping (issue #81).
- Fixed 404 error when downloading `cosmos-mcp-client.html` during web testing (issue #77).
- Added missing JWT token acquisition steps in VS Code MCP setup docs (issue #76).
- Fixed Foundry connection script parameter handling when using project name (issue #75).
- Fixed failures in `scripts/Verify-Role-Assignments.ps1` (issue #74).
- Fixed failures in `scripts/Assign-Role-To-Users.ps1` (issue #73).
- Fixed failures in `scripts/Assign-Role-To-Current-User.ps1` (issue #72).
- Included additional bug fix tracked under issue #60.

## [1.1.0-rc.1] - 2026-05-18

### Added
- Release channel guidance and customer-facing versioning policy in the README.

### Changed
- Added startup validation for `OPENAI_ENDPOINT` to reject Foundry project URLs and provide actionable guidance.
- Trimmed OpenAI configuration values before use to reduce failures caused by accidental whitespace.
- Enabled MCP HTTP transport registration for SDK endpoint mapping.

### Fixed
- Prevented 500 errors during role-denied tool calls by returning a structured 403 JSON-RPC response.
- Restored MCP compatibility for external clients by mapping the SDK endpoint at `/mcp`.
- Moved custom JSON-RPC controller endpoint to `/mcp/http` and updated web UI calls accordingly.
- Renamed vector score alias from `_score` to `score` so Cosmos query results include similarity score.

## [1.0.0] - 2025-09-15

### Added
- Initial version of the Azure Cosmos DB MCP Toolkit.
- Basic MCP server functionality.
- Azure Cosmos DB integration.
- Azure OpenAI integration for vector search.