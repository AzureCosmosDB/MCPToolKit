using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using AzureCosmosDB.MCP.Toolkit.Services;

namespace AzureCosmosDB.MCP.Toolkit.Controllers;

[ApiController]
[Route("api/[controller]")]
public class HealthController : ControllerBase
{
    private readonly AuthenticationService _authService;
    private readonly ILogger<HealthController> _logger;

    public HealthController(AuthenticationService authService, ILogger<HealthController> logger)
    {
        _authService = authService;
        _logger = logger;
    }

    [HttpGet]
    [AllowAnonymous]
    public IActionResult GetHealth()
    {
        try
        {
            // Very basic response to test
            return Ok(new
            {
                status = "healthy",
                timestamp = DateTime.UtcNow,
                server = "Azure Cosmos DB MCP Toolkit",
                version = "1.0.0"
            });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = ex.Message });
        }
    }

    [HttpGet("auth")]
    [Authorize]
    public IActionResult GetAuthInfo()
    {
        try
        {
            var user = _authService.GetCurrentUser();
            var hasRequiredRole = _authService.HasRole(user, "Mcp.Tool.Executor");
            
            if (!hasRequiredRole && _authService.IsAuthenticationEnabled())
            {
                _authService.EnsureMcpToolExecutorRole();
            }
            
            return Ok(new
            {
                status = "authenticated",
                timestamp = DateTime.UtcNow,
                user = new
                {
                    id = _authService.GetUserId(user),
                    email = _authService.GetUserEmail(user),
                    name = _authService.GetUserName(user),
                    roles = user?.FindAll("roles")?.Select(c => c.Value).ToArray() ?? new string[0]
                },
                hasRequiredRole = hasRequiredRole,
                authenticationEnabled = _authService.IsAuthenticationEnabled(),
                devMode = !_authService.IsAuthenticationEnabled()
            });
        }
        catch (Exception ex)
        {
            var user = _authService.GetCurrentUser();
            return Ok(new
            {
                status = "authenticated_but_unauthorized",
                timestamp = DateTime.UtcNow,
                user = new
                {
                    id = _authService.GetUserId(user),
                    email = _authService.GetUserEmail(user),
                    name = _authService.GetUserName(user),
                    roles = user?.FindAll("roles")?.Select(c => c.Value).ToArray() ?? new string[0]
                },
                hasRequiredRole = false,
                error = ex.Message,
                authenticationEnabled = _authService.IsAuthenticationEnabled(),
                devMode = !_authService.IsAuthenticationEnabled()
            });
        }
    }
}