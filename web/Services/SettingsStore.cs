using System.Text.Json;
using Audio2Timeline.Web.Infrastructure;
using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

public sealed class SettingsStore(AppPaths paths)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true,
    };

    public async Task<AppSettingsDocument> LoadAsync(CancellationToken cancellationToken = default)
    {
        if (File.Exists(paths.SettingsPath))
        {
            await using var stream = File.OpenRead(paths.SettingsPath);
            var loaded = await JsonSerializer.DeserializeAsync<AppSettingsDocument>(
                stream,
                _jsonOptions,
                cancellationToken);
            return Normalize(loaded ?? new AppSettingsDocument(), hasPersistedSettings: true);
        }

        if (File.Exists(paths.RuntimeDefaultsPath))
        {
            await using var stream = File.OpenRead(paths.RuntimeDefaultsPath);
            var defaults = await JsonSerializer.DeserializeAsync<AppSettingsDocument>(
                stream,
                _jsonOptions,
                cancellationToken);
            return Normalize(defaults ?? new AppSettingsDocument());
        }

        return Normalize(new AppSettingsDocument());
    }

    public async Task SaveAsync(
        AppSettingsDocument settings,
        string? token = null,
        bool replaceToken = false,
        CancellationToken cancellationToken = default)
    {
        settings = Normalize(settings);
        Directory.CreateDirectory(Path.GetDirectoryName(paths.SettingsPath)!);
        await File.WriteAllTextAsync(
            paths.SettingsPath,
            JsonSerializer.Serialize(settings, _jsonOptions),
            cancellationToken);

        if (!replaceToken)
        {
            return;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(paths.TokenPath)!);
        if (string.IsNullOrWhiteSpace(token))
        {
            if (File.Exists(paths.TokenPath))
            {
                File.Delete(paths.TokenPath);
            }

            return;
        }

        await File.WriteAllTextAsync(paths.TokenPath, token.Trim(), cancellationToken);
    }

    public async Task<bool> HasTokenAsync(CancellationToken cancellationToken = default)
    {
        if (!File.Exists(paths.TokenPath))
        {
            return false;
        }

        var value = await File.ReadAllTextAsync(paths.TokenPath, cancellationToken);
        return !string.IsNullOrWhiteSpace(value);
    }

    public async Task<string?> ReadTokenAsync(CancellationToken cancellationToken = default)
    {
        if (!File.Exists(paths.TokenPath))
        {
            return null;
        }

        var value = await File.ReadAllTextAsync(paths.TokenPath, cancellationToken);
        return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    }

    public async Task SaveHuggingFaceAsync(
        string? token,
        bool termsConfirmed,
        CancellationToken cancellationToken = default)
    {
        var settings = await LoadAsync(cancellationToken);
        settings.HuggingfaceTermsConfirmed = termsConfirmed;
        await SaveAsync(
            settings,
            token,
            replaceToken: true,
            cancellationToken);
    }

    private AppSettingsDocument Normalize(AppSettingsDocument value, bool hasPersistedSettings = false)
    {
        value.InputRoots =
        [
            new RootOption
            {
                Id = "uploads",
                DisplayName = "Uploads",
                Path = paths.UploadsRoot,
                Enabled = true,
            },
        ];

        value.OutputRoots =
        [
            new RootOption
            {
                Id = "runs",
                DisplayName = "Runs",
                Path = paths.OutputsRoot,
                Enabled = true,
            },
        ];

        value.AudioExtensions ??= [];

        value.ComputeMode = value.ComputeMode?.Trim().ToLowerInvariant() switch
        {
            "gpu" => "gpu",
            _ => "cpu",
        };

        value.ProcessingQuality = value.ProcessingQuality?.Trim().ToLowerInvariant() switch
        {
            "high" => "high",
            _ => "standard",
        };

        value.TranscriptionInitialPrompt = value.TranscriptionInitialPrompt?.Trim() ?? "";
        value.TranscriptNormalizationMode = ConversionSignature.NormalizeTranscriptNormalizationMode(
            value.TranscriptNormalizationMode);
        value.TranscriptNormalizationGlossary = value.TranscriptNormalizationGlossary ?? "";

        value.UiLanguage = value.UiLanguage?.Trim() switch
        {
            { Length: > 0 } language => language,
            _ => "en",
        };

        value.LanguageSelected = value.LanguageSelected || hasPersistedSettings;

        return value;
    }
}
