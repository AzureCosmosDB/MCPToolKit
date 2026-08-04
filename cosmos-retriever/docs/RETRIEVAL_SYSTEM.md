# The Retrieval System

This document explains how the **schema-decoupled retrieval layer**
(`cosmos_retriever.retrieval`) works: the layer that turns a *logical* retrieval
request ("search the corpus for X") into safe, parameterised Azure Cosmos DB for
NoSQL queries, executes them, and returns normalised results — **without any
agent-facing code ever touching Cosmos SQL or physical property paths**.

If you only remember one thing: the agent tools speak in *logical fields*
(`text`, `embedding`, `docid`), and a single **`CorpusSchema`** maps those to the
*physical* Cosmos paths (`/text`, `/embedding`, `/docid`) for a given container.
Supporting a brand-new corpus shape is a matter of constructing a schema — no
edits to the tools, planner, or compiler.

---

## 1. Design goals

| Goal | How it's achieved |
|---|---|
| **No hardcoded paths/SQL in tools** | Tools build logical request models; a `CorpusRetriever` façade owns everything physical. |
| **Portability across corpus shapes** | Three separated concerns — *logical schema*, *physical capabilities*, *partition policy* — are supplied per corpus. |
| **Fail loudly, never silently degrade** | Typed errors (`errors.py`); the planner refuses to "try something cheaper" when an index is missing. |
| **Injection-safe queries** | Every value is a bound `@param`; every property path is validated/rendered by `CosmosPath`. |
| **Resilience under load** | The executor bounds concurrency, retries transient Cosmos errors, and logs slow queries. |

---

## 2. The three inputs that describe a corpus

Everything the layer does is driven by three objects you provide once per corpus.

### 2.1 `CorpusSchema` — logical → physical mapping (`schema.py`)
The heart of the system. It says *where each logical field lives*:

```python
CorpusSchema(
    item_id_path="/id",              # unique id of a Cosmos item (a chunk)
    text_paths=["/text"],            # one or more searchable text fields
    primary_text_path="/text",       # the default text field
    vector_fields=[VectorFieldConfig(path="/embedding", dimensions=1536)],
    document_id_path="/docid",       # parent-document id (None => item *is* the document)
    chunk_id_path="/id",
    chunk_order_path="/chunk_idx",   # used to re-assemble a document in order
    partition_key_paths=["/docid"],
    metadata_paths={...},            # optional extra projected fields
)
```

Key behaviours:
- **Named fields.** `text_field_map()` / `vector_field_map()` expose each field by
  its last path segment (`text`, `embedding`), so the agent can pick a field *by
  name* without knowing the path. Collisions fall back to the full path string.
- **`agent_field_summary()`** renders a human-readable list of queryable fields
  (with optional descriptions) that is injected into the tool description shown to
  the model.
- **`resolve_text_fields()` / `resolve_vector_config()`** turn requested field
  *names* into physical `CosmosPath`s, raising `UnknownField` if a name is bogus.
- **`ChunkIdentityCodec`** (attached as `identity_codec`) converts a returned
  chunk id into its parent document id. `LegacyDunderCodec` implements the
  `"<docid>__<chunk_idx>" → "<docid>"` convention.
- **Validation.** A pydantic `model_validator` enforces invariants (e.g.
  `primary_text_path` must be one of `text_paths`, vector dims > 0), raising
  `InvalidCorpusSchema`.

### 2.2 `RetrievalCapabilities` — what the container can *efficiently* do (`capabilities.py`)
The schema says what fields *exist*; capabilities say what the container is
*indexed* to do well:

```python
RetrievalCapabilities(
    vector_fields=[VectorCapability(path="/embedding", dimensions=1536,
                                    support=SupportLevel.INDEXED)],
    full_text_paths=["/text"],
    native_hybrid_supported=True,   # ORDER BY RANK RRF(...) available
    full_text_supported=True,
    vector_supported=True,
    efficient_document_lookup_supported=True,
)
```

