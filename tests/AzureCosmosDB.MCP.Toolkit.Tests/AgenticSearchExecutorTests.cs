using System.Net;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using AzureCosmosDB.MCP.Toolkit.Services;
using FluentAssertions;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;
using Moq;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

/// <summary>
/// Tests for the AgenticSearchExecutor. Stands in for the cosmos-retriever
/// FastAPI service with a tiny in-process HttpListener so we can verify the
/// executor's response pass-through, timeout behaviour, and error-envelope
/// generation without needing the real retriever service running.
/// </summary>
[Collection("Agentic search")]
public sealed class AgenticSearchExecutorTests : IDisposable
{
    private readonly Dictionary<string, string?> _savedEnv = new();
    private static readonly NullLogger _logger = NullLogger.Instance;

    private void SetEnv(string name, string? value)
    {
        if (!_savedEnv.ContainsKey(name))
        {
            _savedEnv[name] = Environment.GetEnvironmentVariable(name);
        }
        Environment.SetEnvironmentVariable(name, value);
    }

    public void Dispose()
    {
        foreach (var (k, v) in _savedEnv)
        {
            Environment.SetEnvironmentVariable(k, v);
        }
    }

    [Fact]
    public async Task RunAsync_passes_through_service_response_body()
    {
        const string body =
            "{\"query\":\"hi\",\"documents\":[{\"id\":\"doc_a\",\"rank\":0}],\"num_turns\":1,\"elapsed_s\":0.01}";

        using var server = StubServer.Start((ctx, _) =>
        {
            ctx.Response.StatusCode = 200;
            ctx.Response.ContentType = "application/json";
            return body;
        });

        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, server.BaseUrl);
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "30");

        var raw = await AgenticSearchExecutor.RunAsync("hi", maxDocuments: 5, logger: _logger);

        using var doc = JsonDocument.Parse(raw);
        doc.RootElement.GetProperty("query").GetString().Should().Be("hi");
        doc.RootElement.GetProperty("num_turns").GetInt32().Should().Be(1);
        doc.RootElement.GetProperty("documents")[0].GetProperty("id").GetString().Should().Be("doc_a");
    }

    [Fact]
    public async Task RunAsync_forwards_request_payload_to_service()
    {
        string? capturedBody = null;
        using var server = StubServer.Start((ctx, reqBody) =>
        {
            capturedBody = reqBody;
            ctx.Response.StatusCode = 200;
            return "{\"query\":\"q\",\"documents\":[],\"num_turns\":0,\"elapsed_s\":0.0}";
        });

        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, server.BaseUrl);
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "30");

        await AgenticSearchExecutor.RunAsync(
            "find me docs", maxDocuments: 7, logger: _logger, database: "db1", container: "corpus-x");

        capturedBody.Should().NotBeNull();
        using var doc = JsonDocument.Parse(capturedBody!);
        doc.RootElement.GetProperty("query").GetString().Should().Be("find me docs");
        doc.RootElement.GetProperty("maxDocuments").GetInt32().Should().Be(7);
        doc.RootElement.GetProperty("database").GetString().Should().Be("db1");
        doc.RootElement.GetProperty("container").GetString().Should().Be("corpus-x");
    }

    [Fact]
    public async Task RunAsync_passes_through_service_error_envelope_on_non_success()
    {
        using var server = StubServer.Start((ctx, _) =>
        {
            ctx.Response.StatusCode = 500;
            ctx.Response.ContentType = "application/json";
            return "{\"error\":\"vllm unreachable\",\"type\":\"RuntimeError\"}";
        });

        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, server.BaseUrl);
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "30");

        var raw = await AgenticSearchExecutor.RunAsync("hi", maxDocuments: 5, logger: _logger);

        using var doc = JsonDocument.Parse(raw);
        doc.RootElement.GetProperty("error").GetString().Should().Be("vllm unreachable");
    }

    [Fact]
    public async Task RunAsync_returns_error_envelope_when_service_unreachable()
    {
        // Reserve+release a port so nothing is listening on it. Small race: another
        // process could bind it before the call — negligible in tests, so not guarded.
        var port = GetFreePort();
        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, $"http://127.0.0.1:{port}");
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "5");

        var raw = await AgenticSearchExecutor.RunAsync("hi", maxDocuments: 5, logger: _logger);

        using var doc = JsonDocument.Parse(raw);
        doc.RootElement.GetProperty("error").GetString().Should().Contain("Failed to reach");
        doc.RootElement.TryGetProperty("hint", out var hint).Should().BeTrue();
        hint.GetString().Should().Contain(AgenticSearchExecutor.BaseUrlEnvVar);
    }

    [Theory]
    [InlineData("not-a-url")]
    [InlineData("http://")]
    [InlineData("file:///tmp/retriever")]
    [InlineData("ftp://127.0.0.1:9000")]
    public async Task RunAsync_returns_error_envelope_for_invalid_service_url(string url)
    {
        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, url);

        var raw = await AgenticSearchExecutor.RunAsync("hi", maxDocuments: 5, logger: _logger);

        using var doc = JsonDocument.Parse(raw);
        doc.RootElement.GetProperty("error").GetString().Should().Be(
            $"{AgenticSearchExecutor.BaseUrlEnvVar} must be an absolute HTTP or HTTPS URL.");
    }

    [Fact]
    public async Task RunAsync_returns_error_envelope_when_service_times_out()
    {
        using var server = StubServer.Start((ctx, _) =>
        {
            // Sleep for longer than the 1s timeout we're about to set.
            Thread.Sleep(5000);
            ctx.Response.StatusCode = 200;
            return "{}";
        });

        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, server.BaseUrl);
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "1");

        var raw = await AgenticSearchExecutor.RunAsync("hi", maxDocuments: 5, logger: _logger);

        using var doc = JsonDocument.Parse(raw);
        doc.RootElement.GetProperty("error").GetString().Should().Contain("timed out after 1s");
    }

    [Fact]
    public async Task AgenticSearch_cancels_pending_http_request_from_sdk()
    {
        using var application = new McpTestApplicationFactory();
        using var client = application.CreateClient();
        var received = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var response = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var server = StubServer.Start(async (ctx, _) =>
        {
            received.TrySetResult();
            return await response.Task;
        });
        SetEnv(AgenticSearchExecutor.BaseUrlEnvVar, server.BaseUrl);
        SetEnv(AgenticSearchExecutor.TimeoutEnvVar, "30");

        var tool = McpServerTool.Create(typeof(AgenticSearchTools).GetMethod("AgenticSearch")!, (object?)null);
        tool.ProtocolTool.InputSchema.GetProperty("properties").EnumerateObject()
            .Select(property => property.Name).Should().BeEquivalentTo(
                "query", "maxDocuments", "database", "container");
        var request = new RequestContext<CallToolRequestParams>(Mock.Of<McpServer>(),
            new JsonRpcRequest { Id = new RequestId(1), Method = "tools/call" },
            new CallToolRequestParams
            {
                Name = "agentic_search",
                Arguments = new Dictionary<string, JsonElement> { ["query"] = JsonSerializer.SerializeToElement("hi") }
            });
        using var cancellation = new CancellationTokenSource();
        var invocation = tool.InvokeAsync(request, cancellation.Token).AsTask();
        try
        {
            await received.Task.WaitAsync(TimeSpan.FromSeconds(5));
            cancellation.Cancel();
            Func<Task> pending = async () => { await invocation.WaitAsync(TimeSpan.FromSeconds(5)); };
            await pending.Should().ThrowAsync<OperationCanceledException>();
        }
        finally
        {
            response.TrySetResult("{}");
            try { await invocation.WaitAsync(TimeSpan.FromSeconds(5)); }
            catch (OperationCanceledException) { }
        }
    }

    private static int GetFreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task AgenticSearch_is_listed_only_when_enabled(bool enabled)
    {
        using var application = new McpTestApplicationFactory().WithWebHostBuilder(builder =>
            builder.UseSetting("AgenticSearch:Enabled", enabled ? "true" : "false"));
        using var client = application.CreateClient();
        client.DefaultRequestHeaders.Accept.ParseAdd("application/json");
        client.DefaultRequestHeaders.Accept.ParseAdd("text/event-stream");

        var initialize = await client.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "initialize",
            @params = new
            {
                protocolVersion = "2025-06-18",
                capabilities = new { },
                clientInfo = new { name = "test", version = "1.0" }
            }
        });
        if (initialize.Headers.TryGetValues("Mcp-Session-Id", out var sessionIds))
        {
            client.DefaultRequestHeaders.Add("Mcp-Session-Id", sessionIds.Single());
        }
        var sdkList = await client.PostAsJsonAsync("/mcp", new { jsonrpc = "2.0", id = 2, method = "tools/list" });
        var webList = await client.PostAsJsonAsync("/mcp/http", new { jsonrpc = "2.0", id = 3, method = "tools/list" });

        sdkList.StatusCode.Should().Be(HttpStatusCode.OK);
        webList.StatusCode.Should().Be(HttpStatusCode.OK);
        (await sdkList.Content.ReadAsStringAsync()).Contains("\"agentic_search\"").Should().Be(enabled);
        (await webList.Content.ReadAsStringAsync()).Contains("\"agentic_search\"").Should().Be(enabled);
    }

    /// <summary>
    /// Minimal in-process HTTP server backed by HttpListener.
    /// The handler receives the request context plus the request body and
    /// returns the response body string.
    /// </summary>
    private sealed class StubServer : IDisposable
    {
        private readonly HttpListener _listener;
        private readonly CancellationTokenSource _cts = new();

        public string BaseUrl { get; }

        private StubServer(HttpListener listener, string baseUrl)
        {
            _listener = listener;
            BaseUrl = baseUrl;
        }

        public static StubServer Start(Func<HttpListenerContext, string, string> handler)
            => Start((context, body) => Task.FromResult(handler(context, body)));

        public static StubServer Start(Func<HttpListenerContext, string, Task<string>> handler)
        {
            var port = GetFreePort();
            var baseUrl = $"http://127.0.0.1:{port}";
            var listener = new HttpListener();
            listener.Prefixes.Add($"{baseUrl}/");
            listener.Start();
            var server = new StubServer(listener, baseUrl);
            _ = Task.Run(() => server.LoopAsync(handler));
            return server;
        }

        private async Task LoopAsync(Func<HttpListenerContext, string, Task<string>> handler)
        {
            while (!_cts.IsCancellationRequested)
            {
                HttpListenerContext ctx;
                try
                {
                    ctx = await _listener.GetContextAsync().ConfigureAwait(false);
                }
                catch
                {
                    return; // listener stopped
                }

                try
                {
                    string reqBody;
                    using (var reader = new StreamReader(ctx.Request.InputStream, Encoding.UTF8))
                    {
                        reqBody = await reader.ReadToEndAsync().ConfigureAwait(false);
                    }

                    var responseBody = await handler(ctx, reqBody);
                    var buffer = Encoding.UTF8.GetBytes(responseBody);
                    ctx.Response.ContentLength64 = buffer.Length;
                    await ctx.Response.OutputStream.WriteAsync(buffer).ConfigureAwait(false);
                    ctx.Response.OutputStream.Close();
                }
                catch
                {
                    try { ctx.Response.Abort(); } catch { /* best effort */ }
                }
            }
        }

        public void Dispose()
        {
            _cts.Cancel();
            try { _listener.Stop(); } catch { /* best effort */ }
            try { _listener.Close(); } catch { /* best effort */ }
            _cts.Dispose();
        }
    }
}

[CollectionDefinition("Agentic search", DisableParallelization = true)]
public sealed class AgenticSearchCollection;
