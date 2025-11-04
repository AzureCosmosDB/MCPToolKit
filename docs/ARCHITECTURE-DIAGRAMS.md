# Azure Cosmos DB MCP Toolkit - Architecture Diagram

## Simple Architecture Overview

```mermaid
graph TB
    subgraph "Client Applications"
        WebUI[Web Browser UI<br/>Test Interface]
        AIFoundry[AI Foundry<br/>Agent Builder]
        MCPClient[MCP Client<br/>Claude, etc.]
    end

    subgraph "MCP Toolkit Service<br/>(Azure Container Apps)"
        Auth[Microsoft Entra ID<br/>Authentication]
        API[ASP.NET Core Web API<br/>MCP Protocol Handler]
        Tools[Cosmos DB Tools Service]
    end

    subgraph "Azure Services"
        CosmosDB[(Azure Cosmos DB<br/>NoSQL Database)]
        OpenAI[Azure OpenAI<br/>Embeddings API]
        MI[Managed Identity<br/>Azure AD Auth]
    end

    WebUI -->|HTTPS + OAuth| Auth
    AIFoundry -->|MCP Protocol| Auth
    MCPClient -->|MCP Protocol| Auth
    
    Auth -->|Validates Token| API
    API -->|Routes Requests| Tools
    
    Tools -->|Read/Query Data| CosmosDB
    Tools -->|Generate Embeddings| OpenAI
    
    MI -.->|Authenticates| CosmosDB
    MI -.->|Authenticates| OpenAI

    style WebUI fill:#e1f5ff
    style AIFoundry fill:#e1f5ff
    style MCPClient fill:#e1f5ff
    style Auth fill:#fff4e6
    style API fill:#fff4e6
    style Tools fill:#fff4e6
    style CosmosDB fill:#e8f5e9
    style OpenAI fill:#e8f5e9
    style MI fill:#f3e5f5
```

## Tool Operations Flow

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant MCP as MCP Toolkit API
    participant Cosmos as Cosmos DB
    participant OpenAI as Azure OpenAI

    Note over Client,OpenAI: List Databases
    Client->>MCP: list_databases()
    MCP->>Cosmos: Query databases
    Cosmos-->>MCP: Database list
    MCP-->>Client: Return databases

    Note over Client,OpenAI: Get Recent Documents
    Client->>MCP: get_recent_documents(db, container, n)
    MCP->>Cosmos: SELECT TOP n * ORDER BY _ts DESC
    Cosmos-->>MCP: Recent documents
    MCP-->>Client: Return JSON documents

    Note over Client,OpenAI: Vector Search
    Client->>MCP: vector_search(text, properties, topN)
    MCP->>OpenAI: Generate embedding(text)
    OpenAI-->>MCP: Embedding vector
    MCP->>Cosmos: VectorDistance(embedding) query
    Cosmos-->>MCP: Similar documents
    MCP-->>Client: Ranked results by similarity
```

## Available MCP Tools

```mermaid
mindmap
  root((Cosmos DB<br/>MCP Tools))
    Discovery
      list_databases
      list_collections
      get_approximate_schema
    Data Access
      get_recent_documents
      find_document_by_id
      text_search
    AI Search
      vector_search
        Generate embedding
        Semantic similarity
        Ranked results
```

## Security & Authentication

```mermaid
graph LR
    User[User] -->|1. Sign In| Entra[Microsoft Entra ID]
    Entra -->|2. ID Token + Role| WebUI[Web UI / MCP Client]
    WebUI -->|3. Bearer Token| API[MCP Toolkit API]
    API -->|4. Validate Token| Entra
    API -->|5. Check Role| Role[Mcp.Tool.Executor]
    
    API -->|6. Use Managed Identity| MI[Managed Identity]
    MI -->|7. Access| Cosmos[(Cosmos DB)]
    MI -->|8. Access| OpenAI[Azure OpenAI]
    
    style Entra fill:#fff4e6
    style Role fill:#fff4e6
    style MI fill:#f3e5f5
    style Cosmos fill:#e8f5e9
    style OpenAI fill:#e8f5e9