`SupportLevel` (`INDEXED` / `SCAN` / `UNSUPPORTED` / `UNKNOWN`) lets the planner
distinguish "indexed and fast" from "possible but a scan". The planner uses this
to choose a strategy and to **refuse** operations that would silently be slow.

### 2.3 `PartitionQueryPolicy` — cross-partition guard-rails (`models.py`)
Controls what the layer is *allowed* to do when a partition key isn't supplied:
`allow_cross_partition_search`, `allow_cross_partition_document_read`,
`allow_bounded_scan`, `maximum_partitions`, etc. This keeps accidental
fan-out/full-scans behind an explicit opt-in.

---

## 3. The request/response models (`models.py`)

These carry **no** SQL or physical knowledge — they are the logical vocabulary
the tools speak:

- **`SearchRequest`** — `query`, optional `query_vector`, `limit`, `text_fields`,
  `vector_field`, `mode` (`auto|hybrid|vector|text`), `filters`,
  `ignored_item_ids` (already-seen chunks to exclude), `partition_key`.
- **`GrepRequest`** — `pattern`, `candidate_limit`, `result_limit`, `text_field`.
- **`ReadDocumentRequest`** — `document_id`/`item_id`, `max_chunks`, `partition_key`.
- **Filters** — `EqualsFilter` / `RangeFilter` / `InFilter` (a discriminated
  union), addressing *logical* field names.
- **`RetrievedItem`** — the normalised hit: `item_id`, `document_id`, `chunk_id`,
  `chunk_order`, `text` (the display text), `text_fields` (every projected text
  field keyed by name), `metadata`, `retrieval_strategy`, `retrieval_channels`,
  `rank`.
- **`NormalizedDocument`** — a reconstructed document: ordered `chunk_texts` +
  `chunk_ids`, with an `assembled` property that concatenates them.
- **`CompiledCosmosQuery`** — the compiler's output: `sql`, bound `parameters`,
  `partition_key`, `enable_cross_partition_query`, `projected_aliases`.

---

## 4. The pipeline

A single `CorpusRetriever.search()` call flows through six stages:

```mermaid
flowchart LR
    A[SearchRequest<br/>logical] --> B[RetrievalPlanner<br/>pick strategy]
    B --> C[SearchStrategy<br/>resolve fields]
    C --> D[CosmosQueryCompiler<br/>build safe SQL]
    D --> E[CosmosExecutor<br/>run + retry]
    E --> F[normalize_rows<br/>rows -> items]
    F --> G[list RetrievedItem]
```

### 4.1 `CorpusRetriever` — the façade (`retriever.py`)
The one object the agent tools depend on. It wires together the schema,
capabilities, planner, compiler, executor, strategies, and the document resolver,
and exposes exactly three methods:

- **`search(SearchRequest) -> list[RetrievedItem]`** — validates any explicitly
  requested field names up front (so an unknown field raises rather than silently
  falling back), asks the planner for a strategy, lazily embeds the query if the
  strategy needs a vector and none was supplied, then executes.
- **`grep_candidates(GrepRequest) -> list[RetrievedItem]`** — full-text candidate
  fetch used as the pool for client-side regex filtering.
- **`read_document(ReadDocumentRequest) -> NormalizedDocument`** — reconstruct a
  full document via the configured resolver.

### 4.2 `RetrievalPlanner` — strategy selection (`planner.py`)
Turns *request + schema + capabilities + policy* into a concrete strategy. It
never equates "the query didn't throw" with "the operation is indexed":

- `_vector_ok()` — vector search is viable only if the field exists, is
  `vector_supported`, its capability is `INDEXED`, **and stored dimensions match
  the schema's** (guards embedding-profile mismatches).
- `_fts_ok()` — full-text is viable only if every requested text path is a
  declared `full_text_path`.
- **`plan_search()`** honours `mode`:
  - `vector` / `text` → force that channel (raise `UnsupportedRetrievalCapability`
    if unavailable);
  - `hybrid` → `NativeHybridStrategy` if native RRF is supported, else
    `ClientSideFusionStrategy`;
  - `auto` → native hybrid → client-side fusion → vector-only → text-only →
    bounded scan (if policy allows) → else raise.
