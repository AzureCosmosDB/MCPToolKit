using System.Security.Claims;

namespace AzureCosmosDB.MCP.Toolkit.Services
{
    /// <summary>
    /// Service for handling authentication and authorization for MCP operations
    /// </summary>
    public class AuthenticationService
    {
        private readonly IHttpContextAccessor _httpContextAccessor;
        private readonly ILogger<AuthenticationService> _logger;
        private readonly IConfiguration _configuration;

        public AuthenticationService(IHttpContextAccessor httpContextAccessor, ILogger<AuthenticationService> logger, IConfiguration configuration)
        {
            _httpContextAccessor = httpContextAccessor;
            _logger = logger;
            _configuration = configuration;
        }

        /// <summary>
        /// Gets the current user from the HTTP context
        /// </summary>
        /// <returns>ClaimsPrincipal representing the current user, or null if not authenticated</returns>
        public ClaimsPrincipal? GetCurrentUser()
        {
            return _httpContextAccessor.HttpContext?.User;
        }

        /// <summary>
        /// Ensures the current user is authenticated
        /// </summary>
        /// <exception cref="UnauthorizedAccessException">Thrown when user is not authenticated</exception>
        public void EnsureAuthenticated()
        {
            var user = GetCurrentUser();
            if (user?.Identity?.IsAuthenticated != true)
            {
                _logger.LogWarning("Unauthorized access attempt - user not authenticated");
                throw new UnauthorizedAccessException("Unauthorized");
            }
        }

        /// <summary>
        /// Ensures the current user has the specified role
        /// </summary>
        /// <param name="role">The required role</param>
        /// <exception cref="UnauthorizedAccessException">Thrown when user is not authenticated</exception>
        /// <exception cref="InvalidOperationException">Thrown when user doesn't have the required role</exception>
        public void EnsureInRole(string role)
        {
            var user = GetCurrentUser();
            EnsureAuthenticated();
            
            if (user is null || !user.IsInRole(role))
            {
                _logger.LogWarning("Forbidden access attempt - user missing required role: {Role}", role);
                throw new InvalidOperationException($"Forbidden: missing role '{role}'");
            }
        }

        /// <summary>
        /// Ensures the current user has the MCP Tool Executor role
        /// </summary>
        public void EnsureMcpToolExecutorRole()
        {
            EnsureInRole("Mcp.Tool.Executor");
        }

        /// <summary>
        /// Gets the current user's identity information for logging
        /// </summary>
        /// <returns>String representation of user identity</returns>
        public string GetUserIdentityInfo()
        {
            var user = GetCurrentUser();
            if (user?.Identity?.IsAuthenticated == true)
            {
                var userId = user.FindFirst("sub")?.Value ?? user.FindFirst("oid")?.Value ?? "unknown";
                var userEmail = user.FindFirst("email")?.Value ?? user.FindFirst("preferred_username")?.Value ?? "unknown";
                return $"User: {userEmail} (ID: {userId})";
            }
            return "Anonymous user";
        }

        /// <summary>
        /// Checks if authentication bypass is enabled
        /// </summary>
        /// <returns>True if authentication should be bypassed</returns>
        private bool IsAuthenticationBypassed()
        {
            return Environment.GetEnvironmentVariable("DEV_BYPASS_AUTH") == "true" ||
                   _configuration.GetValue<bool>("DevelopmentMode:BypassAuthentication");
        }

        /// <summary>
        /// Checks if authentication is enabled in the current environment
        /// </summary>
        /// <returns>True if authentication is enabled, false otherwise</returns>
        public bool IsAuthenticationEnabled()
        {
            return !IsAuthenticationBypassed();
        }

        /// <summary>
        /// Checks if the user has the specified role
        /// </summary>
        /// <param name="user">The user to check</param>
        /// <param name="roleName">The role name</param>
        /// <returns>True if user has the role or authentication is bypassed</returns>
        public bool HasRole(ClaimsPrincipal? user, string roleName)
        {
            // Check for development bypass
            if (IsAuthenticationBypassed())
            {
                return true;
            }

            if (user?.Identity?.IsAuthenticated != true)
            {
                return false;
            }

            return user.IsInRole(roleName);
        }

        /// <summary>
        /// Gets the user ID from claims
        /// </summary>
        /// <param name="user">The user principal</param>
        /// <returns>User ID or fallback for development</returns>
        public string? GetUserId(ClaimsPrincipal? user)
        {
            // Check for development bypass
            if (IsAuthenticationBypassed())
            {
                return "dev-user";
            }

            if (user?.Identity?.IsAuthenticated != true)
            {
                return null;
            }

            return user.FindFirst("oid")?.Value ?? user.FindFirst("sub")?.Value;
        }

        /// <summary>
        /// Gets the user email from claims
        /// </summary>
        /// <param name="user">The user principal</param>
        /// <returns>User email or fallback for development</returns>
        public string? GetUserEmail(ClaimsPrincipal? user)
        {
            // Check for development bypass
            if (IsAuthenticationBypassed())
            {
                return "dev@localhost";
            }

            if (user?.Identity?.IsAuthenticated != true)
            {
                return null;
            }

            return user.FindFirst("upn")?.Value ?? user.FindFirst("email")?.Value;
        }

        /// <summary>
        /// Gets the user name from claims
        /// </summary>
        /// <param name="user">The user principal</param>
        /// <returns>User name or fallback for development</returns>
        public string? GetUserName(ClaimsPrincipal? user)
        {
            // Check for development bypass
            if (IsAuthenticationBypassed())
            {
                return "Development User";
            }

            if (user?.Identity?.IsAuthenticated != true)
            {
                return null;
            }

            return user.FindFirst("name")?.Value ?? user.Identity.Name;
        }
    }
}