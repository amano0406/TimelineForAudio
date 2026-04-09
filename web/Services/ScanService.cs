using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class ScanService(SettingsStore settingsStore)
{
    public async Task<IReadOnlyList<ScannedAudioItem>> ScanAsync(
        IEnumerable<string>? sourceIds,
        CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var allowed = settings.AudioExtensions
            .Where(static ext => !string.IsNullOrWhiteSpace(ext))
            .Select(static ext => ext.StartsWith('.') ? ext : $".{ext}")
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var hasSelectionFilter = sourceIds is not null;
        var selectedIds = sourceIds?
            .Where(static id => !string.IsNullOrWhiteSpace(id))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var roots = settings.InputRoots
            .Where(static root => root.Enabled)
            .Where(root => !hasSelectionFilter || (selectedIds?.Contains(root.Id) ?? false))
            .ToList();

        var results = new List<ScannedAudioItem>();
        foreach (var root in roots)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!Directory.Exists(root.Path))
            {
                continue;
            }

            var files = Directory.EnumerateFiles(root.Path, "*", SearchOption.AllDirectories)
                .Where(path => allowed.Contains(Path.GetExtension(path)))
                .OrderBy(static path => path, StringComparer.OrdinalIgnoreCase);

            foreach (var file in files)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var info = new FileInfo(file);
                results.Add(new ScannedAudioItem
                {
                    SourceId = root.Id,
                    SourceKind = "mounted_root",
                    OriginalPath = file,
                    DisplayName = info.Name,
                    SizeBytes = info.Exists ? info.Length : 0,
                });
            }
        }

        return results;
    }
}
