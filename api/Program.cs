using System.Text.Json;
using System.Text.Json.Nodes;
using TimelineForAudio.Api;

var productPaths = ProductPaths.Resolve(args);
var settingsForBind = ProductSettings.Load(productPaths);
var bindPortArg = ProductPaths.ArgValue(args, "--port");
var bindPort = string.IsNullOrWhiteSpace(bindPortArg)
    ? settingsForBind.Runtime.ApiPort
    : ProductSettings.ParsePort(bindPortArg);

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton(productPaths);
builder.Services.AddSingleton<ProductOperationRunner>();
builder.WebHost.UseUrls($"http://127.0.0.1:{bindPort}");

var app = builder.Build();

app.MapGet("/health", () =>
{
    try
    {
        _ = ProductSettings.Load(productPaths);
        return Results.Json(File.Exists(productPaths.DockerComposePath));
    }
    catch
    {
        return Results.Json(false);
    }
});

var settings = app.MapGroup("/settings");

settings.MapPost("/init", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        _ = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            ["settings", "init", "--json"],
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

settings.MapPost("/status", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        _ = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            ["settings", "status", "--json"],
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

settings.MapPost("/save", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildSettingsSaveArguments(request),
            TimeSpan.FromSeconds(60),
            cancellationToken);
    });
});

var files = app.MapGroup("/files");

files.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildFilesListArguments(request),
            TimeSpan.FromSeconds(120),
            cancellationToken);
    });
});

var items = app.MapGroup("/items");

items.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsListArguments(request),
            TimeSpan.FromSeconds(120),
            cancellationToken);
    });
});

items.MapPost("/refresh", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsRefreshArguments(request),
            TimeSpan.FromSeconds(GetBool(request, "queueOnly", true) ? 120 : 900),
            cancellationToken);
    });
});

items.MapPost("/remove", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsRemoveArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

items.MapPost("/download", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildItemsDownloadArguments(request),
            TimeSpan.FromSeconds(900),
            cancellationToken);
    });
});

var models = app.MapGroup("/models");

models.MapPost("/list", async (
    HttpContext context,
    ProductOperationRunner runner,
    CancellationToken cancellationToken) =>
{
    return await ExecuteJsonEndpointAsync(async () =>
    {
        var request = await ReadJsonObjectAsync(context, cancellationToken);
        return await runner.RunJsonAsync(
            BuildModelsListArguments(request),
            TimeSpan.FromSeconds(GetBool(request, "includeRemote", false) ? 300 : 120),
            cancellationToken);
    });
});

app.Run();

static async Task<IResult> ExecuteJsonEndpointAsync(Func<Task<JsonNode?>> operation)
{
    try
    {
        return Results.Json(await operation());
    }
    catch (ProductCommandException ex)
    {
        return Results.Json(
            ex.Payload ?? ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
    catch (Exception ex) when (ex is not OperationCanceledException)
    {
        return Results.Json(
            ErrorPayload(ex.Message),
            statusCode: StatusCodes.Status500InternalServerError);
    }
}

static async Task<JsonObject?> ReadJsonObjectAsync(HttpContext context, CancellationToken cancellationToken)
{
    if (context.Request.ContentLength == 0)
    {
        return null;
    }

    try
    {
        return await context.Request.ReadFromJsonAsync<JsonObject>(cancellationToken: cancellationToken);
    }
    catch (JsonException ex)
    {
        throw new InvalidOperationException($"Invalid JSON request body: {ex.Message}", ex);
    }
}

static IReadOnlyList<string> BuildSettingsSaveArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "settings",
        "save",
        "--json",
    };
    AddOptionalValue(arguments, "--token", GetStringAny(request, ["token", "huggingFaceToken", "huggingfaceToken"]));
    AddOptionalValue(arguments, "--compute-mode", GetStringAny(request, ["computeMode", "compute_mode"]));
    return arguments;
}

static IReadOnlyList<string> BuildFilesListArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "files",
        "list",
        "--json",
    };
    if (GetBool(request, "probe", false))
    {
        arguments.Add("--probe");
    }
    AddOptionalInt(arguments, "--page", GetIntAny(request, ["page"]));
    AddOptionalInt(arguments, "--page-size", GetIntAny(request, ["pageSize", "page_size"]));
    return arguments;
}

static IReadOnlyList<string> BuildItemsListArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "list",
        "--json",
    };
    AddOptionalInt(arguments, "--page", GetIntAny(request, ["page"]));
    AddOptionalInt(arguments, "--page-size", GetIntAny(request, ["pageSize", "page_size"]));
    return arguments;
}

static IReadOnlyList<string> BuildItemsRefreshArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "refresh",
        "--json",
    };
    if (GetBool(request, "queueOnly", true))
    {
        arguments.Add("--queue-only");
    }
    if (GetBoolAny(request, ["reprocessDuplicates", "reprocess_duplicates"], false))
    {
        arguments.Add("--reprocess-duplicates");
    }
    AddOptionalInt(arguments, "--max-items", GetIntAny(request, ["maxItems", "max_items", "limit"]));
    foreach (var sourceId in GetStringArrayAny(request, ["sourceIds", "source_ids", "inputRoots", "input_roots"]))
    {
        arguments.Add("--input-root");
        arguments.Add(sourceId);
    }
    return arguments;
}

