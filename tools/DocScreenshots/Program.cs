using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using Microsoft.Playwright;

var repoRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
var tempRoot = Path.Combine(Path.GetTempPath(), $"audio2timeline-docshots-{Guid.NewGuid():N}");
Directory.CreateDirectory(tempRoot);

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
await SeedRunsAsync(outputRoot);

var webProjectPath = Path.Combine(repoRoot, "web", "Audio2Timeline.Web.csproj");
var port = GetFreePort();
var baseUrl = $"http://127.0.0.1:{port}";

var startInfo = new ProcessStartInfo("dotnet", $"run --project \"{webProjectPath}\" --urls {baseUrl}")
{
    WorkingDirectory = repoRoot,
    UseShellExecute = false,
    RedirectStandardOutput = true,
    RedirectStandardError = true,
};
startInfo.Environment["AUDIO2TIMELINE_RUNTIME_DEFAULTS"] = runtimeDefaultsPath;
startInfo.Environment["AUDIO2TIMELINE_APPDATA_ROOT"] = appDataRoot;
startInfo.Environment["AUDIO2TIMELINE_UPLOADS_ROOT"] = uploadsRoot;
startInfo.Environment["AUDIO2TIMELINE_OUTPUTS_ROOT"] = outputRoot;
startInfo.Environment["AUDIO2TIMELINE_HF_ACCESS_OVERRIDE"] = "authorized";
startInfo.Environment["ASPNETCORE_ENVIRONMENT"] = "Development";

var process = new Process { StartInfo = startInfo };
if (!process.Start())
{
    throw new InvalidOperationException("Failed to start audio2timeline for documentation screenshots.");
}

try
{
    await WaitUntilReadyAsync(baseUrl, process);

    using var playwright = await Playwright.CreateAsync();
    await using var browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
    {
        Headless = true,
    });

    var screenshotRoot = Path.Combine(repoRoot, "docs", "screenshots");
    Directory.CreateDirectory(screenshotRoot);

    await CaptureSetAsync(browser, repoRoot, baseUrl, "en");
    await CaptureSetAsync(browser, repoRoot, baseUrl, "ja");
}
finally
{
    if (!process.HasExited)
    {
        process.Kill(entireProcessTree: true);
        await process.WaitForExitAsync();
    }

    try
    {
        if (Directory.Exists(tempRoot))
        {
            Directory.Delete(tempRoot, recursive: true);
        }
    }
    catch
    {
    }
}

static async Task CaptureSetAsync(IBrowser browser, string repoRoot, string baseUrl, string lang)
{
    var screenshotRoot = Path.Combine(repoRoot, "docs", "screenshots");
    var page = await browser.NewPageAsync(new BrowserNewPageOptions
    {
        ViewportSize = new ViewportSize { Width = 1360, Height = 1600 },
        DeviceScaleFactor = 1,
    });

    try
    {
        await page.GotoAsync($"{baseUrl}/language?lang={lang}", new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle });
        await CaptureAppShellAsync(page, Path.Combine(screenshotRoot, lang == "ja" ? "language.png" : "language-en.png"));

        await page.GotoAsync($"{baseUrl}/settings?lang={lang}", new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle });
        await CaptureAppShellAsync(page, Path.Combine(screenshotRoot, lang == "ja" ? "settings.png" : "settings-en.png"));

        await page.GotoAsync($"{baseUrl}/jobs/new?lang={lang}", new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle });
        await CaptureAppShellAsync(page, Path.Combine(screenshotRoot, lang == "ja" ? "new-job.png" : "new-job-en.png"));

        await page.GotoAsync($"{baseUrl}/jobs?lang={lang}", new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle });
        await CaptureAppShellAsync(page, Path.Combine(screenshotRoot, lang == "ja" ? "jobs.png" : "jobs-en.png"));

        await page.GotoAsync($"{baseUrl}/runs/run-e2e-active?lang={lang}", new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle });
        await page.EvaluateAsync(
            """
            () => {
                const description = document.querySelector(".page-description");
                if (description) {
                    description.textContent = "/workspace/outputs/runs/run-e2e-active";
                }
            }
            """);
        await CaptureAppShellAsync(page, Path.Combine(screenshotRoot, lang == "ja" ? "run-details.png" : "run-details-en.png"));
    }
    finally
    {
        await page.CloseAsync();
    }
}

