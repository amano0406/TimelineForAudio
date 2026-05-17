using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace TimelineForAudio.Api;

public sealed class ProductCommandException : Exception
{
    public ProductCommandException(
        string message,
        int exitCode,
        JsonNode? payload,
        string stdout,
        string stderr)
        : base(message)
    {
        ExitCode = exitCode;
        Payload = payload;
        Stdout = stdout;
        Stderr = stderr;
    }

    public int ExitCode { get; }

    public JsonNode? Payload { get; }

    public string Stdout { get; }

    public string Stderr { get; }
}

public sealed class ProductCommandRunner
{
    private readonly ProductPaths _paths;

    public ProductCommandRunner(ProductPaths paths)
    {
        _paths = paths;
    }

    public async Task<JsonNode?> RunJsonAsync(
        IReadOnlyList<string> arguments,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var runtime = AudioRuntime.Ensure(_paths);
        var dockerPath = ResolveDockerCommand();
        PrepareDockerPaths(runtime);
        var composeArguments = BuildComposeArguments(runtime);

        var workerState = await GetWorkerStateAsync(dockerPath, composeArguments, runtime, timeout, cancellationToken);
        if (!workerState.IsRunning)
        {
            throw new InvalidOperationException(workerState.Message);
        }

        var dockerArguments = new List<string>
        {
            "compose",
        };
        dockerArguments.AddRange(composeArguments);
        dockerArguments.AddRange([
            "exec",
            "-T",
            "worker",
            "python",
            "-m",
            "timeline_for_audio_worker",
        ]);
        dockerArguments.AddRange(arguments);

        var result = await RunProcessAsync(
            dockerPath,
            dockerArguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);

        var payload = TryParseJson(result.Stdout) ?? TryParseJson(result.Stderr);
        if (result.ExitCode != 0)
        {
            var message = GetErrorMessage(payload);
            if (string.IsNullOrEmpty(message))
            {
                message = !string.IsNullOrWhiteSpace(result.Stderr)
                    ? result.Stderr.Trim()
                    : !string.IsNullOrWhiteSpace(result.Stdout)
                        ? result.Stdout.Trim()
                        : $"exit code {result.ExitCode}";
            }

            throw new ProductCommandException(message, result.ExitCode, payload, result.Stdout, result.Stderr);
        }

        if (payload is null)
        {
            throw new InvalidOperationException("TimelineForAudio worker did not return JSON.");
        }

        return CompleteHostDownloadPayload(arguments, payload);
    }

    private async Task<WorkerState> GetWorkerStateAsync(
        string dockerPath,
        IReadOnlyList<string> composeArguments,
        AudioRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var arguments = new List<string>
        {
            "compose",
        };
        arguments.AddRange(composeArguments);
        arguments.AddRange(["ps", "--status", "running", "--services"]);

        var result = await RunProcessAsync(
            dockerPath,
            arguments,
            _paths.ProductRoot,
            runtime,
            timeout,
            cancellationToken);
        if (result.ExitCode != 0)
        {
            var message = !string.IsNullOrWhiteSpace(result.Stderr)
                ? result.Stderr.Trim()
                : !string.IsNullOrWhiteSpace(result.Stdout)
                    ? result.Stdout.Trim()
                    : "TimelineForAudio worker status could not be checked.";
            return new WorkerState(false, message);
        }

        var isRunning = result.Stdout
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Any(service => string.Equals(service, "worker", StringComparison.Ordinal));
        return isRunning
            ? new WorkerState(true, string.Empty)
            : new WorkerState(false, "TimelineForAudio worker is not running.");
    }

    private List<string> BuildComposeArguments(AudioRuntime runtime)
    {
        var arguments = new List<string>
        {
            "-p",
            runtime.ComposeProject,
            "-f",
            _paths.DockerComposePath,
        };

        if (File.Exists(runtime.PathsOverridePath))
        {
            arguments.Add("-f");
            arguments.Add(runtime.PathsOverridePath);
        }

        if (runtime.ComputeMode == "gpu" && File.Exists(_paths.DockerComposeGpuPath) && IsNvidiaGpuAvailable())
        {
            arguments.Add("-f");
            arguments.Add(_paths.DockerComposeGpuPath);
        }

        return arguments;
    }

