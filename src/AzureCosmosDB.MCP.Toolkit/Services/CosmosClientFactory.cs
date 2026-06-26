using Azure.Identity;
using Microsoft.Azure.Cosmos;
using System.Net.Http;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// Factory for creating CosmosClient instances with support for both Azure credentials and connection strings.
/// Enables local development with Cosmos DB emulator via connection string.
/// </summary>
public static class CosmosClientFactory
{
    private static CosmosClientOptions BuildClientOptions(IConfiguration configuration, ILogger logger, bool useGatewayMode)
    {
        var options = new CosmosClientOptions
        {
            ApplicationName = "AzureCosmosDBMCP",
            EnableContentResponseOnWrite = false,
            RequestTimeout = TimeSpan.FromSeconds(60)
        };

        if (useGatewayMode)
        {
            // Emulator/local scenarios are more reliable over HTTPS gateway mode.
            options.ConnectionMode = ConnectionMode.Gateway;
        }

        var sslVerifySetting = configuration["COSMOS_EMULATOR_SSL_VERIFY"]
            ?? Environment.GetEnvironmentVariable("COSMOS_EMULATOR_SSL_VERIFY");

        if (!string.IsNullOrWhiteSpace(sslVerifySetting)
            && bool.TryParse(sslVerifySetting, out var sslVerify)
            && !sslVerify)
        {
            logger.LogWarning("COSMOS_EMULATOR_SSL_VERIFY=false detected. TLS certificate validation is disabled for Cosmos DB emulator connections.");
            options.HttpClientFactory = () => new HttpClient(new HttpClientHandler
            {
                ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
            });
        }

        return options;
    }

    /// <summary>
    /// Create a CosmosClient with fallback support for connection strings and Azure credentials.
    /// 
    /// Priority order:
    /// 1. COSMOS_CONNECTION_STRING - for emulator or local development
    /// 2. COSMOS_ENDPOINT with DefaultAzureCredential - for cloud production
    /// </summary>
    public static CosmosClient CreateCosmosClient(IConfiguration configuration, ILogger logger)
    {
        // Check for connection string first (emulator/local development)
        var connectionString = configuration["COSMOS_CONNECTION_STRING"] 
            ?? Environment.GetEnvironmentVariable("COSMOS_CONNECTION_STRING");

        if (!string.IsNullOrWhiteSpace(connectionString))
        {
            logger.LogInformation("Creating CosmosClient using connection string (emulator/local mode)");
            return new CosmosClient(connectionString, BuildClientOptions(configuration, logger, useGatewayMode: true));
        }

        // Fall back to Azure credentials for cloud production
        var endpoint = configuration["COSMOS_ENDPOINT"] 
            ?? Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");

        if (string.IsNullOrWhiteSpace(endpoint))
        {
            throw new InvalidOperationException(
                "Either COSMOS_ENDPOINT or COSMOS_CONNECTION_STRING environment variable must be set. " +
                "For emulator/local development, use COSMOS_CONNECTION_STRING. " +
                "For cloud production, use COSMOS_ENDPOINT with Azure credentials.");
        }

        logger.LogInformation("Creating CosmosClient using Azure credentials (cloud mode)");
        // Exclude ManagedIdentityCredential: on Azure VMs MSI_ENDPOINT/IMDS is present
        // but the managed identity often lacks Cosmos RBAC (SSO failure). Skipping it
        // lets the chain fall through to the Azure CLI login (az login), which the
        // Python retriever uses successfully.
        var credential = new DefaultAzureCredential(new DefaultAzureCredentialOptions
        {
            ExcludeManagedIdentityCredential = true,
        });

        return new CosmosClient(endpoint, credential, BuildClientOptions(configuration, logger, useGatewayMode: false));
    }
}
