using System.Text.Json;
using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class UploadSessionStore(AppPaths paths, SettingsStore settingsStore)
{
    private const long ChunkSizeBytes = 8L * 1024 * 1024;

    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<CreateUploadSessionResponse> CreateSessionAsync(CancellationToken cancellationToken = default)
    {
        var sessionId = $"session-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..40];
        var sessionDirectory = GetSessionDirectory(sessionId);
        Directory.CreateDirectory(sessionDirectory);

        var document = new UploadSessionDocument
        {
            SessionId = sessionId,
            CreatedAt = DateTimeOffset.Now.ToString("O"),
            ChunkSizeBytes = ChunkSizeBytes,
        };

        await WriteSessionAsync(document, cancellationToken);
        return new CreateUploadSessionResponse
        {
            SessionId = sessionId,
            ChunkSizeBytes = ChunkSizeBytes,
        };
    }

    public async Task<CreateUploadFileResponse> RegisterFileAsync(
        string sessionId,
        CreateUploadFileRequest request,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(request.OriginalName))
        {
            throw new InvalidOperationException("The upload file name is required.");
        }

        if (request.SizeBytes < 0)
        {
            throw new InvalidOperationException("The upload file size is invalid.");
        }
        if (!await IsSupportedExtensionAsync(request.OriginalName, cancellationToken))
        {
            throw new InvalidOperationException($"Unsupported audio file type: {request.OriginalName}");
        }

        var document = await RequireSessionAsync(sessionId, cancellationToken);
        var fileId = $"file-{document.Files.Count + 1:D4}";
        var safeName = MakeSafeFileName(Path.GetFileName(request.OriginalName));
        var storedPath = Path.Combine(GetSessionDirectory(sessionId), $"{fileId}-{safeName}");
        var expectedChunks = Math.Max(1, (int)Math.Ceiling(request.SizeBytes / (double)document.ChunkSizeBytes));

        document.Files.Add(new UploadSessionFileDocument
        {
            FileId = fileId,
            OriginalName = request.OriginalName,
            SizeBytes = request.SizeBytes,
            ExpectedChunks = expectedChunks,
            UploadedChunks = 0,
            StoredPath = storedPath,
        });

        await WriteSessionAsync(document, cancellationToken);
        return new CreateUploadFileResponse
        {
            FileId = fileId,
            ExpectedChunks = expectedChunks,
        };
    }

    public async Task AppendChunkAsync(
        string sessionId,
        string fileId,
        int chunkIndex,
        Stream source,
        CancellationToken cancellationToken = default)
    {
        var document = await RequireSessionAsync(sessionId, cancellationToken);
        var file = document.Files.FirstOrDefault(item =>
            string.Equals(item.FileId, fileId, StringComparison.OrdinalIgnoreCase));
        if (file is null)
        {
            throw new InvalidOperationException("The upload file could not be found.");
        }

        if (chunkIndex != file.UploadedChunks)
        {
            throw new InvalidOperationException("Chunks must be uploaded in order.");
        }

        var directory = Path.GetDirectoryName(file.StoredPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await using (var target = new FileStream(
            file.StoredPath,
            FileMode.Append,
            FileAccess.Write,
            FileShare.None,
            bufferSize: 1024 * 128,
            useAsync: true))
        {
            await source.CopyToAsync(target, cancellationToken);
        }

        file.UploadedChunks += 1;
        await WriteSessionAsync(document, cancellationToken);
    }

    public async Task<IReadOnlyList<UploadedFileReference>> CompleteSessionAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        var document = await RequireSessionAsync(sessionId, cancellationToken);
        foreach (var file in document.Files)
        {
            if (file.UploadedChunks != file.ExpectedChunks)
            {
                throw new InvalidOperationException($"The upload is incomplete for {file.OriginalName}.");
            }
        }

        return document.Files
            .Select(file => new UploadedFileReference
            {
                ReferenceId = $"{sessionId}:{file.FileId}",
                StoredPath = file.StoredPath,
                OriginalName = file.OriginalName,
                SizeBytes = file.SizeBytes,
            })
            .ToList();
    }

    public Task<bool> DeleteSessionAsync(string sessionId, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var sessionDirectory = GetSessionDirectory(sessionId);
        if (!Directory.Exists(sessionDirectory))
        {
            return Task.FromResult(false);
        }

        var uploadsRoot = Path.GetFullPath(paths.UploadsRoot);
        var fullSessionDirectory = Path.GetFullPath(sessionDirectory);
        if (!IsSubdirectoryOf(fullSessionDirectory, uploadsRoot))
        {
            throw new InvalidOperationException("The upload session path is invalid.");
        }

        Directory.Delete(fullSessionDirectory, recursive: true);
        return Task.FromResult(true);
    }

    private async Task<UploadSessionDocument> RequireSessionAsync(string sessionId, CancellationToken cancellationToken)
    {
        var path = GetSessionPath(sessionId);
        if (!File.Exists(path))
        {
            throw new InvalidOperationException("The upload session could not be found.");
        }

        await using var stream = File.OpenRead(path);
        var document = await JsonSerializer.DeserializeAsync<UploadSessionDocument>(stream, _jsonOptions, cancellationToken);
        return document ?? throw new InvalidOperationException("The upload session is invalid.");
    }

    private async Task WriteSessionAsync(UploadSessionDocument document, CancellationToken cancellationToken)
    {
        var path = GetSessionPath(document.SessionId);
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(document, _jsonOptions), cancellationToken);
    }

    private string GetSessionDirectory(string sessionId) =>
        Path.Combine(paths.UploadsRoot, sessionId);

    private string GetSessionPath(string sessionId) =>
        Path.Combine(GetSessionDirectory(sessionId), "session.json");

    private static string MakeSafeFileName(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(value.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
        return string.IsNullOrWhiteSpace(sanitized) ? $"upload-{Guid.NewGuid():N}.bin" : sanitized;
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

    private async Task<bool> IsSupportedExtensionAsync(string fileName, CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        if (settings.AudioExtensions.Count == 0)
        {
            return true;
        }

        var extension = Path.GetExtension(fileName)?.Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(extension))
        {
            return false;
        }

        return settings.AudioExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase);
    }
}
