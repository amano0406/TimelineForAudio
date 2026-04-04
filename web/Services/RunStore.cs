using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using Audio2Timeline.Web.Infrastructure;
using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

public sealed class RunStore(AppPaths paths, SettingsStore settingsStore, ScanService scanService)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<IReadOnlyList<UploadedFileReference>> SaveUploadsAsync(
        IEnumerable<IFormFile> files,
        CancellationToken cancellationToken = default)
    {
        var list = files?.Where(static file => file.Length > 0).ToList() ?? [];
        if (list.Count == 0)
        {
            return [];
        }

        var uploadFolder = Path.Combine(
            paths.UploadsRoot,
            $"upload-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..36]);
        Directory.CreateDirectory(uploadFolder);

        var stored = new List<UploadedFileReference>();
        foreach (var file in list)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var safeName = MakeSafeFileName(file.FileName);
            var storedFileName = $"{stored.Count + 1:D4}-{safeName}";
            var storedPath = Path.Combine(uploadFolder, storedFileName);
            if (File.Exists(storedPath))
            {
                storedFileName = $"{stored.Count + 1:D4}-{Guid.NewGuid():N}".Replace("--", "-");
                storedFileName = $"{storedFileName[..Math.Min(storedFileName.Length, 20)]}-{safeName}";
                storedPath = Path.Combine(uploadFolder, storedFileName);
            }

            await using var stream = File.Create(storedPath);
            await file.CopyToAsync(stream, cancellationToken);
            stored.Add(new UploadedFileReference
            {
                ReferenceId = $"{Path.GetFileName(uploadFolder)}:{storedFileName}",
                StoredPath = storedPath,
                OriginalName = file.FileName,
                SizeBytes = file.Length,
            });
        }

        return stored;
    }

    public async Task<(string JobId, string RunDirectory)> CreateJobAsync(
        CreateJobCommand command,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var outputRoot = ResolveOutputRoot(settings, command.OutputRootId);
        if (outputRoot is null)
        {
            throw new InvalidOperationException("No enabled output root is configured.");
        }

        Directory.CreateDirectory(outputRoot.Path);
        var scannedItems = await scanService.ScanAsync(command.SourceIds, cancellationToken);
        var selectedPaths = command.SelectedPaths
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (selectedPaths.Count > 0)
        {
            scannedItems = scannedItems
                .Where(item => selectedPaths.Contains(item.OriginalPath))
                .ToList();
        }

        var inputItems = scannedItems
            .Select((item, index) => new InputItemDocument
            {
                InputId = $"scan-{index + 1:D4}",
                SourceKind = item.SourceKind,
                SourceId = item.SourceId,
                OriginalPath = item.OriginalPath,
                DisplayName = item.DisplayName,
                SizeBytes = item.SizeBytes,
            })
            .ToList();

        var uploadItems = command.UploadedFiles
            .Select((file, index) => new InputItemDocument
            {
                InputId = $"upload-{index + 1:D4}",
                SourceKind = "upload",
                SourceId = "uploads",
                OriginalPath = file.OriginalName,
                DisplayName = file.OriginalName,
                SizeBytes = file.SizeBytes,
                UploadedPath = file.StoredPath,
            })
            .ToList();

        inputItems.AddRange(uploadItems);
        if (inputItems.Count == 0)
        {
            throw new InvalidOperationException("No input audio files were selected.");
        }

        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var diarizationEnabled = hasToken && settings.HuggingfaceTermsConfirmed;
        return await CreateJobFromInputsAsync(
            outputRoot,
            inputItems,
            command.ReprocessDuplicates,
            hasToken,
            diarizationEnabled,
            settings.ComputeMode,
            settings.ProcessingQuality,
            cancellationToken);
    }

    public async Task<DuplicatePreviewResponse> PreviewDuplicatesAsync(
        DuplicatePreviewRequest request,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var outputRoot = ResolveOutputRoot(settings, request.OutputRootId);
        if (outputRoot is null)
        {
            throw new InvalidOperationException("No enabled output root is configured.");
        }

        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var conversionSignature = ResolveConversionSignature(
            settings,
            hasToken && settings.HuggingfaceTermsConfirmed);
        var duplicates = await FindDuplicateUploadsAsync(
            outputRoot.Path,
            request.UploadedFiles,
            conversionSignature,
            cancellationToken);

        return new DuplicatePreviewResponse
        {
            TotalCount = request.UploadedFiles.Count,
            DuplicateCount = duplicates.Count,
            NewCount = Math.Max(0, request.UploadedFiles.Count - duplicates.Count),
            Duplicates = duplicates,
        };
    }

    public async Task<RunSummary?> GetActiveRunAsync(CancellationToken cancellationToken = default)
    {
        var summaries = await ListRunsAsync(cancellationToken);
        return summaries.FirstOrDefault(static run =>
                   string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
               ?? summaries.FirstOrDefault(static run =>
                   string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
    }

    public async Task<(string JobId, string RunDirectory)> CreateJobFromExistingAsync(
        string jobId,
        bool useCurrentSettings,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var existingRunDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (existingRunDirectory is null)
        {
            throw new InvalidOperationException("The selected job could not be found.");
        }

        var existingStatus = await ReadJsonAsync<JobStatusDocument>(
            Path.Combine(existingRunDirectory, "status.json"),
            cancellationToken);
        if (existingStatus is not null && IsActiveRunState(existingStatus.State))
        {
            throw new InvalidOperationException("Finish the current job before running it again.");
        }

        var existingRequest = await ReadJsonAsync<JobRequestDocument>(
            Path.Combine(existingRunDirectory, "request.json"),
            cancellationToken);
        if (existingRequest is null || existingRequest.InputItems.Count == 0)
        {
            throw new InvalidOperationException("The selected job does not have a reusable request.");
        }

        EnsureRerunnableInputs(existingRequest.InputItems);

        var outputRoot = settings.OutputRoots
            .FirstOrDefault(root => root.Enabled && string.Equals(root.Id, existingRequest.OutputRootId, StringComparison.OrdinalIgnoreCase))
            ?? settings.OutputRoots.FirstOrDefault(static root => root.Enabled);
        if (outputRoot is null)
        {
            throw new InvalidOperationException("No enabled output root is configured.");
        }

        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var diarizationEnabled = useCurrentSettings
            ? hasToken && settings.HuggingfaceTermsConfirmed
            : existingRequest.DiarizationEnabled;
        return await CreateJobFromInputsAsync(
            outputRoot,
            existingRequest.InputItems.Select(CloneInputItem).ToList(),
            reprocessDuplicates: true,
            hasToken,
            diarizationEnabled,
            useCurrentSettings ? settings.ComputeMode : existingRequest.ComputeMode,
            useCurrentSettings ? settings.ProcessingQuality : existingRequest.ProcessingQuality,
            cancellationToken);
    }

    public async Task<JobRequestDocument?> GetJobRequestAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        return await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
    }

    public async Task DeleteRunAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            throw new InvalidOperationException("The selected job could not be found.");
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        if (status is not null &&
            (string.Equals(status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
             string.Equals(status.State, "running", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidOperationException("Active jobs cannot be deleted.");
        }

        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        DeleteUploadDirectories(request);
        Directory.Delete(runDirectory, recursive: true);
    }

    public async Task<int> DeleteCompletedRunsAsync(CancellationToken cancellationToken = default)
    {
        var deleted = 0;
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in EnumerateJobDirectories(root.Path))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (status is null ||
                    string.Equals(status.State, "pending", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(status.State, "running", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                DeleteUploadDirectories(request);
                Directory.Delete(runDirectory, recursive: true);
                deleted++;
            }
        }

        if (Directory.Exists(paths.DownloadsRoot))
        {
            foreach (var archive in Directory.EnumerateFiles(paths.DownloadsRoot, "*.zip", SearchOption.TopDirectoryOnly))
            {
                cancellationToken.ThrowIfCancellationRequested();
                File.Delete(archive);
            }
        }

        return deleted;
    }

    public async Task<int> CleanupExpiredUploadsAsync(TimeSpan retention, CancellationToken cancellationToken = default)
    {
        var deletedCount = 0;
        var now = DateTimeOffset.Now;
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in EnumerateJobDirectories(root.Path))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (status is null)
                {
                    continue;
                }

                if (!string.Equals(status.State, "completed", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(status.State, "failed", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(status.State, "canceled", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var completedAt = ParseTimestamp(status.CompletedAt) ?? ParseTimestamp(status.UpdatedAt);
                if (completedAt is null || now - completedAt.Value < retention)
                {
                    continue;
                }

                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                deletedCount += DeleteUploadDirectories(request);
            }
        }

        return deletedCount;
    }

    public async Task<int> CleanupOrphanedUploadSessionsAsync(TimeSpan retention, CancellationToken cancellationToken = default)
    {
        if (!Directory.Exists(paths.UploadsRoot))
        {
            return 0;
        }

        var referencedDirectories = await GetReferencedUploadDirectoriesAsync(cancellationToken);
        var deletedCount = 0;
        var now = DateTimeOffset.Now;

        foreach (var sessionDirectory in Directory.EnumerateDirectories(paths.UploadsRoot, "session-*", SearchOption.TopDirectoryOnly))
        {
            cancellationToken.ThrowIfCancellationRequested();

            var fullDirectory = Path.GetFullPath(sessionDirectory);
            if (!IsSubdirectoryOf(fullDirectory, Path.GetFullPath(paths.UploadsRoot)))
            {
                continue;
            }

            if (referencedDirectories.Contains(fullDirectory))
            {
                continue;
            }

            var sessionCreatedAt = await ReadUploadSessionCreatedAtAsync(sessionDirectory, cancellationToken)
                ?? new DateTimeOffset(Directory.GetCreationTimeUtc(sessionDirectory));

            if (retention > TimeSpan.Zero && now - sessionCreatedAt < retention)
            {
                continue;
            }

            Directory.Delete(fullDirectory, recursive: true);
            deletedCount += 1;
        }

        return deletedCount;
    }

    public async Task<string?> BuildRunArchiveAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        if (status is null || IsActiveRunState(status.State))
        {
            throw new InvalidOperationException("The job is still in progress.");
        }
        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        var result = await ReadJsonAsync<JobResultDocument>(Path.Combine(runDirectory, "result.json"), cancellationToken);
        var manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken);

        Directory.CreateDirectory(paths.DownloadsRoot);
        var destination = Path.Combine(paths.DownloadsRoot, $"{jobId}.zip");
        if (File.Exists(destination))
        {
            File.Delete(destination);
        }

        var stagingRoot = Path.Combine(paths.DownloadsRoot, $"{jobId}-export-{Guid.NewGuid():N}");
        Directory.CreateDirectory(stagingRoot);

        try
        {
            await Task.Run(
                () => BuildExportPackage(runDirectory, jobId, stagingRoot, request, status, result, manifest),
                cancellationToken);
            await Task.Run(
                () => ZipFile.CreateFromDirectory(stagingRoot, destination, CompressionLevel.Fastest, includeBaseDirectory: false),
                cancellationToken);
        }
        finally
        {
            if (Directory.Exists(stagingRoot))
            {
                Directory.Delete(stagingRoot, recursive: true);
            }
        }

        return destination;
    }

    public async Task<JobStatusDocument?> GetJobStatusAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var path = Path.Combine(runDirectory, "status.json");
        return await ReadJsonAsync<JobStatusDocument>(path, cancellationToken);
    }

    public async Task<RunDetails?> GetRunDetailsAsync(string jobId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var details = new RunDetails
        {
            JobId = jobId,
            RunDirectory = runDirectory,
            Status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken),
            Result = await ReadJsonAsync<JobResultDocument>(Path.Combine(runDirectory, "result.json"), cancellationToken),
            Manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken),
            LogTail = await ReadLogTailAsync(Path.Combine(runDirectory, "logs", "worker.log"), cancellationToken),
        };
        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        details.Request = request;
        details.CurrentSettings = await settingsStore.LoadAsync(cancellationToken);
        details.ElapsedWallSec = DisplayFormatters.CalculateElapsedSeconds(
            details.Status?.StartedAt,
            details.Status?.CompletedAt,
            details.Status?.UpdatedAt);

        details.TimelineItems = ResolveTimelineItems(runDirectory, request, details.Manifest);

        return details;
    }

    public async Task<string?> ReadTimelineAsync(string jobId, string mediaId, CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        var manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken);
        var timelineItem = ResolveTimelineItems(runDirectory, request, manifest)
            .FirstOrDefault(item => string.Equals(item.MediaId, mediaId, StringComparison.OrdinalIgnoreCase));
        if (timelineItem is null || !File.Exists(timelineItem.TimelinePath))
        {
            return null;
        }

        return await File.ReadAllTextAsync(timelineItem.TimelinePath, cancellationToken);
    }

    public async Task<IReadOnlyList<RunSummary>> ListRunsAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var summaries = new List<RunSummary>();
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            var catalogIndex = LoadCatalogIndex(root.Path);

            foreach (var runDirectory in EnumerateJobDirectories(root.Path))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
                if (request is null || status is null)
                {
                    continue;
                }

                var manifest = await ReadJsonAsync<ManifestDocument>(Path.Combine(runDirectory, "manifest.json"), cancellationToken);
                var totalSizeBytes = manifest?.Items.Sum(static item => item.SizeBytes) ?? 0L;
                var totalDurationSec = manifest?.Items.Sum(static item => item.DurationSeconds) ?? 0.0;
                var hasDownloadableArchive = ResolveTimelineItems(runDirectory, request, manifest, catalogIndex).Count > 0;
                var completedCount = status.VideosDone + status.VideosSkipped + status.VideosFailed;

                summaries.Add(new RunSummary
                {
                    JobId = request.JobId,
                    RunDirectory = runDirectory,
                    OutputRootId = request.OutputRootId,
                    State = status.State,
                    CurrentStage = status.CurrentStage,
                    VideosTotal = status.VideosTotal,
                    VideosDone = status.VideosDone,
                    VideosSkipped = status.VideosSkipped,
                    VideosFailed = status.VideosFailed,
                    TotalSizeBytes = totalSizeBytes,
                    TotalDurationSec = totalDurationSec,
                    ElapsedWallSec = DisplayFormatters.CalculateElapsedSeconds(
                        status.StartedAt,
                        status.CompletedAt,
                        status.UpdatedAt),
                    EstimatedRemainingSec = status.EstimatedRemainingSec,
                    ProgressPercent = status.ProgressPercent > 0
                        ? status.ProgressPercent
                        : status.VideosTotal > 0
                            ? Math.Round(completedCount * 100.0 / status.VideosTotal, 1)
                            : 0,
                    HasDownloadableArchive = hasDownloadableArchive,
                    UpdatedAt = status.UpdatedAt,
                    CreatedAt = request.CreatedAt,
                });
            }
        }

        return summaries
            .OrderByDescending(static row => row.CreatedAt)
            .ToList();
    }

    private async Task<(string JobId, string RunDirectory)> CreateJobFromInputsAsync(
        RootOption outputRoot,
        IReadOnlyList<InputItemDocument> inputItems,
        bool reprocessDuplicates,
        bool hasToken,
        bool diarizationEnabled,
        string computeMode,
        string processingQuality,
        CancellationToken cancellationToken)
    {
        var jobId = $"job-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..28];
        var runDirectory = Path.Combine(outputRoot.Path, jobId);
        Directory.CreateDirectory(runDirectory);
        Directory.CreateDirectory(Path.Combine(runDirectory, "media"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "llm"));
        Directory.CreateDirectory(Path.Combine(runDirectory, "logs"));

        var request = new JobRequestDocument
        {
            SchemaVersion = 1,
            JobId = jobId,
            CreatedAt = DateTimeOffset.Now.ToString("O"),
            OutputRootId = outputRoot.Id,
            OutputRootPath = outputRoot.Path,
            Profile = "quality-first",
            ComputeMode = ConversionSignature.NormalizeComputeMode(computeMode),
            ProcessingQuality = ConversionSignature.NormalizeProcessingQuality(processingQuality),
            PipelineVersion = ConversionSignature.PipelineVersion,
            ConversionSignature = ConversionSignature.Build(computeMode, processingQuality, diarizationEnabled),
            TranscriptionBackend = ConversionSignature.TranscriptionBackend,
            TranscriptionModelId = ConversionSignature.ResolveTranscriptionModelId(processingQuality),
            DiarizationEnabled = diarizationEnabled,
            DiarizationModelId = diarizationEnabled ? ConversionSignature.DiarizationModelId : null,
            VadBackend = ConversionSignature.VadBackend,
            VadModelId = ConversionSignature.VadModelId,
            ReprocessDuplicates = reprocessDuplicates,
            TokenEnabled = hasToken,
            InputItems = inputItems.Select(CloneInputItem).ToList(),
        };

        var status = new JobStatusDocument
        {
            JobId = jobId,
            State = "pending",
            CurrentStage = "queued",
            Message = "Queued for worker pickup.",
            VideosTotal = inputItems.Count,
            UpdatedAt = DateTimeOffset.Now.ToString("O"),
        };

        var result = new JobResultDocument
        {
            JobId = jobId,
            State = "pending",
            RunDir = runDirectory,
            OutputRootId = outputRoot.Id,
            OutputRootPath = outputRoot.Path,
        };

        var manifest = new ManifestDocument
        {
            JobId = jobId,
            GeneratedAt = DateTimeOffset.Now.ToString("O"),
            Items = [],
        };

        await WriteJsonAsync(Path.Combine(runDirectory, "request.json"), request, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "status.json"), status, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "result.json"), result, cancellationToken);
        await WriteJsonAsync(Path.Combine(runDirectory, "manifest.json"), manifest, cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "RUN_INFO.md"), "# Run Info\n\nPending worker pickup.\n", cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "TRANSCRIPTION_INFO.md"), "# Transcription Info\n\nPending worker pickup.\n", cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "NOTICE.md"), "# Notice\n\nPending worker pickup.\n", cancellationToken);

        return (jobId, runDirectory);
    }

    private static RootOption? ResolveOutputRoot(AppSettingsDocument settings, string? outputRootId) =>
        settings.OutputRoots
            .FirstOrDefault(root => root.Enabled && string.Equals(root.Id, outputRootId, StringComparison.OrdinalIgnoreCase))
        ?? settings.OutputRoots.FirstOrDefault(static root => root.Enabled);

    private async Task<string?> FindRunDirectoryAsync(string jobId, CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            var candidate = Path.Combine(root.Path, jobId);
            if (Directory.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static IEnumerable<string> EnumerateJobDirectories(string rootPath)
    {
        if (!Directory.Exists(rootPath))
        {
            return [];
        }

        return Directory.EnumerateDirectories(rootPath, "job-*", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateDirectories(rootPath, "run-*", SearchOption.TopDirectoryOnly))
            .Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private async Task<T?> ReadJsonAsync<T>(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return default;
        }

        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<T>(stream, _jsonOptions, cancellationToken);
    }

    private async Task WriteJsonAsync<T>(string path, T value, CancellationToken cancellationToken)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(value, _jsonOptions), cancellationToken);
    }

    private static async Task<List<DuplicatePreviewItem>> FindDuplicateUploadsAsync(
        string outputRootPath,
        IReadOnlyList<UploadedFileReference> uploadedFiles,
        string conversionSignature,
        CancellationToken cancellationToken)
    {
        var duplicates = new List<DuplicatePreviewItem>();
        var catalogIndex = await LoadCatalogIndexAsync(outputRootPath, cancellationToken);

        foreach (var file in uploadedFiles.Where(static file =>
                     !string.IsNullOrWhiteSpace(file.StoredPath) &&
                     File.Exists(file.StoredPath)))
        {
            cancellationToken.ThrowIfCancellationRequested();

            var sha256 = await ComputeSha256Async(file.StoredPath!, cancellationToken);
            if (!catalogIndex.TryGetValue(BuildCatalogKey(sha256, conversionSignature), out var catalogRow))
            {
                continue;
            }

            var reusableTimelinePath = ResolveCatalogTimelinePath(catalogRow);
            if (string.IsNullOrWhiteSpace(reusableTimelinePath))
            {
                continue;
            }

            duplicates.Add(new DuplicatePreviewItem
            {
                ReferenceId = file.ReferenceId,
                DisplayName = file.OriginalName,
                ExistingJobId = catalogRow.JobId,
                ExistingMediaId = catalogRow.MediaId,
                TimelinePath = reusableTimelinePath,
            });
        }

        return duplicates;
    }

    private static async Task<Dictionary<string, CatalogRow>> LoadCatalogIndexAsync(
        string outputRootPath,
        CancellationToken cancellationToken)
    {
        var path = Path.Combine(outputRootPath, ".audio2timeline", "catalog.jsonl");
        var rows = new Dictionary<string, CatalogRow>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(path))
        {
            return rows;
        }

        var lines = await File.ReadAllLinesAsync(path, cancellationToken);
        foreach (var line in lines)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using var document = JsonDocument.Parse(line);
            var row = ParseCatalogRow(document.RootElement);
            if (string.IsNullOrWhiteSpace(row.Sha256))
            {
                continue;
            }

            rows[BuildCatalogKey(row.Sha256, row.ConversionSignature)] = row;
        }

        return rows;
    }

    private static async Task<string> ComputeSha256Async(string path, CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(stream, cancellationToken);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static List<TimelineMediaItem> ResolveTimelineItems(
        string runDirectory,
        JobRequestDocument? request,
        ManifestDocument? manifest,
        Dictionary<string, CatalogRow>? catalogIndex = null)
    {
        catalogIndex ??= LoadCatalogIndex(request?.OutputRootPath);
        var timelineItems = new List<TimelineMediaItem>();
        foreach (var item in manifest?.Items?.Where(static item => !string.IsNullOrWhiteSpace(item.MediaId)) ?? [])
        {
            var mediaId = item.MediaId!;
            var currentTimelinePath = Path.Combine(runDirectory, "media", mediaId, "timeline", "timeline.md");
            var timelinePath = File.Exists(currentTimelinePath) ? currentTimelinePath : null;
            string? referencedJobId = null;
            string? referencedMediaId = null;

            if (timelinePath is null &&
                string.Equals(item.DuplicateStatus, "duplicate_skip", StringComparison.OrdinalIgnoreCase))
            {
                if (catalogIndex.TryGetValue(BuildCatalogKey(item.Sha256, item.ConversionSignature), out var catalogRow) &&
                    !string.IsNullOrWhiteSpace(ResolveCatalogTimelinePath(catalogRow)))
                {
                    timelinePath = ResolveCatalogTimelinePath(catalogRow);
                    referencedJobId = catalogRow.JobId;
                    referencedMediaId = catalogRow.MediaId;
                }
                else if (!string.IsNullOrWhiteSpace(item.DuplicateOf) && File.Exists(item.DuplicateOf))
                {
                    timelinePath = item.DuplicateOf;
                }
            }

            if (string.IsNullOrWhiteSpace(timelinePath) || !File.Exists(timelinePath))
            {
                continue;
            }

            timelineItems.Add(new TimelineMediaItem
            {
                MediaId = mediaId,
                SourcePath = item.OriginalPath,
                TimelinePath = timelinePath,
                Status = item.Status,
                IsReferencedDuplicate = !string.Equals(timelinePath, currentTimelinePath, StringComparison.OrdinalIgnoreCase),
                ReferencedJobId = referencedJobId,
                ReferencedMediaId = referencedMediaId,
            });
        }

        if (timelineItems.Count > 0 || manifest?.Items.Count > 0)
        {
            return timelineItems;
        }

        var mediaRoot = Path.Combine(runDirectory, "media");
        if (!Directory.Exists(mediaRoot))
        {
            return timelineItems;
        }

        foreach (var mediaDirectory in Directory.EnumerateDirectories(mediaRoot).OrderBy(static value => value, StringComparer.OrdinalIgnoreCase))
        {
            var mediaId = Path.GetFileName(mediaDirectory);
            var timelinePath = Path.Combine(mediaDirectory, "timeline", "timeline.md");
            if (!File.Exists(timelinePath))
            {
                continue;
            }

            SourceInfoExportDocument? sourceInfo = null;
            var sourceInfoPath = Path.Combine(mediaDirectory, "source.json");
            if (File.Exists(sourceInfoPath))
            {
                try
                {
                    sourceInfo = JsonSerializer.Deserialize<SourceInfoExportDocument>(File.ReadAllText(sourceInfoPath));
                }
                catch
                {
                    sourceInfo = null;
                }
            }

            timelineItems.Add(new TimelineMediaItem
            {
                MediaId = mediaId,
                SourcePath = sourceInfo?.OriginalPath ?? mediaId,
                TimelinePath = timelinePath,
                Status = "completed",
            });
        }

        return timelineItems;
    }

    private static Dictionary<string, CatalogRow> LoadCatalogIndex(string? outputRootPath)
    {
        var rows = new Dictionary<string, CatalogRow>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(outputRootPath))
        {
            return rows;
        }

        var path = Path.Combine(outputRootPath, ".audio2timeline", "catalog.jsonl");
        if (!File.Exists(path))
        {
            return rows;
        }

        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using var document = JsonDocument.Parse(line);
            var row = ParseCatalogRow(document.RootElement);
            if (string.IsNullOrWhiteSpace(row.Sha256))
            {
                continue;
            }

            rows[BuildCatalogKey(row.Sha256, row.ConversionSignature)] = row;
        }

        return rows;
    }

    private static CatalogRow ParseCatalogRow(JsonElement payload) =>
        new()
        {
            Sha256 = GetOptionalString(payload, "source_hash")
                     ?? GetOptionalString(payload, "sha256")
                     ?? "",
            ConversionSignature = GetOptionalString(payload, "conversion_signature") ?? "",
            JobId = GetOptionalString(payload, "job_id"),
            MediaId = GetOptionalString(payload, "audio_id") ?? GetOptionalString(payload, "media_id"),
            RunDirectory = GetOptionalString(payload, "run_dir"),
            TimelinePath = GetOptionalString(payload, "timeline_path"),
            OriginalPath = GetOptionalString(payload, "original_path"),
        };

    private static string ResolveConversionSignature(AppSettingsDocument settings, bool diarizationEnabled) =>
        ConversionSignature.Build(settings.ComputeMode, settings.ProcessingQuality, diarizationEnabled);

    private static string BuildCatalogKey(string? sourceHash, string? conversionSignature) =>
        $"{(sourceHash ?? "").Trim().ToLowerInvariant()}::{(conversionSignature ?? "").Trim().ToLowerInvariant()}";

    private static string? ResolveCatalogTimelinePath(CatalogRow row)
    {
        if (!string.IsNullOrWhiteSpace(row.TimelinePath) && File.Exists(row.TimelinePath))
        {
            return row.TimelinePath;
        }

        if (!string.IsNullOrWhiteSpace(row.RunDirectory) && !string.IsNullOrWhiteSpace(row.MediaId))
        {
            var candidate = Path.Combine(row.RunDirectory, "media", row.MediaId, "timeline", "timeline.md");
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static string? GetOptionalString(JsonElement payload, string propertyName)
    {
        if (!payload.TryGetProperty(propertyName, out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : value.ToString();
    }

    private static async Task<string> ReadLogTailAsync(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return "";
        }

        var text = await File.ReadAllTextAsync(path, cancellationToken);
        var lines = text.Split('\n', StringSplitOptions.None);
        return string.Join(Environment.NewLine, lines.TakeLast(80));
    }

    private static string MakeSafeFileName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(value.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
        return string.IsNullOrWhiteSpace(sanitized) ? $"upload-{Guid.NewGuid():N}.bin" : sanitized;
    }

    private int DeleteUploadDirectories(JobRequestDocument? request)
    {
        if (request is null)
        {
            return 0;
        }

        var uploadsRoot = Path.GetFullPath(paths.UploadsRoot);
        var deletedCount = 0;
        var directories = request.InputItems
            .Where(static item => string.Equals(item.SourceKind, "upload", StringComparison.OrdinalIgnoreCase))
            .Select(static item => item.UploadedPath)
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .Select(static path => Path.GetDirectoryName(path!))
            .Where(static path => !string.IsNullOrWhiteSpace(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        foreach (var directory in directories)
        {
            if (directory is null || !Directory.Exists(directory))
            {
                continue;
            }

            var fullDirectory = Path.GetFullPath(directory);
            if (!IsSubdirectoryOf(fullDirectory, uploadsRoot))
            {
                continue;
            }

            Directory.Delete(directory, recursive: true);
            deletedCount += 1;
        }

        return deletedCount;
    }

    private async Task<HashSet<string>> GetReferencedUploadDirectoriesAsync(CancellationToken cancellationToken)
    {
        var referenced = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var settings = await settingsStore.LoadAsync(cancellationToken);

        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            foreach (var runDirectory in EnumerateJobDirectories(root.Path))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
                if (request is null)
                {
                    continue;
                }

                foreach (var directory in request.InputItems
                    .Where(static item => string.Equals(item.SourceKind, "upload", StringComparison.OrdinalIgnoreCase))
                    .Select(static item => item.UploadedPath)
                    .Where(static path => !string.IsNullOrWhiteSpace(path))
                    .Select(static path => Path.GetDirectoryName(path!))
                    .Where(static path => !string.IsNullOrWhiteSpace(path)))
                {
                    referenced.Add(Path.GetFullPath(directory!));
                }
            }
        }

        return referenced;
    }

    private async Task<DateTimeOffset?> ReadUploadSessionCreatedAtAsync(string sessionDirectory, CancellationToken cancellationToken)
    {
        var path = Path.Combine(sessionDirectory, "session.json");
        var session = await ReadJsonAsync<UploadSessionDocument>(path, cancellationToken);
        return ParseTimestamp(session?.CreatedAt);
    }

    private static DateTimeOffset? ParseTimestamp(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        return DateTimeOffset.TryParse(value, out var parsed) ? parsed : null;
    }

    private static InputItemDocument CloneInputItem(InputItemDocument source) =>
        new()
        {
            InputId = source.InputId,
            SourceKind = source.SourceKind,
            SourceId = source.SourceId,
            OriginalPath = source.OriginalPath,
            DisplayName = source.DisplayName,
            SizeBytes = source.SizeBytes,
            UploadedPath = source.UploadedPath,
        };

    private static void EnsureRerunnableInputs(IReadOnlyList<InputItemDocument> inputItems)
    {
        var missing = inputItems
            .Select(item => new
            {
                item.DisplayName,
                ResolvedPath = ResolveRerunInputPath(item),
            })
            .Where(static row => !string.IsNullOrWhiteSpace(row.ResolvedPath) && !File.Exists(row.ResolvedPath))
            .Select(static row => row.DisplayName)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(3)
            .ToList();

        if (missing.Count == 0)
        {
            return;
        }

        throw new InvalidOperationException(
            $"Some source files are no longer available for rerun: {string.Join(", ", missing)}");
    }

    private static string? ResolveRerunInputPath(InputItemDocument item)
    {
        if (!string.IsNullOrWhiteSpace(item.UploadedPath))
        {
            return item.UploadedPath;
        }

        return Path.IsPathRooted(item.OriginalPath) ? item.OriginalPath : null;
    }

    private static bool IsSubdirectoryOf(string candidate, string root)
    {
        if (string.Equals(candidate, root, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var normalizedRoot = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        return candidate.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsActiveRunState(string? state) =>
        string.Equals(state, "pending", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(state, "running", StringComparison.OrdinalIgnoreCase);

    private static void BuildExportPackage(
        string runDirectory,
        string jobId,
        string exportRoot,
        JobRequestDocument? request,
        JobStatusDocument? status,
        JobResultDocument? result,
        ManifestDocument? manifest)
    {
        Directory.CreateDirectory(exportRoot);
        var timelinesRoot = Path.Combine(exportRoot, "timelines");
        var transcriptsRoot = Path.Combine(exportRoot, "raw-transcripts");
        var speakerSummariesRoot = Path.Combine(exportRoot, "speaker-summaries");
        var featureSummariesRoot = Path.Combine(exportRoot, "audio-feature-summaries");
        Directory.CreateDirectory(timelinesRoot);
        Directory.CreateDirectory(transcriptsRoot);
        Directory.CreateDirectory(speakerSummariesRoot);
        Directory.CreateDirectory(featureSummariesRoot);
        var timelineRows = ResolveExportTimelineRows(runDirectory, request, manifest);

        timelineRows = timelineRows
            .OrderBy(static row => row.Label, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static row => row.AudioId, StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (timelineRows.Count == 0)
        {
            throw new InvalidOperationException("No completed timelines are available to download for this job.");
        }

        var transcriptionInfoPath = Path.Combine(runDirectory, "TRANSCRIPTION_INFO.md");
        if (File.Exists(transcriptionInfoPath))
        {
            File.Copy(transcriptionInfoPath, Path.Combine(exportRoot, "TRANSCRIPTION_INFO.md"), overwrite: true);
        }

        var hasFailureArtifacts = WriteFailureArtifacts(runDirectory, exportRoot, jobId, status, result, manifest, timelineRows.Count);

        var packageInfo = string.Join(
            Environment.NewLine,
            [
                "# README",
                "",
                "This ZIP contains timeline markdown files that are ready to review or upload to an LLM such as ChatGPT.",
                "",
                $"- Job ID: `{jobId}`",
                "- Main folder: `timelines/`",
                "- Each markdown file is one audio timeline.",
                "- `raw-transcripts/` contains per-item raw transcript markdown.",
                "- `speaker-summaries/` contains diarization-oriented speaker summaries when available.",
                "- `audio-feature-summaries/` contains pause/loudness/pitch/rate summaries.",
                "- `TRANSCRIPTION_INFO.md` explains which processing and models were used.",
                hasFailureArtifacts ? "- `FAILURE_REPORT.md` summarizes any failed items or warnings from the job." : "",
                hasFailureArtifacts ? "- `logs/worker.log` is included for troubleshooting." : "",
                "",
            ]);
        File.WriteAllText(Path.Combine(exportRoot, "README.md"), packageInfo);

        var usedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in timelineRows)
        {
            var fileName = EnsureUniqueExportFileName($"{row.Label}.md", usedNames);
            File.Copy(row.TimelinePath, Path.Combine(timelinesRoot, fileName), overwrite: true);
            if (!string.IsNullOrWhiteSpace(row.RawTranscriptPath) && File.Exists(row.RawTranscriptPath))
            {
                File.Copy(row.RawTranscriptPath, Path.Combine(transcriptsRoot, fileName), overwrite: true);
            }
            if (!string.IsNullOrWhiteSpace(row.SpeakerSummaryPath) && File.Exists(row.SpeakerSummaryPath))
            {
                File.Copy(row.SpeakerSummaryPath, Path.Combine(speakerSummariesRoot, fileName), overwrite: true);
            }
            if (!string.IsNullOrWhiteSpace(row.AudioFeatureSummaryPath) && File.Exists(row.AudioFeatureSummaryPath))
            {
                File.Copy(row.AudioFeatureSummaryPath, Path.Combine(featureSummariesRoot, fileName), overwrite: true);
            }
        }
    }

    private static List<(string AudioId, string Label, string TimelinePath, string SourcePath, string? RawTranscriptPath, string? SpeakerSummaryPath, string? AudioFeatureSummaryPath)> ResolveExportTimelineRows(
        string runDirectory,
        JobRequestDocument? request,
        ManifestDocument? manifest)
    {
        var resolvedItems = ResolveTimelineItems(runDirectory, request, manifest);
        if (resolvedItems.Count == 0)
        {
            return [];
        }

        var timelineRows = new List<(string AudioId, string Label, string TimelinePath, string SourcePath, string? RawTranscriptPath, string? SpeakerSummaryPath, string? AudioFeatureSummaryPath)>();
        foreach (var item in resolvedItems)
        {
            SourceInfoExportDocument? sourceInfo = null;
            var sourceInfoPath = ResolveSourceInfoPath(item.TimelinePath);
            if (sourceInfoPath is not null && File.Exists(sourceInfoPath))
            {
                try
                {
                    sourceInfo = JsonSerializer.Deserialize<SourceInfoExportDocument>(File.ReadAllText(sourceInfoPath));
                }
                catch
                {
                    sourceInfo = null;
                }
            }

            timelineRows.Add((
                item.MediaId,
                BestExportLabel(item.MediaId, sourceInfo, item.SourcePath),
                item.TimelinePath,
                item.SourcePath,
                ResolveSiblingArtifactPath(item.TimelinePath, "transcript/raw.md"),
                ResolveSiblingArtifactPath(item.TimelinePath, "analysis/speaker_summary.md"),
                ResolveSiblingArtifactPath(item.TimelinePath, "analysis/audio_features.md")));
        }

        return timelineRows;
    }

    private static bool WriteFailureArtifacts(
        string runDirectory,
        string exportRoot,
        string jobId,
        JobStatusDocument? status,
        JobResultDocument? result,
        ManifestDocument? manifest,
        int exportedTimelineCount)
    {
        var failedItems = manifest?.Items
            .Where(static item => string.Equals(item.Status, "failed", StringComparison.OrdinalIgnoreCase))
            .OrderBy(static item => item.OriginalPath, StringComparer.OrdinalIgnoreCase)
            .ToList() ?? [];

        var warnings = new HashSet<string>(StringComparer.Ordinal);
        foreach (var warning in status?.Warnings ?? [])
        {
            if (!string.IsNullOrWhiteSpace(warning))
            {
                warnings.Add(warning.Trim());
            }
        }

        foreach (var warning in result?.Warnings ?? [])
        {
            if (!string.IsNullOrWhiteSpace(warning))
            {
                warnings.Add(warning.Trim());
            }
        }

        var hasFailures =
            failedItems.Count > 0 ||
            (status?.VideosFailed ?? 0) > 0 ||
            (result?.ErrorCount ?? 0) > 0 ||
            string.Equals(status?.State, "failed", StringComparison.OrdinalIgnoreCase);

        if (!hasFailures && warnings.Count == 0)
        {
            return false;
        }

        var lines = new List<string>
        {
            "# Failure Report",
            "",
            "This job produced downloadable timelines, but some items did not complete successfully.",
            "",
            $"- Job ID: `{jobId}`",
            $"- Final state: `{status?.State ?? result?.State ?? "unknown"}`",
            $"- Exported timelines: `{exportedTimelineCount}`",
            $"- Completed items: `{status?.VideosDone ?? result?.ProcessedCount ?? 0}`",
            $"- Failed items: `{status?.VideosFailed ?? result?.ErrorCount ?? failedItems.Count}`",
            $"- Skipped items: `{status?.VideosSkipped ?? result?.SkippedCount ?? 0}`",
        };

        if (!string.IsNullOrWhiteSpace(status?.Message))
        {
            lines.Add($"- Final message: {status.Message}");
        }

        if (failedItems.Count > 0)
        {
            lines.Add("");
            lines.Add("## Failed Items");
            lines.Add("");
            foreach (var item in failedItems)
            {
                var label = string.IsNullOrWhiteSpace(item.OriginalPath) ? item.FileName : item.OriginalPath;
                if (!string.IsNullOrWhiteSpace(item.MediaId))
                {
                    lines.Add($"- `{label}` (`{item.MediaId}`)");
                }
                else
                {
                    lines.Add($"- `{label}`");
                }
            }
        }

        if (warnings.Count > 0)
        {
            lines.Add("");
            lines.Add("## Warnings");
            lines.Add("");
            foreach (var warning in warnings)
            {
                lines.Add($"- {warning}");
            }
        }

        var workerLogPath = Path.Combine(runDirectory, "logs", "worker.log");
        if (File.Exists(workerLogPath))
        {
            var logsRoot = Path.Combine(exportRoot, "logs");
            Directory.CreateDirectory(logsRoot);
            File.Copy(workerLogPath, Path.Combine(logsRoot, "worker.log"), overwrite: true);
            lines.Add("");
            lines.Add("## Worker Log");
            lines.Add("");
            lines.Add("- See `logs/worker.log` for the full worker log captured for this job.");
        }

        File.WriteAllText(Path.Combine(exportRoot, "FAILURE_REPORT.md"), string.Join(Environment.NewLine, lines) + Environment.NewLine);
        return true;
    }

    private static string BestExportLabel(string mediaId, SourceInfoExportDocument? sourceInfo, string? fallbackOriginalPath = null)
    {
        var candidates = new[]
        {
            sourceInfo?.CapturedAt,
            sourceInfo?.DisplayName,
            sourceInfo?.OriginalPath,
            fallbackOriginalPath,
            mediaId,
        };

        foreach (var candidate in candidates)
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            if (TryParseBestEffortDateTime(candidate, out var parsed))
            {
                return parsed.ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
            }
        }

        if (!string.IsNullOrWhiteSpace(sourceInfo?.ResolvedPath) && File.Exists(sourceInfo.ResolvedPath))
        {
            return File.GetLastWriteTime(sourceInfo.ResolvedPath).ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
        }

        return MakeSafeFileName(mediaId);
    }

    private static string? ResolveSourceInfoPath(string timelinePath)
    {
        var timelineDirectory = Path.GetDirectoryName(timelinePath);
        var mediaDirectory = timelineDirectory is null ? null : Path.GetDirectoryName(timelineDirectory);
        return string.IsNullOrWhiteSpace(mediaDirectory)
            ? null
            : Path.Combine(mediaDirectory, "source.json");
    }

    private static string? ResolveSiblingArtifactPath(string timelinePath, string relativePath)
    {
        var timelineDirectory = Path.GetDirectoryName(timelinePath);
        var mediaDirectory = timelineDirectory is null ? null : Path.GetDirectoryName(timelineDirectory);
        if (string.IsNullOrWhiteSpace(mediaDirectory))
        {
            return null;
        }

        var candidate = Path.Combine(mediaDirectory, relativePath);
        return File.Exists(candidate) ? candidate : null;
    }

    private static string EnsureUniqueExportFileName(string fileName, HashSet<string> usedNames)
    {
        var baseName = Path.GetFileNameWithoutExtension(fileName);
        var extension = Path.GetExtension(fileName);
        var candidate = fileName;
        var suffix = 2;

        while (!usedNames.Add(candidate))
        {
            candidate = $"{baseName}-{suffix}{extension}";
            suffix++;
        }

        return candidate;
    }

    private static bool TryParseBestEffortDateTime(string value, out DateTime parsed)
    {
        if (DateTime.TryParse(value, out parsed))
        {
            return true;
        }

        foreach (var pattern in new[]
                 {
                     "yyyy-MM-dd HH-mm-ss",
                     "yyyy-MM-dd HH:mm:ss",
                     "yyyyMMdd-HHmmss",
                     "yyyyMMddHHmmss",
                     "yyyy-MM-ddTHH:mm:ss",
                     "yyyy-MM-ddTHH:mm:ssK",
                 })
        {
            if (DateTime.TryParseExact(
                value,
                pattern,
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AllowWhiteSpaces | System.Globalization.DateTimeStyles.AssumeLocal,
                out parsed))
            {
                return true;
            }
        }

        parsed = default;
        return false;
    }

    private sealed class SourceInfoExportDocument
    {
        public string? OriginalPath { get; set; }

        public string? ResolvedPath { get; set; }

        public string? DisplayName { get; set; }

        public string? CapturedAt { get; set; }
    }

    private sealed class CatalogRow
    {
        public string Sha256 { get; set; } = "";

        public string ConversionSignature { get; set; } = "";

        public string? JobId { get; set; }

        public string? MediaId { get; set; }

        public string? RunDirectory { get; set; }

        public string? TimelinePath { get; set; }

        public string? OriginalPath { get; set; }
    }
}
