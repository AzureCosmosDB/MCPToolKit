# Use Cases & Examples

Real-world scenarios where the MCP Toolkit provides immediate value.

---

## 🏢 **1. Business Intelligence Assistant**

**Scenario:** Sales teams query product databases with natural language instead of SQL.

**User Query:**
```
"Show me the top 10 products by revenue in the last quarter"
```

**How It Works:**
1. Agent receives natural language query
2. Uses `list_collections` → finds `products` container
3. Uses `vector_search` → finds products matching revenue/quarter filters
4. Returns formatted results to the user

**Benefits:**
- ✅ No SQL knowledge required
- ✅ Self-service data access
- ✅ Reduces IT support requests
- ✅ Faster decision-making

**Tools Used:** `vector_search`, `list_collections`, `get_approximate_schema`

---

## 🎓 **2. Customer Support Knowledge Base**

**Scenario:** Support agents use an AI assistant to answer customer questions using FAQ & documentation.

**User Query:**
```
"What's the return policy for digital products?"
```

**How It Works:**
1. Agent searches FAQ database with `hybrid_search`
2. Combines keyword matching (return, policy) with semantic similarity
3. Returns relevant policies + confidence scores
4. Support agent gets instant answer with sources

**Benefits:**
- ✅ Faster response times (from minutes to seconds)
- ✅ Consistent answers (always accurate policy info)
- ✅ Reduced training time for new support staff
- ✅ 24/7 availability

**Tools Used:** `hybrid_search`, `text_search`, `get_recent_documents`

---

## 🔬 **3. Research Paper Discovery**

**Scenario:** Researchers find relevant papers using semantic search across a vector-indexed database.

**User Query:**
```
"Find papers about transformer architectures and attention mechanisms"
```

**How It Works:**
1. Query is embedded using Azure OpenAI
2. `vector_search` finds semantically similar paper abstracts
3. Results ranked by relevance score
4. Researcher gets curated reading list

**Benefits:**
- ✅ Semantic understanding (not just keyword matching)
- ✅ Cross-domain paper discovery
- ✅ Saves hours of manual literature review
- ✅ Reduces researcher cognitive load

**Tools Used:** `vector_search`, `get_recent_documents`, `find_document_by_id`

---

## 📦 **4. Inventory Management Agent**

**Scenario:** Warehouse operators check stock levels and get low-inventory alerts through conversational interface.

**User Query:**
```
"Which products have less than 50 units in stock?"
```

**How It Works:**
1. Agent queries `inventory` container
2. Filters by quantity threshold using `text_search`
3. Returns list with locations and reorder information
4. Operator receives actionable alert

**Benefits:**
- ✅ Real-time inventory visibility
- ✅ Proactive restocking (no manual checks)
- ✅ Reduces stockouts and excess inventory
- ✅ Works on voice + text interfaces

**Tools Used:** `text_search`, `list_collections`, `get_approximate_schema`

---

## 💼 **5. Compliance Audit Assistant**

**Scenario:** Compliance officers query audit logs and document archives to verify regulatory requirements.

**User Query:**
```
"Find all access logs for user john.doe@company.com in the past 30 days"
```

**How It Works:**
1. Agent searches audit logs using `text_search` + `find_document_by_id`
2. Filters by user ID and timestamp
3. Returns structured audit trail
4. Officer exports for regulatory reporting

**Benefits:**
- ✅ Instant compliance verification
- ✅ Auditable search history (MCP protocol tracks all queries)
- ✅ Reduces manual document review (weeks → minutes)
- ✅ Supports SOC 2, HIPAA, GDPR compliance

**Tools Used:** `text_search`, `find_document_by_id`, `get_recent_documents`

---

## 🎮 **6. Game Analytics Dashboard**

**Scenario:** Game developers analyze player behavior from event logs stored in Cosmos DB.

**User Query:**
```
"What are the top 5 most-played game levels this week?"
```

**How It Works:**
1. Agent queries `game_events` container
2. Aggregates level play counts
3. Uses `vector_search` to find similar player behavior patterns
4. Returns engagement insights

**Benefits:**
- ✅ Real-time analytics (no ETL pipelines)
- ✅ Behavioral insights drive game design
- ✅ Fast A/B testing iteration
- ✅ Player retention optimization

**Tools Used:** `vector_search`, `text_search`, `get_recent_documents`

---

## 🏥 **7. Patient Record Lookup (HIPAA Compliant)**

**Scenario:** Healthcare providers securely query patient data through an authenticated AI interface.

**User Query:**
```
"Show me the recent lab results for patient #12345"
```

**How It Works:**
1. Provider authenticates via Azure Entra ID (HIPAA-compliant)
2. Agent uses `find_document_by_id` with patient ID
3. Returns redacted/filtered results based on provider's permissions
4. Query is fully auditable for compliance

**Benefits:**
- ✅ HIPAA-compliant access control (Entra ID + RBAC)
- ✅ Reduced paperwork (instant access)
- ✅ Patient privacy protected (role-based filtering)
- ✅ Audit trail for compliance verification

**Tools Used:** `find_document_by_id`, `text_search`, with Entra ID authentication

---

## 🌐 **8. Multi-Tenant SaaS Platform**

**Scenario:** SaaS application provides tenants with a private data query interface powered by MCP.

**Architecture:**
```
Tenant A → [MCP Server + Cosmos DB]
           ↓ (Entra ID Auth)
           Azure AD
           
Tenant B → [MCP Server + Cosmos DB]
           ↓ (Entra ID Auth)
           Azure AD
```

**Benefits:**
- ✅ Secure multi-tenancy (one MCP server per tenant)
- ✅ No cross-tenant data leakage
- ✅ Self-service analytics for tenants
- ✅ Scalable (Container Apps auto-scale)

**Tools Used:** All MCP tools with per-tenant authentication

---

## 🎯 **Getting Started with Your Use Case**

### Step 1: Identify Your Data
- What database do you want to expose? (Cosmos DB)
- What questions do users ask? (Schema & common queries)

### Step 2: Choose Your Tools
| Question Type | Best Tool |
|---|---|
| "Find document by ID" | `find_document_by_id` |
| "Search for keyword" | `text_search` |
| "Find semantically similar items" | `vector_search` |
| "Combine keyword + semantic search" | `hybrid_search` |
| "Rank documents by keyword relevance" | `bm25_search` |
| "Understand my data structure" | `get_approximate_schema` |
| "Get latest documents" | `get_recent_documents` |

### Step 3: Deploy & Test
1. [Deploy the MCP Toolkit](QUICK-START.md)
2. Test with sample questions in the web UI
3. Connect to your AI agent (Claude, Foundry, etc.)
4. Let it learn from usage

### Step 4: Measure Impact
- Track user engagement (queries per user, time saved)
- Monitor agent accuracy (use feedback ratings)
- Gather user feedback for improvements

---

## 📚 **Learn More**

- [Full Setup Guide](../README.md#quick-start)
- [Python Client Example](../client/README.md)
- [Architecture Guide](ARCHITECTURE-DIAGRAMS.md)
- [Troubleshooting](TROUBLESHOOTING-DEPLOYMENT.md)
