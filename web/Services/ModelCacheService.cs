using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

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

    private IEnumerable<string> EnumerateCacheRoots()
    {
        yield return paths.HuggingFaceCacheRoot;
        yield return paths.TorchCacheRoot;
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
