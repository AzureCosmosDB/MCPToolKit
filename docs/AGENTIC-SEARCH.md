# `agentic_search`

The `agentic_search` tool can be used to answer questions asked in natural
language about existing Cosmos DB data. Given a question, a search agent runs
several searches using Cosmos DB-specific tools, then returns an answer with the
documents it is based on.

This tool is in **private preview** and is **off by default**. It needs the
separate agentic retrieval service, which is available to private preview
participants. To request access, fill in the
[private preview form](https://forms.cloud.microsoft/r/eMm2ARSxnH).

## Turn it on

Set this environment variable on the toolkit:

```bash
# Required: list the agentic_search tool
ENABLE_AGENTIC_SEARCH=true
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| `query` | yes | The question to answer. |
| `maxDocuments` | no | Most documents to return, 1–50 (default 20). |
| `database` | no | Search only this database. If omitted, the agent finds databases itself. |
| `container` | no | Search only this container. Needs `database`. |