```

## Data Flow for Vector Search Demo

```mermaid
graph TB
    subgraph "1. User Query"
        Q[Search: 'luxury sedan']
    end
    
    subgraph "2. Embedding Generation"
        Q -->|Text| OpenAI[Azure OpenAI]
        OpenAI -->|Vector Array| E[Embedding<br/>1536 dimensions]
    end
    
    subgraph "3. Cosmos DB Query"
        E -->|VectorDistance| Query[SELECT TOP 5<br/>VectorDistance query]
        Query -->|Search| VectorIndex[Vector Index]
    end
    
    subgraph "4. Results"
        VectorIndex -->|Ranked| R1[1. BMW 7 Series<br/>Score: 0.85]
        VectorIndex -->|by| R2[2. Audi A8<br/>Score: 0.83]
        VectorIndex -->|Similarity| R3[3. Mercedes C-Class<br/>Score: 0.78]
    end
    
    R1 -->|Return| Results[JSON Results]
    R2 -->|Return| Results
    R3 -->|Return| Results
    
    style Q fill:#e1f5ff
    style OpenAI fill:#fff4e6
    style E fill:#fff4e6
    style VectorIndex fill:#e8f5e9
    style R1 fill:#c8e6c9
    style R2 fill:#c8e6c9
    style R3 fill:#c8e6c9
```

## Deployment to Azure Container Apps

```mermaid
graph TB
    subgraph "Local Development"
        Code[ASP.NET Core<br/>MCP Toolkit Code]
        Docker[Dockerfile]
        Code -->|Build| Docker
    end
    
    subgraph "Azure Container Registry"
        Docker -->|docker build & push| ACR[Container Image<br/>mcptoolkit:latest]
    end
    
    subgraph "Azure Container Apps"
        ACR -->|Deploy| ACA[Container App<br/>mcp-toolkit-app]
        
        subgraph "Configuration"
            Env[Environment Variables<br/>COSMOS_ENDPOINT<br/>OPENAI_ENDPOINT<br/>etc.]
            MI[Managed Identity<br/>System-Assigned]
            Scale[Auto-Scaling<br/>0-10 replicas]
        end
        
        ACA --- Env
        ACA --- MI
        ACA --- Scale
    end
    
    subgraph "Azure Resources"
        MI -->|Authenticate| Cosmos[(Cosmos DB)]
        MI -->|Authenticate| OpenAI[Azure OpenAI]
    end
    
    subgraph "Access"
        Internet[Internet] -->|HTTPS| Ingress[Public Ingress<br/>HTTPS Only]
        Ingress -->|Route| ACA
    end
    
    style Code fill:#e1f5ff
    style Docker fill:#e1f5ff
    style ACR fill:#fff4e6
    style ACA fill:#c8e6c9
    style Env fill:#f3e5f5
    style MI fill:#f3e5f5
    style Scale fill:#f3e5f5
    style Cosmos fill:#e8f5e9
    style OpenAI fill:#e8f5e9
```

---

## How to Use These Diagrams

### Option 1: Render in VS Code
1. Install the "Markdown Preview Mermaid Support" extension
2. Open this file and preview it (Ctrl+Shift+V)
3. Take screenshots of the rendered diagrams

### Option 2: Use Mermaid Live Editor
1. Go to https://mermaid.live
2. Copy/paste each diagram code block
3. Export as PNG or SVG

### Option 3: Use in PowerPoint/Slides
1. Copy the diagram code
2. Use Mermaid tools or render online
3. Export and insert as images

### Option 4: GitHub/Markdown
These diagrams render automatically in:
- GitHub README.md files
- Azure DevOps wikis
- Many documentation platforms

---

## Presentation Talking Points

### Slide 1: Architecture Overview
- **3-tier architecture**: Client → MCP Service → Azure Resources
- **Enterprise security**: Microsoft Entra ID + Managed Identity
- **Scalable deployment**: Azure Container Apps with auto-scaling

### Slide 2: Tool Operations
- **7 MCP tools** for Cosmos DB operations
- **Standard MCP protocol** - works with any MCP client
- **Real-time operations** - direct API calls, no caching

### Slide 3: Vector Search Flow
- **Natural language queries** → Semantic search
- **Azure OpenAI integration** for embeddings
- **Native Cosmos DB vector search** - no external vector DB needed

### Slide 4: Security Model
- **Zero keys in code** - all authentication via Azure AD
- **Role-based access** - granular permissions
- **Managed Identity** - secure service-to-service auth

### Slide 5: Container Apps Deployment
- **Simple containerization** - Standard Dockerfile, any language
- **Azure Container Registry** - Secure image storage
- **Auto-scaling** - Scale to zero, scale to demand
- **Managed Identity** - No connection strings needed
- **One-command deployment** - PowerShell script automates everything
