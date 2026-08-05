# YAML Configuration Reference

Configuration is authored in YAML (or JSON) and validated at startup. Values support two token forms:

- `${ENV}` / `${env:ENV}` — **environment substitution** applied at load time. The `${env:NAME}`
  form is required and errors if unset; the bare `${NAME}` form is substituted only when an
  environment variable of that name exists, otherwise it is preserved as a runtime binding.
- `${input.x}`, `${x}`, `${system.utcNow}`, `${generated.x}`, `${steps.id.field}` — **runtime
  bindings** resolved per invocation.

## Top-level

```yaml
version: "1.0"          # required; only "1.0" is supported
sources: { ... }        # named Cosmos sources (required, at least one)
defaults: { ... }       # optional global defaults
tools: { ... }          # tool definitions
```

## `sources`

```yaml
sources:
  app:
    type: cosmos                       # only "cosmos" supported
    endpoint: "${COSMOS_ENDPOINT}"     # or connectionString for emulator/local
    connectionString: "${COSMOS_CONNECTION_STRING}"
    database: "${COSMOS_DATABASE}"
    authentication:
      type: managed-identity           # managed-identity | default-azure-credential | connection-string
    connectionMode: gateway            # gateway | direct (optional)
```

> **Note (current limitation):** all sources resolve to the toolkit's configured Cosmos account
> (from `COSMOS_ENDPOINT`/`COSMOS_CONNECTION_STRING`); `source.database` selects the database.
> Per-source distinct endpoints/credentials are a planned enhancement.

## `defaults`

```yaml
defaults:
  source: app            # default source for tools that omit one
  governance:
    timeoutMs: 5000
    maxItems: 100
    readOnly: true
```

## Tool

```yaml
tools:
  my_tool:
    name: my_tool          # optional; defaults to the key
    description: ...
    version: "1.0"
    enabled: true
    tags: [a, b]
    examples: ["..."]
    source: app
    operation: { ... }     # required
    input: { ... }         # JSON-schema subset
    output: { ... }        # projection/redaction
    authorization: { ... }
    governance: { ... }
```

### `input`

```yaml
input:
  type: object
  required: [customerId]
  properties:
    customerId: { type: string, minLength: 1, maxLength: 64, pattern: "^[A-Za-z0-9_-]+$" }
    limit:      { type: integer, default: 10, minimum: 1, maximum: 50 }
    amount:     { type: number, minimum: 0.01 }
    category:   { type: string, enum: [a, b, c] }
    active:     { type: boolean }
    tags:       { type: array, minItems: 1, maxItems: 10, items: { type: string } }
    address:    { type: object, required: [city], properties: { city: { type: string } } }
```

The generated MCP input schema is **closed** (`additionalProperties: false`); unknown properties
are rejected, matching the built-in tools.

### `output`

```yaml
output:
  select:                  # projection + rename: outputName -> sourceField
    accountId: accountId
    availableBalance: balance
  redact: [internalRiskScore]   # remove fields entirely
  maxItems: 50                  # cap array results
```

### `authorization`

```yaml
authorization:
  requiredScopes: [banking.accounts.read]
  requiredRoles: [Mcp.Tool.Executor]
  claims: { department: retail }        # claim type => required value
  tenantClaim: tid                      # trusted tenant source (token claim)
  tenantField: tenantId                 # input/document field forced to equal the claim
  partitionKeyFromClaim: { customerId: sub }   # input value forced from identity
```

Tenant/partition values are always taken from validated claims and enforced against input, so a
model cannot spoof another tenant.

### `governance`

```yaml
governance:
  readOnly: true               # default; set false to enable writes
  allowDelete: false           # required true to permit delete
  allowCrossPartition: false   # required true for cross-partition queries
  timeoutMs: 3000
  maxItems: 100
  maxRequestUnits: 10
  maxTopK: 10
  allowedPatchPaths: [/balance]   # when set, patch ops must target one of these
```

## Operation types (one example each)

### point-read

```yaml
operation:
  type: point-read
  container: accounts
  id: "${accountId}"
  partitionKey: "${customerId}"          # or partitionKeys: ["${tenantId}", "${accountId}"]
```

### query

```yaml
operation:
  type: query
  container: transactions
  statement: |
    SELECT TOP @limit c.id, c.amount, c.timestamp
    FROM c WHERE c.accountId = @accountId
    ORDER BY c.timestamp DESC
  parameters:
    accountId: "${accountId}"
    limit: "${limit}"
  partitionKey: "${accountId}"
```

Only `@parameters` are bound from input; the statement text is never built from user input.

### text-search

```yaml
operation:
  type: text-search
  container: docs
  property: content            # validated identifier
  searchText: "${query}"
  limit: "${limit}"
```

### vector-search

```yaml
operation:
  type: vector-search
  container: offers
  searchText: "${query}"
  vectorPath: /embedding
  topK: 5
  select: [id, title, description]
```

### hybrid-search

```yaml
operation:
  type: hybrid-search
  container: offers
  searchText: "${query}"
  vectorPath: /embedding
  textPath: /description
  topK: 5
  select: [id, title, description]
```

### create (write)

```yaml
governance: { readOnly: false }
operation:
  type: create
  container: serviceRequests
  partitionKey: "${customerId}"
  document:
    id: "${generated.id}"
    customerId: "${customerId}"
    createdAt: "${system.utcNow}"
    status: open
```

### replace / patch (write)

```yaml
governance: { readOnly: false, allowedPatchPaths: [/balance] }
operation:
  type: patch
  container: accounts
  id: "${accountId}"
  partitionKey: "${customerId}"
  operations:
    - op: replace           # set | replace | add | remove | increment
      path: /balance
      value: "${newBalance}"
  concurrency:
    ifMatch: "${etag}"      # optimistic concurrency
```

### delete (write, extra opt-in)

```yaml
governance: { readOnly: false, allowDelete: true }
operation:
  type: delete
  container: accounts
  id: "${accountId}"
  partitionKey: "${customerId}"
```

### transactional-batch (single logical partition)

```yaml
governance: { readOnly: false }
operation:
  type: transactional-batch
  container: accounts
  partitionKeys: ["${tenantId}", "${accountId}"]
  steps:
    - id: adjust
      type: patch
      itemId: "${accountId}"
      operations: [{ op: increment, path: /balance, value: "${amount}" }]
    - id: record
      type: create
      document: { id: "${generated.txnId}", amount: "${amount}", at: "${system.utcNow}" }
```

### sequence (bounded Cosmos-only composition)

```yaml
governance: { readOnly: false }
operation:
  type: sequence
  container: accounts
  partitionKey: "${customerId}"
  steps:
    - id: source
      type: point-read
      itemId: "${sourceAccountId}"
    - id: validateFunds
      type: assert
      expression: "${steps.source.balance >= input.amount}"
      message: Insufficient funds.
    - id: debit
      type: patch
      itemId: "${sourceAccountId}"
      operations: [{ op: increment, path: /balance, value: "${negativeAmount}" }]
```

`assert` steps evaluate a **bounded** boolean expression (comparisons + `&&`/`||` only).
Sequences are short and acyclic — no loops, scripts, or cross-service calls.