    private void PrepareDockerPaths(AudioRuntime runtime)
    {
        var generatedDir = Path.GetDirectoryName(runtime.PathsOverridePath);
        if (!string.IsNullOrWhiteSpace(generatedDir))
        {
            Directory.CreateDirectory(generatedDir);
        }

        var mappings = new List<Dictionary<string, string>>();
        var workerVolumeLines = new List<string>();
        var apiVolumeLines = new List<string>();
        var usingSettingsOverride = !PathsEqual(_paths.SettingsPath, Path.Combine(_paths.ProductRoot, "settings.json"));

        if (usingSettingsOverride)
        {
            AddVolumeLines(workerVolumeLines, _paths.SettingsPath, "/host/settings/settings.json", readOnly: true);
            AddVolumeLines(apiVolumeLines, _paths.SettingsPath, "/host/settings/settings.json", readOnly: true);
        }

        var inputIndex = 0;
        foreach (var inputRoot in runtime.InputRoots)
        {
            inputIndex += 1;
            var resolved = ResolveExistingPath(inputRoot);
            if (string.IsNullOrWhiteSpace(resolved))
            {
                continue;
            }

            var containerPath = $"/host/input/input-{inputIndex}";
            mappings.Add(new Dictionary<string, string>
            {
                ["host"] = resolved,
                ["container"] = containerPath,
            });
            AddVolumeLines(workerVolumeLines, resolved, containerPath, readOnly: true);
        }

        if (!string.IsNullOrWhiteSpace(runtime.OutputRoot))
        {
            Directory.CreateDirectory(runtime.OutputRoot);
            var resolved = ResolveExistingPath(runtime.OutputRoot);
            if (!string.IsNullOrWhiteSpace(resolved))
            {
                mappings.Add(new Dictionary<string, string>
                {
                    ["host"] = resolved,
                    ["container"] = "/host/output/master",
                });
                AddVolumeLines(workerVolumeLines, resolved, "/host/output/master", readOnly: false);
            }
        }

        var lines = new List<string>
        {
            "services:",
            "  worker:",
            "    environment:",
            $"      TIMELINE_FOR_AUDIO_PATH_MAPPINGS: {YamlSingleQuoted(JsonSerializer.Serialize(mappings))}",
        };
        if (usingSettingsOverride)
        {
            lines.Add("      TIMELINE_FOR_AUDIO_SETTINGS_PATH: /host/settings/settings.json");
        }
        if (workerVolumeLines.Count > 0)
        {
            lines.Add("    volumes:");
            lines.AddRange(workerVolumeLines);
        }
        if (usingSettingsOverride)
        {
            lines.Add("  api:");
            lines.Add("    environment:");
            lines.Add("      TIMELINE_FOR_AUDIO_SETTINGS_PATH: /host/settings/settings.json");
            if (apiVolumeLines.Count > 0)
            {
                lines.Add("    volumes:");
                lines.AddRange(apiVolumeLines);
            }
        }

        var content = string.Join(Environment.NewLine, lines) + Environment.NewLine;
        var current = File.Exists(runtime.PathsOverridePath)
            ? File.ReadAllText(runtime.PathsOverridePath, Encoding.UTF8)
            : string.Empty;
        if (string.Equals(current, content, StringComparison.Ordinal))
        {
            return;
        }

        var tempPath = Path.Combine(
            generatedDir ?? _paths.ProductRoot,
            $"docker-compose.paths.{Guid.NewGuid():N}.tmp");
        File.WriteAllText(tempPath, content, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        File.Move(tempPath, runtime.PathsOverridePath, overwrite: true);
    }

    private static void AddVolumeLines(List<string> lines, string hostPath, string containerPath, bool readOnly)
    {
        lines.Add("      - type: bind");
        lines.Add($"        source: {YamlSingleQuoted(hostPath)}");
        lines.Add($"        target: {containerPath}");
        if (readOnly)
        {
            lines.Add("        read_only: true");
        }
    }

    private static string? ResolveExistingPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }
        if (!Directory.Exists(path) && !File.Exists(path))
        {
            return null;
        }
        return Path.GetFullPath(path);
    }

    private static bool PathsEqual(string left, string right)
        => string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);

    private static string YamlSingleQuoted(string value)
        => "'" + value.Replace("'", "''", StringComparison.Ordinal) + "'";

    private JsonNode? CompleteHostDownloadPayload(IReadOnlyList<string> arguments, JsonNode? payload)
    {
        var requestedOutput = GetOutputArgumentValue(arguments);
        if (string.IsNullOrWhiteSpace(requestedOutput) || !IsHostPath(requestedOutput) || payload is not JsonObject obj)
        {
            return payload;
        }

        var archivePathText = GetJsonString(obj, "archive_path");
        if (string.IsNullOrWhiteSpace(archivePathText))
        {
            return payload;
        }

        var sourceHostPath = ContainerPathToHostPath(archivePathText);
        if (!File.Exists(sourceHostPath))
        {
            return payload;
        }

        var requestedFullPath = Path.GetFullPath(requestedOutput);
        var requestedParent = Path.GetDirectoryName(requestedFullPath);
        if (!string.IsNullOrWhiteSpace(requestedParent))
        {
            Directory.CreateDirectory(requestedParent);
        }

        if (!PathsEqual(sourceHostPath, requestedFullPath))
        {
            File.Copy(sourceHostPath, requestedFullPath, overwrite: true);
            try
            {
                File.Delete(sourceHostPath);
            }
            catch (IOException)
            {
            }
        }

        obj["archive_path"] = requestedFullPath;
        return obj;
    }

    private string ContainerPathToHostPath(string value)
    {
        var text = value.Trim();
        if (text.Length == 0)
        {
            return text;
        }
        if (Path.IsPathFullyQualified(text))
        {
            return Path.GetFullPath(text);
        }

        var normalized = text.Replace('\\', '/');
        if (normalized == "/workspace")
        {
            return _paths.ProductRoot;
        }
        if (normalized.StartsWith("/workspace/", StringComparison.Ordinal))
        {
            var relative = normalized["/workspace/".Length..].Replace('/', Path.DirectorySeparatorChar);
            return Path.Combine(_paths.ProductRoot, relative);
        }

        return text;
    }

    private static string? GetOutputArgumentValue(IReadOnlyList<string> arguments)
    {
        for (var index = 0; index < arguments.Count; index++)
        {
            var value = arguments[index];
            if (value == "--output" && index + 1 < arguments.Count)
            {
                return arguments[index + 1];
            }
            if (value.StartsWith("--output=", StringComparison.Ordinal))
            {
                return value["--output=".Length..];
            }
        }
        return null;
    }

    private static bool IsHostPath(string value)
        => !string.IsNullOrWhiteSpace(value) && !value.TrimStart().StartsWith("/", StringComparison.Ordinal);

    private static string GetJsonString(JsonObject obj, string name)
    {
        if (obj[name] is JsonValue value && value.TryGetValue<string>(out var text))
        {
            return text;
        }
        return string.Empty;
    }

    private static async Task<CommandResult> RunProcessAsync(
        string fileName,
        IReadOnlyList<string> arguments,
        string workingDirectory,
        AudioRuntime runtime,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var processStart = new ProcessStartInfo
        {
            FileName = fileName,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        processStart.Environment["COMPOSE_PROJECT_NAME"] = runtime.ComposeProject;
        processStart.Environment["TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH"] = runtime.SettingsPath;
        processStart.Environment["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = runtime.SettingsPath;
        processStart.Environment["TIMELINE_FOR_AUDIO_INSTANCE_NAME"] = runtime.InstanceName;
        processStart.Environment["TIMELINE_FOR_AUDIO_API_PORT"] = runtime.ApiPort.ToString();
        processStart.Environment["TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH"] = runtime.PathsOverridePath;
        foreach (var argument in arguments)
        {
            processStart.ArgumentList.Add(argument);
        }

        using var process = Process.Start(processStart)
            ?? throw new InvalidOperationException("TimelineForAudio command process could not be started.");
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();

        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutSource.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            KillProcessTree(process);
            throw new TimeoutException($"TimelineForAudio command timed out after {(int)timeout.TotalSeconds} seconds.");
        }
        catch
        {
            KillProcessTree(process);
            throw;
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        return new CommandResult(process.ExitCode, stdout, stderr);
    }

    private static void KillProcessTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
    }

    private static JsonNode? TryParseJson(string text)
    {
        var trimmed = text.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            return null;
        }

        try
        {
            return JsonNode.Parse(trimmed);
        }
        catch (JsonException)
        {
        }

        var objectStart = trimmed.IndexOf('{');
        var objectEnd = trimmed.LastIndexOf('}');
        if (objectStart >= 0 && objectEnd > objectStart)
        {
            try
            {
                return JsonNode.Parse(trimmed[objectStart..(objectEnd + 1)]);
            }
            catch (JsonException)
            {
            }
        }

        var arrayStart = trimmed.IndexOf('[');
        var arrayEnd = trimmed.LastIndexOf(']');
        if (arrayStart >= 0 && arrayEnd > arrayStart)
        {
            try
            {
                return JsonNode.Parse(trimmed[arrayStart..(arrayEnd + 1)]);
            }
            catch (JsonException)
            {
            }
        }

        return null;
    }

    private static string GetErrorMessage(JsonNode? payload)
    {
        if (payload is not JsonObject obj)
        {
            return string.Empty;
        }

        if (obj["error"] is JsonObject error &&
            error["message"] is JsonValue errorMessage &&
            errorMessage.TryGetValue<string>(out var message) &&
            !string.IsNullOrWhiteSpace(message))
        {
            return message.Trim();
        }

        if (obj["message"] is JsonValue messageValue &&
            messageValue.TryGetValue<string>(out var rootMessage) &&
            !string.IsNullOrWhiteSpace(rootMessage))
        {
            return rootMessage.Trim();
        }

        return string.Empty;
    }

    private static string ResolveDockerCommand()
    {
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrWhiteSpace(programFiles))
        {
            var dockerExe = Path.Combine(programFiles, "Docker", "Docker", "resources", "bin", "docker.exe");
            if (File.Exists(dockerExe))
            {
                return dockerExe;
            }
        }

        return "docker";
    }

    private static bool IsNvidiaGpuAvailable()
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = "nvidia-smi",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            });
            if (process is null)
            {
                return false;
            }
            process.WaitForExit(5000);
            return process.HasExited && process.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }
}