- **`plan_grep()`** → `FullTextGrepCandidateStrategy` when full-text is available.

### 4.3 Strategies — how each search actually runs (`strategies.py`)
All strategies share a `RetrievalContext` (schema, compiler, executor,
capabilities, policy) and return `list[RetrievedItem]`.

| Strategy | What it emits | Notes |
|---|---|---|
| `NativeHybridStrategy` | `ORDER BY RANK RRF(VectorDistance(...), FullTextScore(...))` | Server-side Reciprocal Rank Fusion; multi-field FTS supported. |
| `VectorSearchStrategy` | `ORDER BY RANK VectorDistance(...)` | Pure semantic. |
| `FullTextSearchStrategy` | `ORDER BY RANK FullTextScore(...)` (RRF if multi-field) | Pure keyword/BM25. |
| `ClientSideFusionStrategy` | Runs vector + FTS, fuses with RRF (`k=60`) in Python | Fallback when the container lacks native RRF. |
| `BoundedScanStrategy` | Filter-only query, no ranking | Opt-in via `allow_bounded_scan`; last resort. |
| `FullTextGrepCandidateStrategy` | FTS candidate pool for grep | Feeds client-side regex. |

Cross-partition safety: `_resolve_cross_partition()` decides whether a query may
fan out, raising `CrossPartitionQueryDisabled` when policy forbids it.

### 4.4 `CosmosQueryCompiler` — safe SQL generation (`compiler.py`)
Builds the actual Cosmos SQL. Everything hostile-to-inject is parameterised or
path-validated:

- **`_ParamBag`** collects bound `@p0, @p1, …` parameters; no value is ever string-interpolated.
- **`projection()`** builds the `SELECT`, projecting logical columns (`item_id`,
  `text`, `document_id`, `chunk_order`, …), plus every text field as `txt_<i>` and
  every metadata field as `md_<key>`. It returns an **alias legend** so the
  normaliser can map columns back to field names.
- **`_where()`** compiles filters and appends the `ignored_item_ids` exclusion
  (`NOT ARRAY_CONTAINS(@ids, c.<item_id>)`).
- **`compile_hybrid` / `compile_vector` / `compile_full_text` / `compile_structured`
  / `compile_document_read`** each return a `CompiledCosmosQuery`.
- Physical paths are rendered through `CosmosPath.render()` (see §5), never raw strings.

### 4.5 `CosmosExecutor` — the single DB chokepoint (`executor.py`)
Every query in the system goes through `_query_items()`, which provides:

- **Bounded concurrency** — a process-wide `BoundedSemaphore`
  (`COSMOS_QUERY_MAX_CONCURRENCY`, default 8) caps simultaneous Cosmos calls.
- **Retries** — `@tenacity.retry` (5 attempts, exponential backoff 4–15 s) on
  transient Cosmos statuses (408/429/449/500/502/503/504).
- **Partition routing** — passes `partition_key` when known, else
  `enable_cross_partition_query=True`.
- **Slow-query logging** — warns when a query exceeds ~4.5 s.

### 4.6 `normalize_rows` — raw rows → `RetrievedItem` (`normalization.py`)
Maps the projected aliases back into structured items:

- `md_*` columns → `metadata`.
- `txt_*` columns → `text_fields` (keyed by the real field name via the alias legend).
- **Display text** (`_display_text`) returns the field(s) the caller actually
  queried, and *also* appends the configured primary field if it wasn't already
  included — so a keyword hit on a title still shows the body text too.

---

## 5. Path safety (`paths.py`)

`CosmosPath` parses a `"/a/b"` path into validated segments and rejects anything
unsafe (bad characters, injection attempts), raising `UnsafeCosmosPath`. It
renders to `c.a.b` against the query alias. Because **every** physical path in a
compiled query flows through `CosmosPath`, a malicious or malformed schema path
cannot produce injectable SQL.

## 6. Text processing (`expressions.py`)

