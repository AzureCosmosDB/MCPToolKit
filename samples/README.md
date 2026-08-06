# Declarative Tool Configuration Samples

These samples demonstrate the **generic**, opt-in declarative runtime of the Azure Cosmos DB MCP
Toolkit. The toolkit engine contains **no domain-specific logic** — it reads a YAML/JSON file and
executes the described operations against any Cosmos DB container. Each sample below is just a
different configuration file; none of them required any code change to the toolkit.

To use any sample, point the toolkit at it:

```powershell
$env:COSMOS_TOOLS_CONFIG = "C:\path\to\<sample>.yaml"
```

## Samples

| Sample | Domain | Shows |
|---|---|---|
| [`banking/cosmos-tools.yaml`](./banking/cosmos-tools.yaml) | Retail banking | Hierarchical partition keys, tenant isolation, `point-read`, `query`, `vector-search`, `create`, `transactional-batch` |
| [`ecommerce/cosmos-tools.yaml`](./ecommerce/cosmos-tools.yaml) | E‑commerce catalog & orders | A completely different domain using the same engine: `point-read`, `query`, `hybrid-search`, `patch` with an allow‑list, `sequence` with an assertion |

## The point

The two samples share **no toolkit code** — only different YAML. Anything you can express with the
supported operation types (point read, query, text/vector/hybrid search, create/replace/patch/delete,
transactional batch, bounded `sequence`) works for any Cosmos-backed application. See the
[YAML reference](../docs/declarative-tools/yaml-reference.md) for the full schema.
