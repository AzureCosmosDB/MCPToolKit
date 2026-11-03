# `agentic_search` HTTP integration

Use `agentic_search` to find answers to queries or questions from relevant
documents in a Cosmos DB corpus. A retrieval agent (LLM) will receive the
question, issue multiple sub-queries and return an answer and the documents it
used.

*A separately running, `cosmos-agentic-retrieval` service is required.*
Configure the agent's retrieval behavior, Cosmos access, and models on that
service. Note that this feature is currently **experimental**.

## Architecture

```text
  MCP client
       |
       | MCP tool call: agentic_search
       v
  MCPToolKit (.NET)
       |
       | HTTP POST /agentic_search  <-- Response body
       v
     External retrieval service (`cosmos-agentic-retrieval`)
```

## Configuration

The tool reads two optional environment variables. The values below are the defaults.

```bash
# Base URL of the external retrieval service
COSMOS_RETRIEVER_URL=http://127.0.0.1:9000

# HTTP request timeout in seconds
COSMOS_RETRIEVER_TIMEOUT_S=600
```

