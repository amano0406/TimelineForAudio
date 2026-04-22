using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using TimelineForAudio.Web.Infrastructure;
using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class RunStore(AppPaths paths, SettingsStore settingsStore, ScanService scanService)
{
    private const string DeleteRequestedMarkerFileName = ".delete-requested";
    private const string JobLockFileName = ".job.lock";

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
        var diarizationEnabled = RuntimeProfile.ResolveDiarizationDefault(
            settings.ComputeMode,
            hasToken && settings.HuggingfaceTermsConfirmed);
        return await CreateJobFromInputsAsync(
            outputRoot,
            inputItems,
            command.ReprocessDuplicates,
            hasToken,
            diarizationEnabled,
            settings.ComputeMode,
            settings.UiLanguage,
            command.SupplementalContextText,
            cancellationToken);
    }

    public async Task<RunSummary?> GetActiveRunAsync(CancellationToken cancellationToken = default)
    {
        var summaries = await ListRunsAsync(cancellationToken);
        return summaries.FirstOrDefault(static run =>
                   string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
               ?? summaries.FirstOrDefault(static run =>
                   string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
    }

    public async Task<bool> HasAnyRunsAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (EnumerateJobDirectories(root.Path).Any())
            {
                return true;
            }
        }

        return false;
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
            ? RuntimeProfile.ResolveDiarizationDefault(
                settings.ComputeMode,
                hasToken && settings.HuggingfaceTermsConfirmed)
            : existingRequest.DiarizationEnabled;
        return await CreateJobFromInputsAsync(
            outputRoot,
            existingRequest.InputItems.Select(CloneInputItem).ToList(),
            reprocessDuplicates: true,
            hasToken,
            diarizationEnabled,
            useCurrentSettings ? settings.ComputeMode : existingRequest.ComputeMode,
            useCurrentSettings ? settings.UiLanguage : existingRequest.LanguageHint,
            existingRequest.SupplementalContextText,
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
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken, includeDeleteRequested: true);
        if (runDirectory is null)
        {
            throw new InvalidOperationException("The selected job could not be found.");
        }

        await DeleteOrRequestRunDeletionAsync(runDirectory, cancellationToken);
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

            foreach (var runDirectory in EnumerateJobDirectories(root.Path, includeDeleteRequested: true))
            {
                cancellationToken.ThrowIfCancellationRequested();
                await DeleteOrRequestRunDeletionAsync(runDirectory, cancellationToken);
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

    public async Task<string?> BuildRunArchiveAsync(string jobId, string? artifactKind = null, CancellationToken cancellationToken = default)
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
        var normalizedArtifactKind = NormalizeExportArtifactKind(artifactKind);

        Directory.CreateDirectory(paths.DownloadsRoot);
        var destination = Path.Combine(paths.DownloadsRoot, $"{jobId}-{normalizedArtifactKind}.zip");
        if (File.Exists(destination))
        {
            File.Delete(destination);
        }

        var stagingRoot = Path.Combine(paths.DownloadsRoot, $"{jobId}-{normalizedArtifactKind}-export-{Guid.NewGuid():N}");
        Directory.CreateDirectory(stagingRoot);

        try
        {
            await Task.Run(
                () => BuildExportPackage(runDirectory, jobId, stagingRoot, normalizedArtifactKind, request, status, result, manifest),
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
            ConversionInfoText = await ReadArtifactTextAsync(FindConversionInfoPath(runDirectory), cancellationToken) ?? "",
            LogTail = await ReadLogTailAsync(Path.Combine(runDirectory, "logs", "worker.log"), cancellationToken),
        };
        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        details.Request = request;
        details.CurrentSettings = await settingsStore.LoadAsync(cancellationToken);
        details.ElapsedWallSec = DisplayFormatters.CalculateElapsedSeconds(
            details.Status?.StartedAt,
            details.Status?.CompletedAt,
            details.Status?.UpdatedAt);

        details.ArtifactItems = ResolveArtifactItems(runDirectory, request, details.Manifest, status: details.Status);

        return details;
    }

    public async Task<string?> ReadArtifactAsync(
        string jobId,
        string mediaId,
        string? artifactKind,
        CancellationToken cancellationToken = default)
    {
        var mediaItem = await GetMediaArtifactItemAsync(jobId, mediaId, cancellationToken);
        var artifactPath = ResolveSelectedArtifactPath(mediaItem, artifactKind);
        if (string.IsNullOrWhiteSpace(artifactPath) || !File.Exists(artifactPath))
        {
            return null;
        }

        return await File.ReadAllTextAsync(artifactPath, cancellationToken);
    }

    public async Task<MediaArtifactItem?> GetMediaArtifactItemAsync(
        string jobId,
        string mediaId,
        CancellationToken cancellationToken = default)
    {
        var runDirectory = await FindRunDirectoryAsync(jobId, cancellationToken);
        if (runDirectory is null)
        {
            return null;
        }

        var request = await ReadJsonAsync<JobRequestDocument>(
            Path.Combine(runDirectory, "request.json"),
            cancellationToken);
        var manifest = await ReadJsonAsync<ManifestDocument>(
            Path.Combine(runDirectory, "manifest.json"),
            cancellationToken);
        return ResolveArtifactItems(runDirectory, request, manifest)
            .FirstOrDefault(item => string.Equals(item.MediaId, mediaId, StringComparison.OrdinalIgnoreCase));
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
                var resolvedItems = ResolveArtifactItems(runDirectory, request, manifest, catalogIndex);
                var hasReadableTextArchive = resolvedItems.Any(static item => !string.IsNullOrWhiteSpace(item.ReadableTextPath));
                var hasIpaArchive = resolvedItems.Any(static item => !string.IsNullOrWhiteSpace(item.IpaPath));
                var hasDownloadableArchive = hasReadableTextArchive || hasIpaArchive;
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
                    HasIpaArchive = hasIpaArchive,
                    HasReadableTextArchive = hasReadableTextArchive,
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
        string? languageHint,
        string? supplementalContextText,
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
            PipelineVersion = ConversionSignature.PipelineVersion,
            ConversionSignature = ConversionSignature.Build(
                computeMode,
                diarizationEnabled,
                languageHint,
                supplementalContextText,
                contextBuilderVersion: ConversionSignature.ContextBuilderVersion),
            TranscriptionBackend = ConversionSignature.TranscriptionBackend,
            TranscriptionModelId = ConversionSignature.ResolveTranscriptionModelId(),
            LanguageHint = ConversionSignature.NormalizeLanguageHint(languageHint),
            ReconstructionBackend = ConversionSignature.ResolveReconstructionBackend(languageHint, computeMode),
            ReconstructionModelId = ConversionSignature.ResolveReconstructionModelId(languageHint, computeMode),
            ReconstructionPromptVersion = ConversionSignature.ResolveReconstructionPromptVersion(languageHint, computeMode),
            SupplementalContextText = string.IsNullOrWhiteSpace(supplementalContextText)
                ? null
                : supplementalContextText.Replace("\r\n", "\n").Replace('\r', '\n').Trim(),
            ContextBuilderVersion = ConversionSignature.ContextBuilderVersion,
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
        const string pendingConversionInfo = "# Conversion Info\n\nPending worker pickup.\n";
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "CONVERSION_INFO.md"), pendingConversionInfo, cancellationToken);
        await File.WriteAllTextAsync(Path.Combine(runDirectory, "NOTICE.md"), "# Notice\n\nPending worker pickup.\n", cancellationToken);

        return (jobId, runDirectory);
    }

    private static RootOption? ResolveOutputRoot(AppSettingsDocument settings, string? outputRootId) =>
        settings.OutputRoots
            .FirstOrDefault(root => root.Enabled && string.Equals(root.Id, outputRootId, StringComparison.OrdinalIgnoreCase))
        ?? settings.OutputRoots.FirstOrDefault(static root => root.Enabled);

    private async Task<string?> FindRunDirectoryAsync(
        string jobId,
        CancellationToken cancellationToken,
        bool includeDeleteRequested = false)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        foreach (var root in settings.OutputRoots.Where(static root => root.Enabled))
        {
            var candidate = Path.Combine(root.Path, jobId);
            if (Directory.Exists(candidate) && (includeDeleteRequested || !IsDeleteRequested(candidate)))
            {
                return candidate;
            }
        }

        return null;
    }

    private static IEnumerable<string> EnumerateJobDirectories(
        string rootPath,
        bool includeDeleteRequested = false)
    {
        if (!Directory.Exists(rootPath))
        {
            return [];
        }

        return Directory.EnumerateDirectories(rootPath, "job-*", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateDirectories(rootPath, "run-*", SearchOption.TopDirectoryOnly))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(directory => includeDeleteRequested || !IsDeleteRequested(directory));
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

    private static async Task<string?> ReadArtifactTextAsync(string? path, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return null;
        }

        return await File.ReadAllTextAsync(path, cancellationToken);
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

    private static async Task<string> ComputeSha256Async(string path, CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(stream, cancellationToken);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static List<MediaArtifactItem> ResolveArtifactItems(
        string runDirectory,
        JobRequestDocument? request,
        ManifestDocument? manifest,
        Dictionary<string, CatalogRow>? catalogIndex = null,
        JobStatusDocument? status = null)
    {
        catalogIndex ??= LoadCatalogIndex(request?.OutputRootPath);
        var artifactItems = new List<MediaArtifactItem>();
        foreach (var item in manifest?.Items?.Where(static item => !string.IsNullOrWhiteSpace(item.MediaId)) ?? [])
        {
            var mediaId = item.MediaId!;
            var currentReadableTextPath = Path.Combine(runDirectory, "media", mediaId, "readable-text", "Readable Text.md");
            var currentIpaPath = Path.Combine(runDirectory, "media", mediaId, "ipa", "IPA.md");
            var readableTextPath = File.Exists(currentReadableTextPath) ? currentReadableTextPath : null;
            var ipaPath = File.Exists(currentIpaPath) ? currentIpaPath : null;
            var primaryArtifactPath = readableTextPath ?? ipaPath;
            var primaryArtifactKind = ResolvePrimaryArtifactKind(readableTextPath, ipaPath, primaryArtifactPath);
            var anchorArtifactPath = primaryArtifactPath ?? readableTextPath ?? ipaPath;
            string? referencedJobId = null;
            string? referencedMediaId = null;

            if (primaryArtifactPath is null &&
                string.Equals(item.DuplicateStatus, "duplicate_skip", StringComparison.OrdinalIgnoreCase))
            {
                if (catalogIndex.TryGetValue(BuildCatalogKey(item.Sha256, item.ConversionSignature), out var catalogRow))
                {
                    readableTextPath = ResolveCatalogSiblingArtifactPath(catalogRow, "readable-text", "Readable Text.md");
                    ipaPath = ResolveCatalogSiblingArtifactPath(catalogRow, "ipa", "IPA.md");
                    primaryArtifactPath = readableTextPath ?? ipaPath;
                    if (!string.IsNullOrWhiteSpace(primaryArtifactPath))
                    {
                        referencedJobId = catalogRow.JobId;
                        referencedMediaId = catalogRow.MediaId;
                    }
                }
                else if (!string.IsNullOrWhiteSpace(item.DuplicateOf) && File.Exists(item.DuplicateOf))
                {
                    primaryArtifactPath = item.DuplicateOf;
                }
            }

            primaryArtifactKind = ResolvePrimaryArtifactKind(readableTextPath, ipaPath, primaryArtifactPath);
            anchorArtifactPath = primaryArtifactPath ?? readableTextPath ?? ipaPath;
            var speakerMetadata = ResolveSpeakerMetadata(anchorArtifactPath);
            var isReferencedDuplicate =
                !string.IsNullOrWhiteSpace(primaryArtifactPath) &&
                !string.Equals(primaryArtifactPath, currentReadableTextPath, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(primaryArtifactPath, currentIpaPath, StringComparison.OrdinalIgnoreCase);

            artifactItems.Add(new MediaArtifactItem
            {
                MediaId = mediaId,
                FileName = !string.IsNullOrWhiteSpace(item.FileName)
                    ? item.FileName
                    : Path.GetFileName(item.OriginalPath),
                SourcePath = item.OriginalPath,
                PrimaryArtifactPath = primaryArtifactPath,
                PrimaryArtifactKind = primaryArtifactKind,
                IpaPath = ipaPath,
                ReadableTextPath = readableTextPath,
                Status = ResolveMediaItemStatus(item, status),
                SpeakerCount = item.SpeakerCount ?? speakerMetadata?.SpeakerCount,
                SpeakerCountStatus = item.SpeakerCountStatus ?? speakerMetadata?.SpeakerCountStatus,
                SpeakerCountNote = item.SpeakerCountNote ?? speakerMetadata?.SpeakerCountNote,
                IsCacheReused =
                    string.Equals(item.DuplicateStatus, "duplicate_skip", StringComparison.OrdinalIgnoreCase) ||
                    isReferencedDuplicate,
                IsReferencedDuplicate = isReferencedDuplicate,
                ReferencedJobId = referencedJobId,
                ReferencedMediaId = referencedMediaId,
            });
        }

        if (artifactItems.Count > 0 || manifest?.Items.Count > 0)
        {
            return artifactItems;
        }

        var mediaRoot = Path.Combine(runDirectory, "media");
        if (!Directory.Exists(mediaRoot))
        {
            return artifactItems;
        }

        foreach (var mediaDirectory in Directory.EnumerateDirectories(mediaRoot).OrderBy(static value => value, StringComparer.OrdinalIgnoreCase))
        {
            var mediaId = Path.GetFileName(mediaDirectory);
            var readableTextPath = Path.Combine(mediaDirectory, "readable-text", "Readable Text.md");
            var ipaPath = Path.Combine(mediaDirectory, "ipa", "IPA.md");
            var primaryArtifactPath = File.Exists(readableTextPath)
                ? readableTextPath
                : File.Exists(ipaPath)
                    ? ipaPath
                    : null;
            if (string.IsNullOrWhiteSpace(primaryArtifactPath))
            {
                continue;
            }

            var speakerMetadata = ResolveSpeakerMetadata(primaryArtifactPath);

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

            artifactItems.Add(new MediaArtifactItem
            {
                MediaId = mediaId,
                FileName = Path.GetFileName(sourceInfo?.OriginalPath ?? mediaId),
                SourcePath = sourceInfo?.OriginalPath ?? mediaId,
                PrimaryArtifactPath = primaryArtifactPath,
                PrimaryArtifactKind = ResolvePrimaryArtifactKind(
                    File.Exists(readableTextPath) ? readableTextPath : null,
                    File.Exists(ipaPath) ? ipaPath : null,
                    primaryArtifactPath),
                IpaPath = File.Exists(ipaPath) ? ipaPath : null,
                ReadableTextPath = File.Exists(readableTextPath) ? readableTextPath : null,
                SpeakerCount = speakerMetadata?.SpeakerCount,
                SpeakerCountStatus = speakerMetadata?.SpeakerCountStatus,
                SpeakerCountNote = speakerMetadata?.SpeakerCountNote,
                Status = "completed",
            });
        }

        return artifactItems;
    }

    private static string ResolvePrimaryArtifactKind(
        string? readableTextPath,
        string? ipaPath,
        string? primaryArtifactPath)
    {
        if (!string.IsNullOrWhiteSpace(readableTextPath))
        {
            return "readable_text";
        }

        if (!string.IsNullOrWhiteSpace(ipaPath))
        {
            return "ipa";
        }

        return InferArtifactKind(primaryArtifactPath);
    }

    private static string ResolveMediaItemStatus(ManifestItemDocument item, JobStatusDocument? status)
    {
        if (string.Equals(item.Status, "skipped_duplicate", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(item.DuplicateStatus, "duplicate_skip", StringComparison.OrdinalIgnoreCase))
        {
            return "skipped_duplicate";
        }

        if (status is null || !IsActiveRunState(status.State))
        {
            return string.IsNullOrWhiteSpace(item.Status) ? "pending" : item.Status;
        }

        var currentMedia = status.CurrentMedia?.Trim();
        var fileName = !string.IsNullOrWhiteSpace(item.FileName)
            ? item.FileName
            : Path.GetFileName(item.OriginalPath);
        if (!string.IsNullOrWhiteSpace(currentMedia) &&
            !string.IsNullOrWhiteSpace(fileName) &&
            string.Equals(currentMedia, fileName, StringComparison.OrdinalIgnoreCase))
        {
            return string.IsNullOrWhiteSpace(status.CurrentStage) ? "processing" : status.CurrentStage;
        }

        return string.IsNullOrWhiteSpace(item.Status) ? "pending" : item.Status;
    }

    private static Dictionary<string, CatalogRow> LoadCatalogIndex(string? outputRootPath)
    {
        var rows = new Dictionary<string, CatalogRow>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(outputRootPath))
        {
            return rows;
        }

        var path = Path.Combine(outputRootPath, ".timeline-for-audio", "catalog.jsonl");
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
            ConversionSignature = GetOptionalString(payload, "generation_signature")
                                  ?? GetOptionalString(payload, "conversion_signature")
                                  ?? "",
            JobId = GetOptionalString(payload, "job_id"),
            MediaId = GetOptionalString(payload, "audio_id") ?? GetOptionalString(payload, "media_id"),
            RunDirectory = GetOptionalString(payload, "run_dir"),
            OriginalPath = GetOptionalString(payload, "original_path"),
        };

    private static string ResolveConversionSignature(
        AppSettingsDocument settings,
        bool diarizationEnabled,
        string? languageHint,
        string? supplementalContextText) =>
        ConversionSignature.Build(
            settings.ComputeMode,
            diarizationEnabled,
            languageHint,
            supplementalContextText,
            contextBuilderVersion: ConversionSignature.ContextBuilderVersion);

    private static string BuildCatalogKey(string? sourceHash, string? conversionSignature) =>
        $"{(sourceHash ?? "").Trim().ToLowerInvariant()}::{(conversionSignature ?? "").Trim().ToLowerInvariant()}";

    private static string? FindConversionInfoPath(string runDirectory)
    {
        var candidates = new[]
        {
            Path.Combine(runDirectory, "CONVERSION_INFO.md"),
            Path.Combine(runDirectory, "TRANSCRIPTION_INFO.md"),
        };

        return candidates.FirstOrDefault(File.Exists);
    }

    private static string? ResolveCatalogSiblingArtifactPath(CatalogRow row, string folderName, string fileName)
    {
        if (string.IsNullOrWhiteSpace(row.RunDirectory) || string.IsNullOrWhiteSpace(row.MediaId))
        {
            return null;
        }

        var candidate = Path.Combine(row.RunDirectory, "media", row.MediaId, folderName, fileName);
        return File.Exists(candidate) ? candidate : null;
    }

    private static string? ResolveSelectedArtifactPath(MediaArtifactItem? item, string? artifactKind)
    {
        if (item is null)
        {
            return null;
        }

        var normalized = (artifactKind ?? string.Empty).Trim().ToLowerInvariant();
        return normalized switch
        {
            "ipa" => item.IpaPath ?? item.PrimaryArtifactPath,
            "readable-text" or "readable_text" or "readable" => item.ReadableTextPath ?? item.PrimaryArtifactPath,
            _ => item.PrimaryArtifactPath ?? item.ReadableTextPath ?? item.IpaPath,
        };
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

            foreach (var runDirectory in EnumerateJobDirectories(root.Path, includeDeleteRequested: true))
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

    private async Task DeleteOrRequestRunDeletionAsync(string runDirectory, CancellationToken cancellationToken)
    {
        if (!Directory.Exists(runDirectory))
        {
            return;
        }

        var status = await ReadJsonAsync<JobStatusDocument>(Path.Combine(runDirectory, "status.json"), cancellationToken);
        var request = await ReadJsonAsync<JobRequestDocument>(Path.Combine(runDirectory, "request.json"), cancellationToken);
        var isLocked = File.Exists(Path.Combine(runDirectory, JobLockFileName));
        var isActive = IsActiveRunState(status?.State) || isLocked;

        if (isActive && isLocked)
        {
            RemoveCatalogRowsForRun(request, status, runDirectory);
            await RequestRunDeletionAsync(runDirectory, cancellationToken);
            return;
        }

        RemoveCatalogRowsForRun(request, status, runDirectory);
        DeleteUploadDirectories(request);
        Directory.Delete(runDirectory, recursive: true);
    }

    private static Task RequestRunDeletionAsync(string runDirectory, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(runDirectory);
        return File.WriteAllTextAsync(
            Path.Combine(runDirectory, DeleteRequestedMarkerFileName),
            $"requested_at={DateTimeOffset.UtcNow:O}{Environment.NewLine}",
            cancellationToken);
    }

    private static bool IsDeleteRequested(string runDirectory) =>
        File.Exists(Path.Combine(runDirectory, DeleteRequestedMarkerFileName));

    private static void RemoveCatalogRowsForRun(JobRequestDocument? request, JobStatusDocument? status, string runDirectory)
    {
        if (request is null || string.IsNullOrWhiteSpace(request.OutputRootPath))
        {
            return;
        }

        var path = Path.Combine(request.OutputRootPath, ".timeline-for-audio", "catalog.jsonl");
        if (!File.Exists(path))
        {
            return;
        }

        var targetJobId = status?.JobId ?? request.JobId ?? Path.GetFileName(runDirectory);
        var normalizedRunDirectory = NormalizePath(runDirectory);
        var keptLines = new List<string>();
        var removedAny = false;

        foreach (var line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                using var document = JsonDocument.Parse(line);
                var payload = document.RootElement;
                var rowJobId = GetOptionalString(payload, "job_id");
                var rowRunDirectory = GetOptionalString(payload, "run_dir");
                var sameJob = !string.IsNullOrWhiteSpace(targetJobId)
                    && string.Equals(rowJobId, targetJobId, StringComparison.OrdinalIgnoreCase);
                var sameRunDirectory = !string.IsNullOrWhiteSpace(rowRunDirectory)
                    && string.Equals(NormalizePath(rowRunDirectory), normalizedRunDirectory, StringComparison.OrdinalIgnoreCase);
                if (sameJob || sameRunDirectory)
                {
                    removedAny = true;
                    continue;
                }
            }
            catch
            {
                keptLines.Add(line);
                continue;
            }

            keptLines.Add(line);
        }

        if (!removedAny)
        {
            return;
        }

        if (keptLines.Count == 0)
        {
            File.Delete(path);
            var parent = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(parent) && Directory.Exists(parent) &&
                !Directory.EnumerateFileSystemEntries(parent).Any())
            {
                Directory.Delete(parent);
            }
            return;
        }

        File.WriteAllLines(path, keptLines, Encoding.UTF8);
    }

    private static string NormalizePath(string path) =>
        Path.GetFullPath(path)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

    private static bool IsActiveRunState(string? state) =>
        string.Equals(state, "pending", StringComparison.OrdinalIgnoreCase) ||
        string.Equals(state, "running", StringComparison.OrdinalIgnoreCase);

    private static string NormalizeExportArtifactKind(string? artifactKind)
    {
        var normalized = (artifactKind ?? "readable-text").Trim().ToLowerInvariant();
        return normalized switch
        {
            "readable-text" or "readable_text" or "readable" => "readable-text",
            "ipa" => "ipa",
            _ => throw new InvalidOperationException($"Unsupported artifact kind: {artifactKind}")
        };
    }

    private static string ExportArtifactTitle(string artifactKind) =>
        string.Equals(artifactKind, "ipa", StringComparison.OrdinalIgnoreCase)
            ? "IPA"
            : "Readable Text";

    private static void BuildExportPackage(
        string runDirectory,
        string jobId,
        string exportRoot,
        string artifactKind,
        JobRequestDocument? request,
        JobStatusDocument? status,
        JobResultDocument? result,
        ManifestDocument? manifest)
    {
        Directory.CreateDirectory(exportRoot);
        var normalizedArtifactKind = NormalizeExportArtifactKind(artifactKind);
        var artifactRoot = Path.Combine(exportRoot, normalizedArtifactKind);
        Directory.CreateDirectory(artifactRoot);
        var artifactRows = ResolveExportArtifactRows(runDirectory, request, manifest);

        artifactRows = artifactRows
            .OrderBy(static row => row.Label, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static row => row.AudioId, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var conversionInfoPath = FindConversionInfoPath(runDirectory);
        if (!string.IsNullOrWhiteSpace(conversionInfoPath))
        {
            File.Copy(conversionInfoPath, Path.Combine(exportRoot, "CONVERSION_INFO.md"), overwrite: true);
        }

        var hasFailureArtifacts = WriteFailureArtifacts(runDirectory, exportRoot, jobId, status, result, manifest, artifactRows.Count);

        var usedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var exportedRows = new List<ExportIndexRow>();
        foreach (var row in artifactRows)
        {
            var selectedSourcePath = string.Equals(normalizedArtifactKind, "ipa", StringComparison.OrdinalIgnoreCase)
                ? row.IpaPath
                : row.ReadableTextPath;
            if (string.IsNullOrWhiteSpace(selectedSourcePath) || !File.Exists(selectedSourcePath))
            {
                continue;
            }
            var fileName = EnsureUniqueExportFileName($"{row.Label}.md", usedNames);
            File.Copy(selectedSourcePath, Path.Combine(artifactRoot, fileName), overwrite: true);
            var exportedRow = new ExportIndexRow
            {
                Label = row.Label,
                SourcePath = row.SourcePath,
                ArtifactPath = $"{normalizedArtifactKind}/{fileName}",
            };
            exportedRows.Add(exportedRow);
        }

        if (exportedRows.Count == 0)
        {
            throw new InvalidOperationException($"No completed {ExportArtifactTitle(normalizedArtifactKind)} artifacts are available to download for this job.");
        }

        WriteExportIndexHtml(
            exportRoot,
            jobId,
            normalizedArtifactKind,
            exportedRows,
            hasConversionInfo: File.Exists(Path.Combine(exportRoot, "CONVERSION_INFO.md")),
            hasFailureReport: File.Exists(Path.Combine(exportRoot, "FAILURE_REPORT.md")),
            hasWorkerLog: File.Exists(Path.Combine(exportRoot, "logs", "worker.log")));
    }

    private static List<(string AudioId, string Label, string? IpaPath, string? ReadableTextPath, string SourcePath)> ResolveExportArtifactRows(
        string runDirectory,
        JobRequestDocument? request,
        ManifestDocument? manifest)
    {
        var resolvedItems = ResolveArtifactItems(runDirectory, request, manifest);
        if (resolvedItems.Count == 0)
        {
            return [];
        }

        var artifactRows = new List<(string AudioId, string Label, string? IpaPath, string? ReadableTextPath, string SourcePath)>();
        foreach (var item in resolvedItems)
        {
            var anchorArtifactPath = item.PrimaryArtifactPath ?? item.ReadableTextPath ?? item.IpaPath;
            SourceInfoExportDocument? sourceInfo = null;
            var sourceInfoPath = string.IsNullOrWhiteSpace(anchorArtifactPath) ? null : ResolveSourceInfoPath(anchorArtifactPath);
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

            artifactRows.Add((
                item.MediaId,
                BestExportLabel(item.MediaId, sourceInfo, item.SourcePath),
                item.IpaPath,
                item.ReadableTextPath,
                item.SourcePath));
        }

        return artifactRows;
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
            "This job produced downloadable artifacts, but some items did not complete successfully.",
            "",
            $"- Job ID: `{jobId}`",
            $"- Final state: `{status?.State ?? result?.State ?? "unknown"}`",
            $"- Exported artifacts: `{exportedTimelineCount}`",
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
            sourceInfo?.RecordedAt,
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
            var lastWriteTime = File.GetLastWriteTime(sourceInfo.ResolvedPath);
            if (lastWriteTime != DateTime.MinValue)
            {
                return lastWriteTime.ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
            }

            var creationTime = File.GetCreationTime(sourceInfo.ResolvedPath);
            if (creationTime != DateTime.MinValue)
            {
                return creationTime.ToString("yyyy-MM-dd HH-mm-ss", System.Globalization.CultureInfo.InvariantCulture);
            }
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

    private static string InferArtifactKind(string? artifactPath)
    {
        if (string.IsNullOrWhiteSpace(artifactPath))
        {
            return "readable_text";
        }

        if (artifactPath.EndsWith($"{Path.DirectorySeparatorChar}ipa{Path.DirectorySeparatorChar}IPA.md", StringComparison.OrdinalIgnoreCase) ||
            artifactPath.EndsWith($"{Path.AltDirectorySeparatorChar}ipa{Path.AltDirectorySeparatorChar}IPA.md", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(Path.GetFileName(artifactPath), "IPA.md", StringComparison.OrdinalIgnoreCase))
        {
            return "ipa";
        }

        return "readable_text";
    }

    private static SpeakerMetadata? ResolveSpeakerMetadata(string? anchorArtifactPath)
    {
        if (string.IsNullOrWhiteSpace(anchorArtifactPath))
        {
            return null;
        }

        var speakerSummaryPath = ResolveSiblingArtifactPath(anchorArtifactPath, "analysis/speaker_summary.json");
        if (string.IsNullOrWhiteSpace(speakerSummaryPath) || !File.Exists(speakerSummaryPath))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(speakerSummaryPath));
            var root = document.RootElement;
            var speakerCount = root.TryGetProperty("speaker_count", out var countElement) &&
                               countElement.ValueKind == JsonValueKind.Number
                ? countElement.GetInt32()
                : (int?)null;
            var speakerCountStatus = GetOptionalString(root, "speaker_count_status");
            var speakerCountNote = GetOptionalString(root, "speaker_count_note");
            var diarizationUsed = root.TryGetProperty("diarization_used", out var diarizationElement) &&
                                  diarizationElement.ValueKind == JsonValueKind.True;
            var diarizationError = GetOptionalString(root, "diarization_error");

            if (string.IsNullOrWhiteSpace(speakerCountStatus))
            {
                speakerCountStatus = speakerCount switch
                {
                    > 0 when diarizationUsed => "confirmed",
                    > 0 => "estimated",
                    _ => "unavailable",
                };
            }

            if (string.IsNullOrWhiteSpace(speakerCountNote) &&
                string.Equals(speakerCountStatus, "estimated", StringComparison.OrdinalIgnoreCase))
            {
                speakerCountNote = string.IsNullOrWhiteSpace(diarizationError)
                    ? "Speaker count is inferred from current turns without confirmed speaker separation."
                    : diarizationError;
            }

            if (string.IsNullOrWhiteSpace(speakerCountNote) &&
                string.Equals(speakerCountStatus, "unavailable", StringComparison.OrdinalIgnoreCase))
            {
                speakerCountNote = string.IsNullOrWhiteSpace(diarizationError)
                    ? "No speaker-attributed turns were available."
                    : diarizationError;
            }

            return new SpeakerMetadata
            {
                SpeakerCount = speakerCount,
                SpeakerCountStatus = speakerCountStatus,
                SpeakerCountNote = speakerCountNote,
            };
        }
        catch
        {
            return null;
        }
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

    private static void WriteExportIndexHtml(
        string exportRoot,
        string jobId,
        string artifactKind,
        IReadOnlyList<ExportIndexRow> rows,
        bool hasConversionInfo,
        bool hasFailureReport,
        bool hasWorkerLog)
    {
        static string Encode(string? value) => WebUtility.HtmlEncode(value ?? "");
        static string LinkOrMuted(string? path, string label) =>
            string.IsNullOrWhiteSpace(path)
                ? "<span class=\"muted\">N/A</span>"
                : $"<a href=\"{Encode(path)}\">{Encode(label)}</a>";

        var topLinks = new List<string>();
        if (hasConversionInfo)
        {
            topLinks.Add("<li><a href=\"CONVERSION_INFO.md\">CONVERSION_INFO.md</a></li>");
        }
        if (hasFailureReport)
        {
            topLinks.Add("<li><a href=\"FAILURE_REPORT.md\">FAILURE_REPORT.md</a></li>");
        }
        if (hasWorkerLog)
        {
            topLinks.Add("<li><a href=\"logs/worker.log\">logs/worker.log</a></li>");
        }

        var bodyRows = new StringBuilder();
        foreach (var row in rows)
        {
            bodyRows.AppendLine("<tr>");
            bodyRows.AppendLine(string.Concat("<td>", Encode(row.Label), "</td>"));
            bodyRows.AppendLine(string.Concat("<td><code>", Encode(row.SourcePath), "</code></td>"));
            bodyRows.AppendLine(string.Concat("<td>", LinkOrMuted(row.ArtifactPath, ExportArtifactTitle(artifactKind).ToLowerInvariant()), "</td>"));
            bodyRows.AppendLine("</tr>");
        }

        var html = string.Join(
            Environment.NewLine,
            [
                "<!doctype html>",
                "<html lang=\"en\">",
                "<head>",
                "  <meta charset=\"utf-8\">",
                $"  <title>TimelineForAudio export {Encode(jobId)}</title>",
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
                "  <style>",
                "    :root { color-scheme: light; }",
                "    body { font-family: 'Segoe UI', sans-serif; margin: 24px; color: #1e293b; background: #f8fafc; }",
                "    h1, h2 { margin: 0 0 12px; }",
                "    p, li { line-height: 1.6; }",
                "    code { font-family: Consolas, monospace; font-size: 12px; }",
                "    .panel { background: white; border: 1px solid #dbe4ee; border-radius: 16px; padding: 20px; margin-bottom: 20px; }",
                "    table { width: 100%; border-collapse: collapse; background: white; }",
                "    th, td { border-bottom: 1px solid #e2e8f0; padding: 10px 12px; text-align: left; vertical-align: top; }",
                "    th { background: #eff6ff; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }",
                "    a { color: #0f766e; text-decoration: none; }",
                "    a:hover { text-decoration: underline; }",
                "    .muted { color: #94a3b8; }",
                "  </style>",
                "</head>",
                "<body>",
                "  <section class=\"panel\">",
                "    <h1>TimelineForAudio export</h1>",
                $"    <p>Job ID: <code>{Encode(jobId)}</code></p>",
                $"    <p>This package contains the {Encode(ExportArtifactTitle(artifactKind))} export for the selected job.</p>",
                "  </section>",
                "  <section class=\"panel\">",
                "    <h2>Top-level files</h2>",
                $"    <ul>{string.Join("", topLinks)}</ul>",
                "  </section>",
                "  <section class=\"panel\">",
                "    <h2>Per-item artifacts</h2>",
                "    <table>",
                "      <thead>",
                $"        <tr><th>Item</th><th>Source</th><th>{Encode(ExportArtifactTitle(artifactKind))}</th></tr>",
                "      </thead>",
                "      <tbody>",
                bodyRows.ToString(),
                "      </tbody>",
                "    </table>",
                "  </section>",
                "</body>",
                "</html>",
                "",
            ]);

        File.WriteAllText(Path.Combine(exportRoot, "README.html"), html, Encoding.UTF8);
    }

    private sealed class ExportIndexRow
    {
        public string Label { get; set; } = "";
        public string SourcePath { get; set; } = "";
        public string ArtifactPath { get; set; } = "";
    }

    private sealed class SpeakerMetadata
    {
        public int? SpeakerCount { get; set; }
        public string? SpeakerCountStatus { get; set; }
        public string? SpeakerCountNote { get; set; }
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
        [JsonPropertyName("original_path")]
        public string? OriginalPath { get; set; }

        [JsonPropertyName("resolved_path")]
        public string? ResolvedPath { get; set; }

        [JsonPropertyName("display_name")]
        public string? DisplayName { get; set; }

        [JsonPropertyName("recorded_at")]
        public string? RecordedAt { get; set; }

        [JsonPropertyName("captured_at")]
        public string? CapturedAt { get; set; }
    }

    private sealed class CatalogRow
    {
        public string Sha256 { get; set; } = "";

        public string ConversionSignature { get; set; } = "";

        public string? JobId { get; set; }

        public string? MediaId { get; set; }

        public string? RunDirectory { get; set; }

        public string? OriginalPath { get; set; }
    }
}



