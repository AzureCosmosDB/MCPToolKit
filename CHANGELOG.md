# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release of Azure Cosmos DB MCP Toolkit
- Document querying and full-text search capabilities
- AI-powered vector similarity search with Azure OpenAI embeddings
- Container schema discovery and analysis
- Secure Entra ID authentication
- Model Context Protocol integration for AI agents

### Features
- **ListDatabases**: Lists databases available in the Cosmos DB account
- **ListCollections**: Lists containers (collections) for the specified database
- **GetRecentDocuments**: Gets the most recent N documents ordered by timestamp
- **TextSearch**: Full-text search within document properties
- **FindDocumentByID**: Find a document by its ID
- **GetApproximateSchema**: Approximates container schema by sampling documents
- **VectorSearch**: Performs vector search using Azure OpenAI embeddings

### Environment Variables
- `COSMOS_ENDPOINT`: Azure Cosmos DB endpoint URL
- `OPENAI_ENDPOINT`: Azure OpenAI endpoint URL
- `OPENAI_EMBEDDING_DEPLOYMENT`: Azure OpenAI embedding deployment name

### Todo
- Host in Azure Container Apps (or Azure Functions)
- Expose an MCP Server endpoint from hosting platform (ACA, AF)
- Authenticate to MCP Server via EntraID/MI
- Test via Microsoft Foundry Agents Service

## [1.0.0] - 2025-09-15

### Added
- Initial version of the Azure Cosmos DB MCP Toolkit
- Basic MCP server functionality
- Azure Cosmos DB integration
- Azure OpenAI integration for vector search