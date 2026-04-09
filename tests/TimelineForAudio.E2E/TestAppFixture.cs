using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TimelineForAudio.E2E;

internal sealed class TestAppFixture : IAsyncDisposable
{
    private const string CurrentConversionSignature = "c681195f95a364a381faec19ae5d1b9632f633ed844c36cfde0dec2e757324c2";
    private readonly StringBuilder _logs = new();
    private readonly Process _process;

    private TestAppFixture(string repoRoot, string tempRoot, int port, Process process)
    {
        RepoRoot = repoRoot;
        TempRoot = tempRoot;
        Port = port;
        BaseUrl = $"http://127.0.0.1:{port}";
        _process = process;
        _process.OutputDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                lock (_logs)
                {
                    _logs.AppendLine(args.Data);
                }
            }
        };
        _process.ErrorDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                lock (_logs)
                {
                    _logs.AppendLine(args.Data);
                }
            }
        };
    }

    public string RepoRoot { get; }

    public string TempRoot { get; }

    public int Port { get; }

    public string BaseUrl { get; }

    public string CompletedJobId => "job-e2e-completed";

    public string CompletedMediaId => "sample-media-001";

    public string PartialFailedJobId => "job-e2e-partial";

    public string PartialFailedMediaId => "sample-media-002";

    public string FailedNoTimelineJobId => "job-e2e-failed-no-timeline";

    public string DuplicateSkippedJobId => "job-e2e-duplicate-skip";

    public string DuplicateSkippedMediaId => "sample-media-duplicate";

    public string LegacyDuplicateProgressJobId => "job-e2e-legacy-duplicate";

    public string DuplicateUploadPath => Path.Combine(TempRoot, "fixtures", "already-processed.wav");

    public static async Task<TestAppFixture> StartAsync()
    {
        var repoRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
        var tempRoot = Path.Combine(Path.GetTempPath(), $"TimelineForAudio-e2e-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempRoot);

        var port = GetFreePort();
        var fixture = await CreateAndStartAsync(repoRoot, tempRoot, port);
        await fixture.WaitUntilReadyAsync();
        return fixture;
    }

    private static async Task<TestAppFixture> CreateAndStartAsync(string repoRoot, string tempRoot, int port)
    {
        var appDataRoot = Path.Combine(tempRoot, "app-data");
        var uploadsRoot = Path.Combine(tempRoot, "uploads");
        var outputRoot = Path.Combine(tempRoot, "outputs", "runs");
        var runtimeDefaultsPath = Path.Combine(tempRoot, "runtime.defaults.json");
        Directory.CreateDirectory(appDataRoot);
        Directory.CreateDirectory(uploadsRoot);
        Directory.CreateDirectory(outputRoot);

        await File.WriteAllTextAsync(
            runtimeDefaultsPath,
            JsonSerializer.Serialize(CreateRuntimeDefaults(outputRoot), new JsonSerializerOptions { WriteIndented = true }));

        await SeedSettingsAsync(appDataRoot, outputRoot);
        await SeedCompletedRunAsync(outputRoot, tempRoot);
        await SeedPartiallyFailedRunAsync(outputRoot);
        await SeedFailedRunWithoutTimelineAsync(outputRoot);
        await SeedDuplicateCatalogEntryAsync(outputRoot, tempRoot);
        await SeedDuplicateSkippedRunAsync(outputRoot);
        await SeedLegacyDuplicateProgressRunAsync(outputRoot);

        var appDllPath = ResolveAppDllPath(repoRoot);
        var dotnetHostPath = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH");
        var startInfo = new ProcessStartInfo(
            string.IsNullOrWhiteSpace(dotnetHostPath) ? "dotnet" : dotnetHostPath,
            $"\"{appDllPath}\" --urls http://127.0.0.1:{port}")
        {
            WorkingDirectory = repoRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.Environment["TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS"] = runtimeDefaultsPath;
        startInfo.Environment["TIMELINE_FOR_AUDIO_APPDATA_ROOT"] = appDataRoot;
        startInfo.Environment["TIMELINE_FOR_AUDIO_UPLOADS_ROOT"] = uploadsRoot;
        startInfo.Environment["TIMELINE_FOR_AUDIO_OUTPUTS_ROOT"] = outputRoot;
        startInfo.Environment["TIMELINE_FOR_AUDIO_HF_ACCESS_OVERRIDE"] = "authorized";
        startInfo.Environment["ASPNETCORE_ENVIRONMENT"] = "Development";

        var process = new Process { StartInfo = startInfo };
        var fixture = new TestAppFixture(repoRoot, tempRoot, port, process);
        if (!process.Start())
        {
            throw new InvalidOperationException("Failed to start the ASP.NET Core test host.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return fixture;
    }

    private static string ResolveAppDllPath(string repoRoot)
    {
        var candidates = new[]
        {
            Path.Combine(repoRoot, "web", "bin", "Debug", "net10.0", "TimelineForAudio.Web.dll"),
            Path.Combine(repoRoot, "web", "bin", "Release", "net10.0", "TimelineForAudio.Web.dll"),
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new FileNotFoundException(
            $"TimelineForAudio.Web.dll was not found in any expected build output.{Environment.NewLine}{string.Join(Environment.NewLine, candidates)}");
    }

    public async Task<string> CreateRunningRunAsync()
    {
        var jobId = $"job-e2e-running-{Guid.NewGuid():N}"[..28];
        await SeedRunningRunAsync(Path.Combine(TempRoot, "outputs", "runs"), jobId);
        return jobId;
    }

    public async Task<string> CreatePendingRunAsync()
    {
        var jobId = $"job-e2e-pending-{Guid.NewGuid():N}"[..28];
        await SeedPendingRunAsync(Path.Combine(TempRoot, "outputs", "runs"), jobId);
        return jobId;
    }

    public Task DeleteRunAsync(string jobId)
    {
        var runRoot = Path.Combine(TempRoot, "outputs", "runs", jobId);
        if (Directory.Exists(runRoot))
        {
            Directory.Delete(runRoot, recursive: true);
        }

        return Task.CompletedTask;
    }

    public async Task<(string ComputeMode, string ProcessingQuality, bool ReprocessDuplicates)> ReadJobRequestSettingsAsync(string jobId)
    {
        var requestPath = Path.Combine(TempRoot, "outputs", "runs", jobId, "request.json");
        await using var stream = File.OpenRead(requestPath);
        using var document = await JsonDocument.ParseAsync(stream);
        var root = document.RootElement;
        return (
            root.GetProperty("compute_mode").GetString() ?? "",
            root.GetProperty("processing_quality").GetString() ?? "",
            root.GetProperty("reprocess_duplicates").GetBoolean());
    }

    public async Task SetTokenAsync(string? token)
    {
        var tokenPath = Path.Combine(TempRoot, "app-data", "secrets", "huggingface.token");
        if (string.IsNullOrWhiteSpace(token))
        {
            if (File.Exists(tokenPath))
            {
                File.Delete(tokenPath);
            }

            return;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(tokenPath)!);
        await File.WriteAllTextAsync(tokenPath, token);
    }

    private async Task WaitUntilReadyAsync()
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var deadline = DateTime.UtcNow.AddSeconds(30);

        while (DateTime.UtcNow < deadline)
        {
            if (_process.HasExited)
            {
                throw new InvalidOperationException($"The ASP.NET Core test host exited early.{Environment.NewLine}{GetLogs()}");
            }

            try
            {
                using var response = await client.GetAsync($"{BaseUrl}/");
                if (response.StatusCode == HttpStatusCode.OK)
                {
                    return;
                }
            }
            catch
            {
            }

            await Task.Delay(500);
        }

        throw new TimeoutException($"Timed out waiting for the ASP.NET Core test host.{Environment.NewLine}{GetLogs()}");
    }

    private static object CreateRuntimeDefaults(string outputRoot) => new
    {
        audioExtensions = new[] { ".mp3", ".wav", ".m4a", ".aac", ".flac" },
        inputRoots = new object[]
        {
            new { id = "primary", displayName = "Primary Audio", path = "/shared/inputs/primary", enabled = true },
            new { id = "secondary", displayName = "Secondary Audio", path = "/shared/inputs/secondary", enabled = true },
            new { id = "uploads", displayName = "Uploaded Files", path = "/shared/uploads", enabled = true },
        },
        outputRoots = new object[]
        {
            new { id = "runs", displayName = "Runs", path = outputRoot, enabled = true },
        },
    };

    private static async Task SeedSettingsAsync(string appDataRoot, string outputRoot)
    {
        Directory.CreateDirectory(appDataRoot);
        Directory.CreateDirectory(Path.Combine(appDataRoot, "secrets"));

        var settings = new
        {
            schemaVersion = 1,
            audioExtensions = new[] { ".mp3", ".wav", ".m4a", ".aac", ".flac" },
            inputRoots = new object[]
            {
                new { id = "primary", displayName = "Primary Audio", path = "/shared/inputs/primary", enabled = true },
                new { id = "secondary", displayName = "Secondary Audio", path = "/shared/inputs/secondary", enabled = true },
                new { id = "uploads", displayName = "Uploaded Files", path = "/shared/uploads", enabled = true },
            },
            outputRoots = new object[]
            {
                new { id = "runs", displayName = "Runs", path = outputRoot, enabled = true },
            },
            huggingfaceTermsConfirmed = true,
            computeMode = "gpu",
            processingQuality = "high",
            uiLanguage = "en",
            languageSelected = true,
        };

        await File.WriteAllTextAsync(
            Path.Combine(appDataRoot, "settings.json"),
            JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true }));
        await File.WriteAllTextAsync(
            Path.Combine(appDataRoot, "secrets", "huggingface.token"),
            "hf_test_token_value");
    }

    private static async Task SeedCompletedRunAsync(string outputRoot, string tempRoot)
    {
        const string jobId = "job-e2e-completed";
        const string mediaId = "sample-media-001";

        var runRoot = Path.Combine(outputRoot, jobId);
        var fixturesRoot = Path.Combine(tempRoot, "fixtures");
        var uploadedPath = Path.Combine(fixturesRoot, "sample-call.wav");
        Directory.CreateDirectory(fixturesRoot);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));
        Directory.CreateDirectory(Path.Combine(runRoot, "media", mediaId, "timeline"));
        await File.WriteAllBytesAsync(uploadedPath, Encoding.UTF8.GetBytes("TimelineForAudio-e2e-completed-source"));

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T09:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            compute_mode = "cpu",
            processing_quality = "standard",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "sample-call.wav",
                    display_name = "sample-call.wav",
                    size_bytes = 1048576,
                    uploaded_path = uploadedPath.Replace("\\", "/"),
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            current_stage = "completed",
            message = "Job completed.",
            warnings = Array.Empty<string>(),
            items_total = 1,
            items_done = 1,
            items_skipped = 0,
            items_failed = 0,
            current_item = (string?)null,
            current_item_elapsed_sec = 0.0,
            processed_duration_sec = 70.417,
            total_duration_sec = 70.417,
            estimated_remaining_sec = 0.0,
            started_at = "2026-03-24T09:00:03+09:00",
            updated_at = "2026-03-24T09:02:10+09:00",
            completed_at = "2026-03-24T09:02:10+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 1,
            skipped_count = 0,
            error_count = 0,
            batch_count = 1,
            timeline_index_path = Path.Combine(runRoot, "llm", "timeline_index.jsonl").Replace("\\", "/"),
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T09:02:10+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "sample-call.wav",
                    file_name = "sample-call.wav",
                    size_bytes = 1048576,
                    duration_seconds = 70.417,
                    source_hash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    conversion_signature = CurrentConversionSignature,
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    audio_id = mediaId,
                    status = "completed",
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] completed test run\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "llm", "timeline_index.jsonl"), "{\"media_id\":\"sample-media-001\"}\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "llm", "batch-001.md"),
            "# Batch 001\n\nIncluded: sample-media-001\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "timeline", "timeline.md"),
            """
            # Audio Timeline

            - Source: `sample-call.wav`
            - Audio ID: `sample-media-001`
            - Duration: `70.417s`

            ## 00:00:11.179 - 00:00:57.194
            - Speaker: `SPEAKER_00`
            - Text: Hello, this is a public test sample.
            - Pause before: `0.000s`
            - Overlap with previous: `0.000s`
            - Estimated units/min: `155.4`
            """);
    }

    private static async Task SeedDuplicateCatalogEntryAsync(string outputRoot, string tempRoot)
    {
        var fixturesRoot = Path.Combine(tempRoot, "fixtures");
        Directory.CreateDirectory(fixturesRoot);

        var duplicatePath = Path.Combine(fixturesRoot, "already-processed.wav");
        var duplicateBytes = Encoding.UTF8.GetBytes("TimelineForAudio-e2e-duplicate-seed");
        await File.WriteAllBytesAsync(duplicatePath, duplicateBytes);

        var source_hash = Convert.ToHexString(SHA256.HashData(duplicateBytes)).ToLowerInvariant();
        var catalogDirectory = Path.Combine(outputRoot, ".timeline-for-audio");
        Directory.CreateDirectory(catalogDirectory);

        var catalogRow = new
        {
            job_id = "job-e2e-completed",
            run_dir = Path.Combine(outputRoot, "job-e2e-completed").Replace("\\", "/"),
            audio_id = "sample-media-001",
            source_hash,
            conversion_signature = CurrentConversionSignature,
            original_path = "already-processed.wav",
            duration_seconds = 12.5,
            timeline_path = Path.Combine(outputRoot, "job-e2e-completed", "media", "sample-media-001", "timeline", "timeline.md").Replace("\\", "/"),
            created_at = "2026-03-24T09:02:07+09:00",
        };

        await File.AppendAllTextAsync(
            Path.Combine(catalogDirectory, "catalog.jsonl"),
            JsonSerializer.Serialize(catalogRow) + Environment.NewLine);
    }

    private static async Task SeedPartiallyFailedRunAsync(string outputRoot)
    {
        const string jobId = "job-e2e-partial";
        const string mediaId = "sample-media-002";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));
        Directory.CreateDirectory(Path.Combine(runRoot, "media", mediaId, "timeline"));

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T10:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            reprocess_duplicates = false,
            token_enabled = true,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "good-call.wav",
                    display_name = "good-call.wav",
                    size_bytes = 2097152,
                    uploaded_path = (string?)null,
                },
                new
                {
                    input_id = "upload-0002",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "broken-call.wav",
                    display_name = "broken-call.wav",
                    size_bytes = 3145728,
                    uploaded_path = (string?)null,
                },
            },
        };

        var warnings = new[]
        {
            "broken-call.wav: CUDA failed with error unknown error",
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "failed",
            current_stage = "failed",
            message = "Job finished with errors.",
            warnings,
            items_total = 2,
            items_done = 1,
            items_skipped = 0,
            items_failed = 1,
            current_item = (string?)null,
            current_item_elapsed_sec = 0.0,
            processed_duration_sec = 120.125,
            total_duration_sec = 180.775,
            estimated_remaining_sec = 0.0,
            progress_percent = 100.0,
            started_at = "2026-03-24T10:00:03+09:00",
            updated_at = "2026-03-24T10:05:10+09:00",
            completed_at = "2026-03-24T10:05:10+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "failed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 1,
            skipped_count = 0,
            error_count = 1,
            batch_count = 1,
            timeline_index_path = Path.Combine(runRoot, "llm", "timeline_index.jsonl").Replace("\\", "/"),
            warnings,
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T10:05:10+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "good-call.wav",
                    file_name = "good-call.wav",
                    size_bytes = 2097152,
                    duration_seconds = 120.125,
                    source_hash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    audio_id = mediaId,
                    status = "completed",
                },
                new
                {
                    input_id = "upload-0002",
                    source_kind = "upload",
                    original_path = "broken-call.wav",
                    file_name = "broken-call.wav",
                    size_bytes = 3145728,
                    duration_seconds = 60.650,
                    source_hash = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    audio_id = "broken-media-003",
                    status = "failed",
                },
            },
        };

        var sourceInfo = new
        {
            original_path = "good-call.wav",
            resolved_path = "good-call.wav",
            display_name = "good-call.wav",
            captured_at = "2026-03-24 10-00-00",
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "logs", "worker.log"),
            """
            [info] completed good-call.wav
            [error] broken-call.wav: CUDA failed with error unknown error
            [info] job finished with errors
            """);
        await File.WriteAllTextAsync(Path.Combine(runRoot, "llm", "timeline_index.jsonl"), "{\"media_id\":\"sample-media-002\"}\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "llm", "batch-001.md"),
            "# Batch 001\n\nIncluded: sample-media-002\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "source.json"),
            JsonSerializer.Serialize(sourceInfo, jsonOptions));
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "timeline", "timeline.md"),
            """
            # Audio Timeline

            - Source: `good-call.wav`
            - Audio ID: `sample-media-002`
            - Duration: `120.125s`

            ## 00:00:05.000 - 00:01:10.000
            - Speaker: `SPEAKER_00`
            - Text: This is the successful part of a partially failed run.
            - Pause before: `0.000s`
            - Overlap with previous: `0.000s`
            - Estimated units/min: `149.2`
            """);
    }

    private static async Task SeedDuplicateSkippedRunAsync(string outputRoot)
    {
        const string jobId = "job-e2e-duplicate-skip";
        const string mediaId = "sample-media-duplicate";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));

        var duplicateBytes = Encoding.UTF8.GetBytes("TimelineForAudio-e2e-duplicate-seed");
        var source_hash = Convert.ToHexString(SHA256.HashData(duplicateBytes)).ToLowerInvariant();
        var referencedTimelinePath = Path.Combine(outputRoot, "job-e2e-completed", "media", "sample-media-001", "timeline", "timeline.md")
            .Replace("\\", "/");

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T11:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "already-processed.wav",
                    display_name = "already-processed.wav",
                    size_bytes = duplicateBytes.Length,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            current_stage = "completed",
            message = "Job completed with duplicate skips.",
            warnings = Array.Empty<string>(),
            current_item = (string?)null,
            items_total = 1,
            items_done = 0,
            items_skipped = 1,
            items_failed = 0,
            total_duration_sec = 12.5,
            processed_duration_sec = 12.5,
            current_item_elapsed_sec = 0.0,
            current_stage_elapsed_sec = 0.0,
            estimated_remaining_sec = 0.0,
            progress_percent = 100.0,
            started_at = "2026-03-24T11:00:00+09:00",
            updated_at = "2026-03-24T11:00:03+09:00",
            completed_at = "2026-03-24T11:00:03+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 0,
            skipped_count = 1,
            error_count = 0,
            batch_count = 0,
            timeline_index_path = (string?)null,
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T11:00:03+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "already-processed.wav",
                    file_name = "already-processed.wav",
                    size_bytes = duplicateBytes.Length,
                    duration_seconds = 12.5,
                    source_hash,
                    conversion_signature = CurrentConversionSignature,
                    duplicate_status = "duplicate_skip",
                    duplicate_of = referencedTimelinePath,
                    audio_id = mediaId,
                    status = "skipped_duplicate",
                    container_name = "mp4",
                    video_codec = "h264",
                    audio_codec = "aac",
                    width = 1280,
                    height = 720,
                    frame_rate = 30.0,
                    audio_channels = 2,
                    audio_sample_rate = 48000,
                    has_video = true,
                    has_audio = true,
                    captured_at = "2026-03-24T11:00:00+09:00",
                    processing_wall_seconds = 0.0,
                    stage_elapsed_seconds = new { },
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] duplicate timeline reused\n");
    }

    private static async Task SeedLegacyDuplicateProgressRunAsync(string outputRoot)
    {
        const string jobId = "job-e2e-legacy-duplicate";
        const string mediaId = "sample-media-legacy-duplicate";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));

        var duplicateBytes = Encoding.UTF8.GetBytes("TimelineForAudio-e2e-legacy-duplicate-seed");
        var referencedTimelinePath = Path.Combine(outputRoot, "job-e2e-completed", "media", "sample-media-001", "timeline", "timeline.md")
            .Replace("\\", "/");

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-23T10:30:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            compute_mode = "cpu",
            processing_quality = "standard",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "legacy-duplicate.mp4",
                    display_name = "legacy-duplicate.mp4",
                    size_bytes = duplicateBytes.Length,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            current_stage = "completed",
            message = "Legacy duplicate run completed.",
            warnings = Array.Empty<string>(),
            current_item = (string?)null,
            items_total = 1,
            items_done = 0,
            items_skipped = 1,
            items_failed = 0,
            total_duration_sec = 18.0,
            processed_duration_sec = 18.0,
            current_item_elapsed_sec = 0.0,
            current_stage_elapsed_sec = 0.0,
            estimated_remaining_sec = 0.0,
            progress_percent = 0.0,
            started_at = "2026-03-23T10:30:00+09:00",
            updated_at = "2026-03-23T10:30:04+09:00",
            completed_at = "2026-03-23T10:30:04+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "completed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 0,
            skipped_count = 1,
            error_count = 0,
            batch_count = 0,
            timeline_index_path = (string?)null,
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-23T10:30:04+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "legacy-duplicate.mp4",
                    file_name = "legacy-duplicate.mp4",
                    size_bytes = duplicateBytes.Length,
                    duration_seconds = 18.0,
                    source_hash = "legacy-duplicate-sha256",
                    conversion_signature = CurrentConversionSignature,
                    duplicate_status = "duplicate_skip",
                    duplicate_of = referencedTimelinePath,
                    audio_id = mediaId,
                    status = "skipped_duplicate",
                    container_name = "mp4",
                    video_codec = "h264",
                    audio_codec = "aac",
                    width = 1920,
                    height = 1080,
                    frame_rate = 30.0,
                    audio_channels = 2,
                    audio_sample_rate = 48000,
                    has_video = true,
                    has_audio = true,
                    captured_at = "2026-03-23T10:30:00+09:00",
                    processing_wall_seconds = 0.0,
                    stage_elapsed_seconds = new { },
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] legacy duplicate timeline reused\n");
    }

    private static async Task SeedFailedRunWithoutTimelineAsync(string outputRoot)
    {
        const string jobId = "job-e2e-failed-no-timeline";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));

        var warnings = new[]
        {
            "orphaned-success.mp4: timeline output was not written",
        };

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T11:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "orphaned-success.mp4",
                    display_name = "orphaned-success.mp4",
                    size_bytes = 1024,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "failed",
            current_stage = "failed",
            message = "Job finished with errors.",
            warnings,
            items_total = 1,
            items_done = 1,
            items_skipped = 0,
            items_failed = 0,
            current_item = (string?)null,
            current_item_elapsed_sec = 0.0,
            processed_duration_sec = 10.0,
            total_duration_sec = 10.0,
            estimated_remaining_sec = 0.0,
            progress_percent = 100.0,
            started_at = "2026-03-24T11:00:03+09:00",
            updated_at = "2026-03-24T11:00:15+09:00",
            completed_at = "2026-03-24T11:00:15+09:00",
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "failed",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 1,
            skipped_count = 0,
            error_count = 0,
            batch_count = 0,
            timeline_index_path = (string?)null,
            warnings,
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T11:00:15+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "orphaned-success.mp4",
                    file_name = "orphaned-success.mp4",
                    size_bytes = 1024,
                    duration_seconds = 10.0,
                    source_hash = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    audio_id = "orphaned-media-001",
                    status = "completed",
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[error] timeline output missing\n");
    }

    private static async Task SeedRunningRunAsync(string outputRoot, string jobId)
    {
        const string mediaId = "sample-media-running";

        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));
        Directory.CreateDirectory(Path.Combine(runRoot, "media", mediaId, "timeline"));

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T12:00:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "running-call.wav",
                    display_name = "running-call.wav",
                    size_bytes = 2048,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "running",
            current_stage = "transcribe",
            message = "Running faster-whisper transcription.",
            warnings = Array.Empty<string>(),
            items_total = 1,
            items_done = 1,
            items_skipped = 0,
            items_failed = 0,
            current_item = "running-call.wav",
            current_item_elapsed_sec = 30.0,
            processed_duration_sec = 30.0,
            total_duration_sec = 60.0,
            estimated_remaining_sec = 30.0,
            progress_percent = 50.0,
            started_at = "2026-03-24T12:00:03+09:00",
            updated_at = "2026-03-24T12:00:33+09:00",
            completed_at = (string?)null,
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "running",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 1,
            skipped_count = 0,
            error_count = 0,
            batch_count = 0,
            timeline_index_path = (string?)null,
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T12:00:33+09:00",
            items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    original_path = "running-call.wav",
                    file_name = "running-call.wav",
                    size_bytes = 2048,
                    duration_seconds = 60.0,
                    source_hash = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                    duplicate_status = "new",
                    duplicate_of = (string?)null,
                    audio_id = mediaId,
                    status = "completed",
                },
            },
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] still processing\n");
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "timeline", "timeline.md"),
            """
            # Audio Timeline

            - Source: `running-call.wav`
            - Audio ID: `sample-media-running`
            """);
    }

    private static async Task SeedPendingRunAsync(string outputRoot, string jobId)
    {
        var runRoot = Path.Combine(outputRoot, jobId);
        Directory.CreateDirectory(runRoot);
        Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
        Directory.CreateDirectory(Path.Combine(runRoot, "logs"));

        var request = new
        {
            schema_version = 1,
            job_id = jobId,
            created_at = "2026-03-24T12:05:00+09:00",
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            profile = "quality-first",
            compute_mode = "cpu",
            processing_quality = "standard",
            reprocess_duplicates = false,
            token_enabled = false,
            input_items = new object[]
            {
                new
                {
                    input_id = "upload-0001",
                    source_kind = "upload",
                    source_id = "uploads",
                    original_path = "pending-call.mp4",
                    display_name = "pending-call.mp4",
                    size_bytes = 1024,
                    uploaded_path = (string?)null,
                },
            },
        };

        var status = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "pending",
            current_stage = "queued",
            message = "Queued for worker pickup.",
            warnings = Array.Empty<string>(),
            items_total = 1,
            items_done = 0,
            items_skipped = 0,
            items_failed = 0,
            current_item = (string?)null,
            current_item_elapsed_sec = 0.0,
            current_stage_elapsed_sec = 0.0,
            processed_duration_sec = 0.0,
            total_duration_sec = 45.0,
            estimated_remaining_sec = 45.0,
            progress_percent = 0.0,
            started_at = (string?)null,
            updated_at = "2026-03-24T12:05:00+09:00",
            completed_at = (string?)null,
        };

        var result = new
        {
            schema_version = 1,
            job_id = jobId,
            state = "pending",
            run_dir = runRoot.Replace("\\", "/"),
            output_root_id = "runs",
            output_root_path = outputRoot.Replace("\\", "/"),
            processed_count = 0,
            skipped_count = 0,
            error_count = 0,
            batch_count = 0,
            timeline_index_path = (string?)null,
            warnings = Array.Empty<string>(),
        };

        var manifest = new
        {
            schema_version = 1,
            job_id = jobId,
            generated_at = "2026-03-24T12:05:00+09:00",
            items = Array.Empty<object>(),
        };

        var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
        await File.WriteAllTextAsync(Path.Combine(runRoot, "request.json"), JsonSerializer.Serialize(request, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "status.json"), JsonSerializer.Serialize(status, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "result.json"), JsonSerializer.Serialize(result, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "manifest.json"), JsonSerializer.Serialize(manifest, jsonOptions));
        await File.WriteAllTextAsync(Path.Combine(runRoot, "RUN_INFO.md"), "# Run Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "NOTICE.md"), "# Notice\n");
        await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] pending test run\n");
    }

    private static int GetFreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private string GetLogs()
    {
        lock (_logs)
        {
            return _logs.ToString();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (!_process.HasExited)
        {
            _process.Kill(entireProcessTree: true);
            await _process.WaitForExitAsync();
        }

        try
        {
            if (Directory.Exists(TempRoot))
            {
                Directory.Delete(TempRoot, recursive: true);
            }
        }
        catch
        {
        }
    }
}
