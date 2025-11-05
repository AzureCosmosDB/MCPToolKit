# syntax=docker/dockerfile:1
# Use the official .NET 9.0 runtime as base image
FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS base
WORKDIR /app
EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080

# Use the official .NET 9.0 SDK for building
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
ARG BUILD_CONFIGURATION=Release
WORKDIR /src

# Copy only project files first for better caching (dependencies change less frequently than code)
COPY ["src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj", "src/AzureCosmosDB.MCP.Toolkit/"]
COPY ["Directory.Build.props", "./"]

# Restore dependencies in a separate layer (cached unless project file changes)
RUN dotnet restore "src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj"

# Now copy the rest of the source code
COPY src/ src/

# Build the application
WORKDIR "/src/src/AzureCosmosDB.MCP.Toolkit"
RUN dotnet build "AzureCosmosDB.MCP.Toolkit.csproj" -c $BUILD_CONFIGURATION -o /app/build --no-restore

# Publish the application
FROM build AS publish
ARG BUILD_CONFIGURATION=Release
RUN dotnet publish "AzureCosmosDB.MCP.Toolkit.csproj" -c $BUILD_CONFIGURATION -o /app/publish \
    --no-restore \
    /p:UseAppHost=false

# Final stage - runtime image
FROM base AS final
WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy the published application
COPY --from=publish /app/publish .

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" --uid 1000 appuser && chown -R appuser /app
USER appuser

# Add health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Set the entry point
ENTRYPOINT ["dotnet", "AzureCosmosDB.MCP.Toolkit.dll"]