# Security & Governance

The declarative layer is designed to **fail closed** and to keep identity decisions server-side.

## Authentication

Configured tools run inside the same ASP.NET pipeline as the built-in tools and honor the same
authentication configuration (Entra ID JWT bearer, or the `DEV_BYPASS_AUTH=true` development
bypass). The caller's `ClaimsPrincipal` is read per invocation from the request `HttpContext`.

## Authorization

Per-tool `authorization` supports:

- `requiredScopes` — every listed scope must be present (`scp` claim).
- `requiredRoles` — every listed role must be present (`roles` claim).
- `claims` — claim type must equal the required value.
- `tenantClaim` + `tenantField` — tenant isolation (below).
- `partitionKeyFromClaim` — partition restriction derived from identity.

When any authorization rule is present and the caller is unauthenticated (and not in dev bypass),
the tool is denied.

## Tenant isolation & anti-spoofing

The tenant identity is **always** taken from a validated token claim, never from model-supplied
input:

1. If the model supplies a `tenantField` value that differs from the `tenantClaim`, the call is
   **denied** (`tenant isolation violation`).
2. Before binding, the trusted claim value is **overlaid** onto the input, so the executed
   operation uses the caller's real tenant regardless of what the model sent.

The same mechanism applies to `partitionKeyFromClaim` for partition-level restriction.

## Injection resistance

- Query text comes only from configuration. Caller input is bound as **parameters**
  (`@name`), ids, and partition keys — never concatenated into SQL.
- Identifier paths used to build SQL fragments (search property, vector/text paths, projection
  fields) come from configuration and are validated; wildcard projection is rejected.
- Unit tests assert that SQL-looking input (`'; DROP TABLE ...`, `A1' OR '1'='1`) is passed through
  as a literal parameter value and never appears in the statement text.

## Governance (fail closed)

- **Read-only by default.** Writes require `governance.readOnly: false`; `delete` additionally
  requires `allowDelete: true`. This is enforced at load time — an offending tool makes the whole
  configuration invalid and the server does not start.
- **Cross-partition** queries require `allowCrossPartition: true`; otherwise queries are scoped to
  the tool's partition key.
- **Limits:** `maxItems` caps result counts and `MaxItemCount`; `maxTopK` caps vector/hybrid `topK`.
- **Timeouts:** `timeoutMs` wraps each invocation in a linked cancellation token; a timeout returns
  a structured `timeout` error rather than hanging.
- **Patch allow-list:** when `allowedPatchPaths` is set, patch operations must target one of the
  listed JSON paths.

## Observability

Each configured invocation logs tool name, version, operation, database, container, latency, and a
result category (`ok`, `validation`, `authorization`, `not_found`, `conflict`, `timeout`,
`cosmos`, `internal`). Sensitive document content is not logged by default.

## Error taxonomy

All failures are returned as structured, client-safe JSON: `{ "error": "...", "category": "...",
"details": [...] }`. Categories include `validation`, `authorization`, `binding`, `assertion`,
`not_found`, `conflict` (ETag/precondition), `timeout`, `cosmos`, and `internal`.
