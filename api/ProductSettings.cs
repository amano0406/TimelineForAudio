using System.Text.Json;
using System.Text.Json.Nodes;

namespace TimelineForAudio.Api;

public sealed record RuntimeSettings(int ApiPort);

public sealed record ProductSettings(RuntimeSettings Runtime)
{
    public static ProductSettings Load(ProductPaths paths)
    {
        var defaults = Default();
        if (!File.Exists(paths.SettingsPath))
        {
            return defaults;
        }

        JsonObject root;
        try
        {
            root = JsonNode.Parse(File.ReadAllText(paths.SettingsPath)) as JsonObject
                ?? throw new InvalidOperationException("settings.json must contain a JSON object.");
        }
        catch (JsonException exc)
        {
            throw new InvalidOperationException($"Invalid JSON in settings.json: {exc.Message}", exc);
        }

        var runtime = root["runtime"] as JsonObject ?? new JsonObject();
        return new ProductSettings(
            Runtime: new RuntimeSettings(
                ApiPort: Port(runtime, "apiPort", "api_port") ?? Port(root, "apiPort", "api_port") ?? defaults.Runtime.ApiPort));
    }

    public static int ParsePort(string value)
    {
        if (!int.TryParse(value, out var port))
        {
            throw new InvalidOperationException("TimelineForAudio API port must be an integer.");
        }

        if (port is < 1 or > 65535)
        {
            throw new InvalidOperationException("TimelineForAudio API port must be between 1 and 65535.");
        }

        return port;
    }

    private static ProductSettings Default() => new(new RuntimeSettings(19100));

    private static int? Port(JsonObject source, params string[] names)
    {
        foreach (var name in names)
        {
            if (source[name] is not JsonValue value)
            {
                continue;
            }

            if (value.TryGetValue<int>(out var intValue))
            {
                return ValidatePort(intValue);
            }

            if (value.TryGetValue<string>(out var textValue) && !string.IsNullOrWhiteSpace(textValue))
            {
                return ParsePort(textValue);
            }
        }

        return null;
    }

    private static int ValidatePort(int port)
    {
        if (port is < 1 or > 65535)
        {
            throw new InvalidOperationException("TimelineForAudio API port must be between 1 and 65535.");
        }

        return port;
    }
}
