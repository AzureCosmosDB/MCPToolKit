using System.Buffers.Binary;
using System.Net.Sockets;
using System.Text;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// Minimal SOCKS5 CONNECT client (no authentication) for Gateway-mode Cosmos
/// traffic through a local Bastion SOCKS proxy. See
/// https://github.com/AzureCosmosDB/MCPToolKit/issues/152
/// </summary>
public static class Socks5Connect
{
    public static async Task<Stream> ConnectAsync(
        string proxyHost,
        int proxyPort,
        string destinationHost,
        int destinationPort,
        CancellationToken cancellationToken)
    {
        var socket = new Socket(SocketType.Stream, ProtocolType.Tcp)
        {
            NoDelay = true
        };
        try
        {
            await socket.ConnectAsync(proxyHost, proxyPort, cancellationToken).ConfigureAwait(false);
            var stream = new NetworkStream(socket, ownsSocket: true);

            // Greeting: VER=5, NMETHODS=1, METHOD=0 (no auth)
            await stream.WriteAsync(new byte[] { 0x05, 0x01, 0x00 }, cancellationToken).ConfigureAwait(false);
            var greet = new byte[2];
            await ReadExactAsync(stream, greet, cancellationToken).ConfigureAwait(false);
            if (greet[0] != 0x05 || greet[1] != 0x00)
            {
                throw new IOException($"SOCKS5 proxy rejected auth method (ver={greet[0]}, method={greet[1]}).");
            }

            // CONNECT request
            var hostBytes = Encoding.ASCII.GetBytes(destinationHost);
            if (hostBytes.Length > 255)
            {
                throw new ArgumentException("Destination host name is too long for SOCKS5.", nameof(destinationHost));
            }

            var request = new byte[4 + 1 + hostBytes.Length + 2];
            request[0] = 0x05; // VER
            request[1] = 0x01; // CONNECT
            request[2] = 0x00; // RSV
            request[3] = 0x03; // ATYP = domain
            request[4] = (byte)hostBytes.Length;
            Buffer.BlockCopy(hostBytes, 0, request, 5, hostBytes.Length);
            BinaryPrimitives.WriteUInt16BigEndian(request.AsSpan(5 + hostBytes.Length), (ushort)destinationPort);

            await stream.WriteAsync(request, cancellationToken).ConfigureAwait(false);

            // Reply: VER METH RSV ATYP … (at least 4 bytes, then bound addr)
            var replyHead = new byte[4];
            await ReadExactAsync(stream, replyHead, cancellationToken).ConfigureAwait(false);
            if (replyHead[0] != 0x05)
            {
                throw new IOException($"Invalid SOCKS5 reply version {replyHead[0]}.");
            }
            if (replyHead[1] != 0x00)
            {
                throw new IOException($"SOCKS5 CONNECT failed with reply code {replyHead[1]}.");
            }

            await DiscardBoundAddressAsync(stream, replyHead[3], cancellationToken).ConfigureAwait(false);
            return stream;
        }
        catch
        {
            socket.Dispose();
            throw;
        }
    }

    private static async Task DiscardBoundAddressAsync(Stream stream, byte atyp, CancellationToken cancellationToken)
    {
        int addrLen = atyp switch
        {
            0x01 => 4,   // IPv4
            0x03 => 1,   // domain length prefix read next
            0x04 => 16,  // IPv6
            _ => throw new IOException($"Unsupported SOCKS5 address type {atyp}.")
        };

        if (atyp == 0x03)
        {
            var lenBuf = new byte[1];
            await ReadExactAsync(stream, lenBuf, cancellationToken).ConfigureAwait(false);
            addrLen = lenBuf[0];
        }

        var skip = new byte[addrLen + 2]; // address + port
        await ReadExactAsync(stream, skip, cancellationToken).ConfigureAwait(false);
    }

    private static async Task ReadExactAsync(Stream stream, byte[] buffer, CancellationToken cancellationToken)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(offset, buffer.Length - offset), cancellationToken)
                .ConfigureAwait(false);
            if (read == 0)
            {
                throw new EndOfStreamException("SOCKS5 proxy closed the connection early.");
            }
            offset += read;
        }
    }

    /// <summary>
    /// Parses socks5://host:port (also accepts host:port). Returns null when unset.
    /// </summary>
    public static bool TryParseProxyUrl(string? raw, out string host, out int port, out string? error)
    {
        host = "";
        port = 0;
        error = null;
        if (string.IsNullOrWhiteSpace(raw))
        {
            return false;
        }

        var value = raw.Trim();
        if (value.StartsWith("socks5h://", StringComparison.OrdinalIgnoreCase))
        {
            value = value["socks5h://".Length..];
        }
        else if (value.StartsWith("socks5://", StringComparison.OrdinalIgnoreCase))
        {
            value = value["socks5://".Length..];
        }
        else if (value.Contains("://", StringComparison.Ordinal))
        {
            error = $"Unsupported proxy scheme in '{raw}'. Use socks5://host:port.";
            return false;
        }

        // Strip optional userinfo (unsupported)
        var at = value.LastIndexOf('@');
        if (at >= 0)
        {
            value = value[(at + 1)..];
        }

        // host:port or [ipv6]:port
        string hostPart;
        string portPart;
        if (value.StartsWith('[') && value.Contains(']'))
        {
            var end = value.IndexOf(']');
            hostPart = value[1..end];
            var rest = value[(end + 1)..];
            if (!rest.StartsWith(':'))
            {
                error = $"SOCKS5 proxy URL missing port: '{raw}'.";
                return false;
            }
            portPart = rest[1..];
        }
        else
        {
            var colon = value.LastIndexOf(':');
            if (colon <= 0 || colon == value.Length - 1)
            {
                error = $"SOCKS5 proxy URL must be host:port (got '{raw}').";
                return false;
            }
            hostPart = value[..colon];
            portPart = value[(colon + 1)..];
        }

        // Drop any path/query
        var slash = portPart.IndexOfAny(['/', '?']);
        if (slash >= 0)
        {
            portPart = portPart[..slash];
        }

        if (!int.TryParse(portPart, out port) || port is < 1 or > 65535)
        {
            error = $"Invalid SOCKS5 proxy port in '{raw}'.";
            return false;
        }

        host = hostPart.Trim();
        if (string.IsNullOrWhiteSpace(host))
        {
            error = $"Invalid SOCKS5 proxy host in '{raw}'.";
            return false;
        }

        return true;
    }
}