static async Task CaptureAppShellAsync(IPage page, string path)
{
    await page.EvaluateAsync(
        """
        () => {
            const styleId = "docshot-style";
            let style = document.getElementById(styleId);
            if (!style) {
                style = document.createElement("style");
                style.id = styleId;
                document.head.appendChild(style);
            }

            style.textContent = `
                html, body {
                    min-height: 0 !important;
                    height: auto !important;
                    background: #e9edf4 !important;
                }

                .app-shell,
                .app-content,
                .app-main,
                .app-page {
                    min-height: 0 !important;
                    height: auto !important;
                }

                .app-main {
                    padding-bottom: 0 !important;
                }
            `;
        }
        """);

    await page.WaitForTimeoutAsync(100);
    await page.Locator(".app-shell").ScreenshotAsync(new LocatorScreenshotOptions { Path = path });
}

static async Task WaitUntilReadyAsync(string baseUrl, Process process)
{
    using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
    var deadline = DateTime.UtcNow.AddSeconds(45);

    while (DateTime.UtcNow < deadline)
    {
        if (process.HasExited)
        {
            throw new InvalidOperationException("Documentation screenshot host exited early.");
        }

        try
        {
            using var response = await client.GetAsync($"{baseUrl}/settings");
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

    throw new TimeoutException("Timed out waiting for documentation screenshot host.");
}

static object CreateRuntimeDefaults(string outputRoot) => new
{
    videoExtensions = new[] { ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm" },
    inputRoots = new object[]
    {
        new { id = "primary", displayName = "Primary Videos", path = "/shared/inputs/primary", enabled = true },
        new { id = "secondary", displayName = "Secondary Videos", path = "/shared/inputs/secondary", enabled = true },
        new { id = "uploads", displayName = "Uploaded Files", path = "/shared/uploads", enabled = true },
    },
    outputRoots = new object[]
    {
        new { id = "runs", displayName = "Runs", path = outputRoot, enabled = true },
    },
};

static async Task SeedSettingsAsync(string appDataRoot, string outputRoot)
{
    Directory.CreateDirectory(appDataRoot);
    Directory.CreateDirectory(Path.Combine(appDataRoot, "secrets"));

    var settings = new
    {
        schemaVersion = 1,
        videoExtensions = new[] { ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm" },
        inputRoots = new object[]
        {
            new { id = "primary", displayName = "Primary Videos", path = "/shared/inputs/primary", enabled = true },
            new { id = "secondary", displayName = "Secondary Videos", path = "/shared/inputs/secondary", enabled = true },
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
    await File.WriteAllTextAsync(
        Path.Combine(appDataRoot, "worker-capabilities.json"),
        JsonSerializer.Serialize(new
        {
            generatedAt = "2026-03-26T09:00:00+09:00",
            torchInstalled = true,
            torchCudaBuilt = true,
            gpuAvailable = true,
            deviceCount = 1,
            deviceNames = new[] { "NVIDIA GeForce RTX 4070" },
            deviceMemoryGiB = new[] { 12.0 },
            maxGpuMemoryGiB = 12.0,
            message = "GPU ready"
        }, new JsonSerializerOptions { WriteIndented = true }));
}

static async Task SeedRunsAsync(string outputRoot)
{
    await SeedRunAsync(
        outputRoot,
        jobId: "run-e2e-active",
        mediaId: "active-media-001",
        state: "running",
        stage: "transcribe",
        message: "Processing current file.",
        videosTotal: 3,
        videosDone: 1,
        videosSkipped: 0,
        videosFailed: 0,
        progressPercent: 41.7,
        estimatedRemainingSec: 522,
        createdAt: "2026-03-26T10:20:00+09:00",
        updatedAt: "2026-03-26T10:24:30+09:00",
        completedAt: null,
        currentMedia: "2026-03-25-team-sync.mp4",
        includeTimeline: true);

    await SeedRunAsync(
        outputRoot,
        jobId: "run-e2e-completed",
        mediaId: "sample-media-001",
        state: "completed",
        stage: "completed",
        message: "Job completed.",
        videosTotal: 1,
        videosDone: 1,
        videosSkipped: 0,
        videosFailed: 0,
        progressPercent: 100.0,
        estimatedRemainingSec: 0,
        createdAt: "2026-03-24T09:00:00+09:00",
        updatedAt: "2026-03-24T09:02:10+09:00",
        completedAt: "2026-03-24T09:02:10+09:00",
        currentMedia: null,
        includeTimeline: true);

    await SeedRunAsync(
        outputRoot,
        jobId: "run-e2e-pending",
        mediaId: "queued-media-001",
        state: "pending",
        stage: "queued",
        message: "Queued for worker pickup.",
        videosTotal: 2,
        videosDone: 0,
        videosSkipped: 0,
        videosFailed: 0,
        progressPercent: 0.0,
        estimatedRemainingSec: null,
        createdAt: "2026-03-26T10:26:00+09:00",
        updatedAt: "2026-03-26T10:26:10+09:00",
        completedAt: null,
        currentMedia: null,
        includeTimeline: false);
}

static async Task SeedRunAsync(
    string outputRoot,
    string jobId,
    string mediaId,
    string state,
    string stage,
    string message,
    int videosTotal,
    int videosDone,
    int videosSkipped,
    int videosFailed,
    double progressPercent,
    double? estimatedRemainingSec,
    string createdAt,
    string updatedAt,
    string? completedAt,
    string? currentMedia,
    bool includeTimeline)
{
    var runRoot = Path.Combine(outputRoot, jobId);
    var publicRunRoot = $"/workspace/outputs/runs/{jobId}";
    var publicTimelineIndexPath = $"{publicRunRoot}/llm/timeline_index.jsonl";
    Directory.CreateDirectory(runRoot);
    Directory.CreateDirectory(Path.Combine(runRoot, "llm"));
    Directory.CreateDirectory(Path.Combine(runRoot, "logs"));
    Directory.CreateDirectory(Path.Combine(runRoot, "media", mediaId, "timeline"));

    var request = new
    {
        schema_version = 1,
        job_id = jobId,
        created_at = createdAt,
        output_root_id = "runs",
        output_root_path = "/workspace/outputs/runs",
        profile = "quality-first",
        compute_mode = "gpu",
        processing_quality = "high",
        reprocess_duplicates = false,
        token_enabled = true,
        input_items = new object[]
        {
            new
            {
                input_id = "upload-0001",
                source_kind = "upload",
                source_id = "uploads",
                original_path = "meeting-sample.mp4",
                display_name = "meeting-sample.mp4",
                size_bytes = 1048576,
                uploaded_path = (string?)null,
            },
        },
    };

    var status = new
    {
        schema_version = 1,
        job_id = jobId,
        state,
        current_stage = stage,
        message,
        warnings = Array.Empty<string>(),
        videos_total = videosTotal,
        videos_done = videosDone,
        videos_skipped = videosSkipped,
        videos_failed = videosFailed,
        current_media = currentMedia,
        current_media_elapsed_sec = 93.2,
        processed_duration_sec = 1420.5,
        total_duration_sec = 3410.7,
        estimated_remaining_sec = estimatedRemainingSec,
        progress_percent = progressPercent,
        started_at = createdAt,
        updated_at = updatedAt,
        completed_at = completedAt,
    };

    var result = new
    {
        schema_version = 1,
        job_id = jobId,
        state,
        run_dir = publicRunRoot,
        output_root_id = "runs",
        output_root_path = "/workspace/outputs/runs",
        processed_count = videosDone,
        skipped_count = videosSkipped,
        error_count = videosFailed,
        batch_count = 1,
        timeline_index_path = publicTimelineIndexPath,
        warnings = Array.Empty<string>(),
    };

    var manifest = new
    {
        schema_version = 1,
        job_id = jobId,
        generated_at = updatedAt,
        items = new object[]
        {
            new
            {
                input_id = "upload-0001",
                source_kind = "upload",
                original_path = "meeting-sample.mp4",
                file_name = "meeting-sample.mp4",
                size_bytes = 1048576,
                duration_seconds = 70.417,
                sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                duplicate_status = "new",
                duplicate_of = (string?)null,
                media_id = mediaId,
                status = includeTimeline ? "completed" : state,
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
    await File.WriteAllTextAsync(Path.Combine(runRoot, "logs", "worker.log"), "[info] sample worker log line\n[info] transcribe in progress\n");
    await File.WriteAllTextAsync(Path.Combine(runRoot, "llm", "timeline_index.jsonl"), $"{{\"media_id\":\"{mediaId}\"}}\n");
    await File.WriteAllTextAsync(Path.Combine(runRoot, "llm", "batch-001.md"), $"# Batch 001\n\nIncluded: {mediaId}\n");
    if (includeTimeline)
    {
        await File.WriteAllTextAsync(
            Path.Combine(runRoot, "media", mediaId, "timeline", "timeline.md"),
            """
            # Video Timeline

            - Source: `/workspace/inputs/meeting-sample.mp4`
            - Media ID: `sample-media-001`
            - Duration: `70.417s`

            ## 00:00:11.179 - 00:00:57.194
            Speech:
            SPEAKER_00: Hello, this is a public test sample.

            Screen:
            OCR detected text. Top lines: Example / Sample / Timeline

            Screen change:
            Initial frame.
            """);
    }
}

static int GetFreePort()
{
    var listener = new TcpListener(IPAddress.Loopback, 0);
    listener.Start();
    var port = ((IPEndPoint)listener.LocalEndpoint).Port;
    listener.Stop();
    return port;
}