`tokenize_for_fts()` lower-cases, strips a stopword list, de-duplicates, and caps
at 30 terms; `fts_literal_args()` escapes each term into the quoted argument list
that `FullTextScore(path, "t1", "t2", …)` expects.

The stopword list is **English-only**. Tokenization itself is Unicode-aware, so
non-English queries are still tokenized, lower-cased, de-duplicated, and searched
— their function words just aren't removed. The only degenerate case is a query
made entirely of English stopwords, which can reduce to zero terms. Add
per-language stopword lists in `expressions.py` if broader support is needed.

## 7. Document reconstruction (`document_resolvers.py`)

`read_document` reassembles a full document from its chunks. The factory
`build_document_resolver()` picks the right resolver from the schema:

| Resolver | When | How |
|---|---|---|
| `ItemIsDocumentResolver` | `document_id_path is None` (item *is* the doc) | Single-item lookup. |
| `ChunkedDocumentResolver` | partition key **is** the document id | Partition-scoped read, ordered by `chunk_order`. |
| `CrossPartitionChunkedDocumentResolver` | docid ≠ partition key | Cross-partition read (requires policy permission). |

All derive the parent id via the schema's identity codec and sort chunks by
`chunk_order` before assembly (default cap `DEFAULT_MAX_CHUNKS = 300`).

## 8. Typed errors (`errors.py`)

`RetrievalError` subclasses make every failure mode explicit instead of degrading:
`InvalidCorpusSchema`, `UnsafeCosmosPath`, `UnsupportedRetrievalCapability`,
`UnknownField`, `EmbeddingProfileMismatch`, `CrossPartitionQueryDisabled`,
`UnboundedScanRejected`, `DocumentResolutionUnsupported`, `QueryCompilationError`,
`IndexNotReady`, `MissingPartitionKey`.

## 9. The default profile (`legacy.py`)

The MCP server must work out-of-the-box against the conventional chunked corpus
(`/id`, `/text`, `/embedding`, `/docid`, `/chunk_idx`, `<docid>__<chunk_idx>`
chunk ids, native RRF hybrid). `legacy.py` packages exactly that as a named
profile:

- `build_legacy_schema()` → the standard `CorpusSchema` (+ `LegacyDunderCodec`),
- `legacy_capabilities_for()` → capabilities with native hybrid enabled,
- `build_legacy_retriever()` → a ready `CorpusRetriever`.

`ToolSet.build()` calls `build_legacy_retriever()` when no explicit retriever is
supplied, so existing deployments keep working while custom corpora can pass their
own schema.

---

## 10. Adding a new corpus (recipe)

1. Write a `CorpusSchema` mapping your logical fields to physical paths.
2. Attach an identity codec if your chunk ids encode the parent doc id.
3. Declare a `RetrievalCapabilities` describing indexed vector/full-text support.
4. Build a `CorpusRetriever(container, schema, capabilities, query_embedder)`.
5. Pass it to `ToolSet.build(retriever=...)`.

No changes to tools, planner, compiler, executor, or resolvers are required.

## 11. Module map

| File | Responsibility |
|---|---|
| `schema.py` | `CorpusSchema`, `VectorFieldConfig`, identity codec, field resolution |
| `capabilities.py` | `RetrievalCapabilities`, `VectorCapability`, `SupportLevel` |
| `models.py` | Request/response models, filters, `PartitionQueryPolicy`, `CompiledCosmosQuery` |
| `paths.py` | `CosmosPath` safe parse/render |
| `expressions.py` | FTS tokenisation + literal escaping |
| `planner.py` | Strategy selection from capabilities |
| `strategies.py` | Hybrid / vector / full-text / fusion / scan / grep execution |
| `compiler.py` | Logical plan → parameterised Cosmos SQL |
| `executor.py` | Concurrency, retries, slow-query logging |
| `normalization.py` | Raw rows → `RetrievedItem` |
| `document_resolvers.py` | Full-document reconstruction |
| `errors.py` | Typed failure modes |
| `retriever.py` | `CorpusRetriever` façade |
| `legacy.py` | Default chunked-corpus profile |
| `__init__.py` | Public API surface |
