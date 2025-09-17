# Use the official .NET 9.0 runtime as base image
FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS base
WORKDIR /app
EXPOSE 8080

# Use the official .NET 9.0 SDK for building
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

# Copy project file and restore dependencies
COPY ["src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj", "src/AzureCosmosDB.MCP.Toolkit/"]
RUN dotnet restore "src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj"

# Copy all source files
COPY . .
WORKDIR "/src/src/AzureCosmosDB.MCP.Toolkit"

# Build the application
RUN dotnet build "AzureCosmosDB.MCP.Toolkit.csproj" -c Release -o /app/build

# Publish the application
FROM build AS publish
RUN dotnet publish "AzureCosmosDB.MCP.Toolkit.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Final stage - runtime image
FROM base AS final
WORKDIR /app

# Copy the published application
COPY --from=publish /app/publish .

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" --uid 1000 appuser && chown -R appuser /app
USER appuser

# Set the entry point
ENTRYPOINT ["dotnet", "AzureCosmosDB.MCP.Toolkit.dll"]