internal sealed record CommandResult(int ExitCode, string Stdout, string Stderr);

internal sealed record WorkerState(bool IsRunning, string Message);

internal sealed record AudioRuntime(
    string InstanceName,
    int ApiPort,
    string ComposeProject,
    string SettingsPath,
    string PathsOverridePath,
    string ComputeMode,
    IReadOnlyList<string> InputRoots,
    string OutputRoot)
{
    public static AudioRuntime Ensure(ProductPaths paths)
    {
        var sourcePath = File.Exists(paths.SettingsPath)
            ? paths.SettingsPath
            : File.Exists(paths.SettingsExamplePath)
                ? paths.SettingsExamplePath
                : string.Empty;
        var root = !string.IsNullOrWhiteSpace(sourcePath)
            ? JsonNode.Parse(File.ReadAllText(sourcePath, Encoding.UTF8)) as JsonObject ?? new JsonObject()
            : new JsonObject();

        var runtime = root["runtime"] as JsonObject ?? new JsonObject();
        root["runtime"] = runtime;

        var instanceName = NormalizeInstanceName(GetString(runtime, "instanceName"));
        if (string.IsNullOrWhiteSpace(instanceName))
        {
            instanceName = Guid.NewGuid().ToString("N")[..10];
        }

        var apiPort = GetInt(runtime, "apiPort") ?? 19100;
        if (apiPort is < 1 or > 65535)
        {
            apiPort = 19100;
        }

        var inputRoots = GetStringArray(root, "inputRoots");
        var outputRoot = GetString(root, "outputRoot");
        var token = GetString(root, "huggingFaceToken");
        if (string.IsNullOrWhiteSpace(token))
        {
            token = GetString(root, "huggingfaceToken");
        }
        var computeMode = GetString(root, "computeMode").Trim().ToLowerInvariant();
        if (computeMode is not ("cpu" or "gpu"))
        {
            computeMode = "cpu";
        }

        var inputRootArray = new JsonArray();
        foreach (var inputRoot in inputRoots)
        {
            inputRootArray.Add(inputRoot);
        }

        var normalized = new JsonObject
        {
            ["schemaVersion"] = GetInt(root, "schemaVersion") ?? 1,
            ["inputRoots"] = inputRootArray,
            ["outputRoot"] = outputRoot,
            ["huggingFaceToken"] = token,
            ["computeMode"] = computeMode,
            ["runtime"] = new JsonObject
            {
                ["instanceName"] = instanceName,
                ["apiPort"] = apiPort,
            },
        };

        Directory.CreateDirectory(Path.GetDirectoryName(paths.SettingsPath) ?? paths.ProductRoot);
        File.WriteAllText(
            paths.SettingsPath,
            normalized.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        var composeProject = Environment.GetEnvironmentVariable("COMPOSE_PROJECT_NAME");
        if (string.IsNullOrWhiteSpace(composeProject))
        {
            composeProject = $"timeline-for-audio-{instanceName}";
        }

        var overridePath = Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH");
        if (string.IsNullOrWhiteSpace(overridePath))
        {
            overridePath = paths.DockerPathsOverridePath;
        }

        return new AudioRuntime(
            instanceName,
            apiPort,
            composeProject,
            paths.SettingsPath,
            Path.GetFullPath(overridePath),
            computeMode,
            inputRoots,
            outputRoot);
    }

    private static string NormalizeInstanceName(string value)
    {
        var text = value.Trim().ToLowerInvariant();
        if (text.StartsWith("local-", StringComparison.Ordinal))
        {
            text = text["local-".Length..];
        }

        var builder = new StringBuilder();
        var lastWasDash = false;
        foreach (var ch in text)
        {
            var isValid = ch is >= 'a' and <= 'z' || ch is >= '0' and <= '9';
            if (isValid)
            {
                builder.Append(ch);
                lastWasDash = false;
            }
            else if (!lastWasDash)
            {
                builder.Append('-');
                lastWasDash = true;
            }
        }

        return builder.ToString().Trim('-');
    }

    private static string GetString(JsonObject source, string name)
    {
        if (source[name] is JsonValue value)
        {
            if (value.TryGetValue<string>(out var text))
            {
                return text.Trim();
            }
            if (value.TryGetValue<int>(out var intValue))
            {
                return intValue.ToString();
            }
        }
        return string.Empty;
    }

    private static int? GetInt(JsonObject source, string name)
    {
        if (source[name] is not JsonValue value)
        {
            return null;
        }
        if (value.TryGetValue<int>(out var intValue))
        {
            return intValue;
        }
        if (value.TryGetValue<string>(out var textValue) && int.TryParse(textValue, out var parsed))
        {
            return parsed;
        }
        return null;
    }

    private static IReadOnlyList<string> GetStringArray(JsonObject source, string name)
    {
        if (source[name] is not JsonArray array)
        {
            return [];
        }

        return array
            .OfType<JsonValue>()
            .Select(value => value.TryGetValue<string>(out var text) ? text.Trim() : string.Empty)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }
}
