using System.Text.Json;

const int DefaultApiPort = 19100;

var settingsPath = TimelineSettings.ResolveSettingsPath();
var apiPort = TimelineSettings.ResolveApiPort(settingsPath, DefaultApiPort);

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{apiPort}");

var app = builder.Build();

app.MapGet("/health", () => Results.Json(TimelineSettings.IsHealthy(settingsPath)));

app.Run();

internal static class TimelineSettings
{
    public static string ResolveSettingsPath()
    {
        var configured = Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_SETTINGS_PATH");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return Path.GetFullPath(configured);
        }

        var current = Directory.GetCurrentDirectory();
        foreach (var candidate in CandidateSettingsPaths(current))
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return Path.GetFullPath(Path.Combine(current, "settings.json"));
    }

    public static int ResolveApiPort(string settingsPath, int fallback)
    {
        var envPort = Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_API_PORT");
        if (TryNormalizePort(envPort, out var configuredPort))
        {
            return configuredPort;
        }

        if (TryReadSettings(settingsPath, out var document))
        {
            using (document)
            {
                if (document.RootElement.TryGetProperty("runtime", out var runtime)
                    && runtime.ValueKind == JsonValueKind.Object
                    && runtime.TryGetProperty("apiPort", out var apiPort)
                    && TryNormalizePort(apiPort, out configuredPort))
                {
                    return configuredPort;
                }
            }
        }

        return fallback;
    }

    public static bool IsHealthy(string settingsPath)
    {
        if (!TryReadSettings(settingsPath, out var document))
        {
            return false;
        }

        using (document)
        {
            return document.RootElement.ValueKind == JsonValueKind.Object
                && document.RootElement.TryGetProperty("runtime", out var runtime)
                && runtime.ValueKind == JsonValueKind.Object
                && runtime.TryGetProperty("apiPort", out var apiPort)
                && TryNormalizePort(apiPort, out _);
        }
    }

    private static IEnumerable<string> CandidateSettingsPaths(string current)
    {
        var directory = new DirectoryInfo(current);
        while (directory is not null)
        {
            yield return Path.Combine(directory.FullName, "settings.json");
            directory = directory.Parent;
        }
    }

    private static bool TryReadSettings(string path, out JsonDocument document)
    {
        document = null!;
        try
        {
            if (!File.Exists(path))
            {
                return false;
            }

            document = JsonDocument.Parse(File.ReadAllText(path));
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static bool TryNormalizePort(JsonElement element, out int port)
    {
        if (element.ValueKind == JsonValueKind.Number && element.TryGetInt32(out port))
        {
            return port is >= 1 and <= 65535;
        }

        if (element.ValueKind == JsonValueKind.String)
        {
            return TryNormalizePort(element.GetString(), out port);
        }

        port = 0;
        return false;
    }

    private static bool TryNormalizePort(string? value, out int port)
    {
        if (int.TryParse(value, out port))
        {
            return port is >= 1 and <= 65535;
        }

        port = 0;
        return false;
    }
}