static IReadOnlyList<string> BuildItemsRemoveArguments(JsonObject? request)
{
    var itemIds = GetItemIds(request);
    if (itemIds.Count == 0)
    {
        throw new InvalidOperationException("At least one item id is required.");
    }

    var arguments = new List<string>
    {
        "items",
        "remove",
        "--item-id",
        string.Join(",", itemIds),
        "--json",
    };
    if (GetBool(request, "dryRun", false))
    {
        arguments.Add("--dry-run");
    }
    return arguments;
}

static IReadOnlyList<string> BuildItemsDownloadArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "items",
        "download",
        "--json",
    };
    var itemIds = GetItemIds(request);
    if (itemIds.Count > 0)
    {
        arguments.Add("--item-id");
        arguments.Add(string.Join(",", itemIds));
    }
    AddOptionalValue(arguments, "--output", GetStringAny(request, ["outputPath", "output", "to", "destinationPath"]));
    return arguments;
}

static IReadOnlyList<string> BuildModelsListArguments(JsonObject? request)
{
    var arguments = new List<string>
    {
        "models",
        "list",
        "--json",
    };
    if (GetBoolAny(request, ["includeRemote", "include_remote", "remote"], false))
    {
        arguments.Add("--include-remote");
    }
    AddOptionalValue(arguments, "--output", GetStringAny(request, ["outputPath", "output"]));
    return arguments;
}

static JsonObject ErrorPayload(string message)
{
    return new JsonObject
    {
        ["ok"] = false,
        ["error"] = new JsonObject
        {
            ["message"] = message,
        },
    };
}

static void AddOptionalValue(List<string> arguments, string name, string value)
{
    if (string.IsNullOrWhiteSpace(value))
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Trim());
}

static void AddOptionalInt(List<string> arguments, string name, int? value)
{
    if (value is not > 0)
    {
        return;
    }

    arguments.Add(name);
    arguments.Add(value.Value.ToString());
}

static List<string> GetItemIds(JsonObject? request)
{
    return GetStringArrayAny(request, ["itemIds", "item_ids", "itemId", "item_id"])
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .Distinct(StringComparer.Ordinal)
        .ToList();
}

static List<string> GetStringArrayAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var values = GetStringArray(source, name);
        if (values.Count > 0)
        {
            return values;
        }
    }

    return [];
}

static List<string> GetStringArray(JsonObject? source, string name)
{
    var node = GetNode(source, name);
    if (node is null)
    {
        return [];
    }
    if (node is JsonArray array)
    {
        return array
            .Select(item => ConvertJsonText(item))
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .ToList();
    }

    var text = ConvertJsonText(node);
    if (string.IsNullOrWhiteSpace(text))
    {
        return [];
    }

    return text
        .Replace("\r", ",", StringComparison.Ordinal)
        .Replace("\n", ",", StringComparison.Ordinal)
        .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .ToList();
}

static string GetStringAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is not null)
        {
            return ConvertJsonText(node);
        }
    }

    return string.Empty;
}

static int? GetIntAny(JsonObject? source, string[] names)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is null)
        {
            continue;
        }

        if (node is JsonValue value)
        {
            if (value.TryGetValue<int>(out var intValue))
            {
                return intValue;
            }
            if (value.TryGetValue<string>(out var textValue)
                && int.TryParse(textValue, out var parsed))
            {
                return parsed;
            }
        }
    }

    return null;
}

static bool GetBool(JsonObject? source, string name, bool fallback)
    => GetBoolAny(source, [name], fallback);

static bool GetBoolAny(JsonObject? source, string[] names, bool fallback)
{
    foreach (var name in names)
    {
        var node = GetNode(source, name);
        if (node is null)
        {
            continue;
        }
        if (node is JsonValue value)
        {
            if (value.TryGetValue<bool>(out var boolValue))
            {
                return boolValue;
            }
            if (value.TryGetValue<string>(out var textValue))
            {
                var text = textValue.Trim().ToLowerInvariant();
                if (text is "1" or "true" or "yes" or "on")
                {
                    return true;
                }
                if (text is "0" or "false" or "no" or "off")
                {
                    return false;
                }
            }
        }
    }

    return fallback;
}

static JsonNode? GetNode(JsonObject? source, string name)
{
    if (source is null)
    {
        return null;
    }
    if (source.TryGetPropertyValue(name, out var node))
    {
        return node;
    }

    foreach (var property in source)
    {
        if (property.Key.Equals(name, StringComparison.OrdinalIgnoreCase))
        {
            return property.Value;
        }
    }

    return null;
}

static string ConvertJsonText(JsonNode? node)
{
    if (node is null || node.GetValueKind() == JsonValueKind.Null)
    {
        return string.Empty;
    }

    if (node is JsonValue value)
    {
        if (value.TryGetValue<string>(out var text))
        {
            return text.Trim();
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue.ToString();
        }
        if (value.TryGetValue<bool>(out var boolValue))
        {
            return boolValue ? "true" : "false";
        }
    }

    return node.ToJsonString().Trim();
}
