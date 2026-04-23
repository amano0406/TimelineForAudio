using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class ModelCacheService(AppPaths paths)
{
    public Task<ModelCacheSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var directories = 0;
        long totalBytes = 0;
        foreach (var root in EnumerateCacheRoots())
        {
            if (!Directory.Exists(root))
            {
                continue;
            }

            directories++;
            totalBytes += GetDirectorySize(root);
        }

        return Task.FromResult(new ModelCacheSnapshot
        {
            HasCache = directories > 0 && totalBytes > 0,
            DirectoryCount = directories,
            TotalBytes = totalBytes,
        });
    }

    public Task<int> ClearAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var cleared = 0;
        foreach (var root in EnumerateCacheRoots())
        {
            if (!Directory.Exists(root))
            {
                Directory.CreateDirectory(root);
                continue;
            }

            foreach (var directory in Directory.EnumerateDirectories(root))
            {
                cancellationToken.ThrowIfCancellationRequested();
                Directory.Delete(directory, recursive: true);
                cleared++;
            }

            foreach (var file in Directory.EnumerateFiles(root))
            {
                cancellationToken.ThrowIfCancellationRequested();
                File.Delete(file);
                cleared++;
            }
        }

        return Task.FromResult(cleared);
    }

    public Task<long> GetHuggingFaceModelSizeBytesAsync(string modelId, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(modelId))
        {
            return Task.FromResult(0L);
        }

        var normalized = $"models--{modelId.Replace("/", "--", StringComparison.Ordinal)}";
        long totalBytes = 0;

        foreach (var candidate in EnumerateHuggingFaceModelRoots(normalized))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!Directory.Exists(candidate))
            {
                continue;
            }

            var snapshotsRoot = Path.Combine(candidate, "snapshots");
            if (!Directory.Exists(snapshotsRoot))
            {
                continue;
            }

            totalBytes += GetDirectorySize(candidate);
        }

        return Task.FromResult(totalBytes);
    }

    private IEnumerable<string> EnumerateCacheRoots()
    {
        yield return paths.HuggingFaceCacheRoot;
        yield return paths.TorchCacheRoot;
    }

    private IEnumerable<string> EnumerateHuggingFaceModelRoots(string normalizedModelId)
    {
        yield return Path.Combine(paths.HuggingFaceCacheRoot, normalizedModelId);
        yield return Path.Combine(paths.HuggingFaceCacheRoot, "hub", normalizedModelId);
    }

    private static long GetDirectorySize(string root)
    {
        long totalBytes = 0;

        foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
        {
            try
            {
                totalBytes += new FileInfo(file).Length;
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        return totalBytes;
    }
}
