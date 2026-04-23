using System.Net;
using System.Net.Http.Headers;
using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class HuggingFaceAccessService(
    HttpClient httpClient,
    ModelCacheService modelCacheService,
    SettingsStore settingsStore,
    IConfiguration configuration)
{
    private const string PyannoteModelId = "pyannote/speaker-diarization-community-1";
    private const string PyannoteDisplayName = "pyannote speaker diarization";
    private const string PyannotePurpose = "Speaker diarization";
    private const string PyannoteApprovalUrl = "https://huggingface.co/pyannote/speaker-diarization-community-1";
    private const string PyannoteResolveUrl =
        "https://huggingface.co/pyannote/speaker-diarization-community-1/resolve/main/config.yaml";
    private const string FasterWhisperMediumModelId = "medium";
    private const string FasterWhisperMediumCacheModelId = "Systran/faster-whisper-medium";
    private const string FasterWhisperMediumModelUrl = "https://huggingface.co/Systran/faster-whisper-medium";
    private const string ReconstructionModelId = "Respair/Japanese_Phoneme_to_Grapheme_LLM";
    private const string ReconstructionDisplayName = "Japanese phoneme to grapheme";
    private const string ReconstructionPurpose = "Readable text reconstruction";
    private const string ReconstructionModelUrl = "https://huggingface.co/Respair/Japanese_Phoneme_to_Grapheme_LLM";

    private readonly string? _overrideState = configuration["TIMELINE_FOR_AUDIO_HF_ACCESS_OVERRIDE"];

    public async Task<HuggingFaceAccessSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var pyannoteSavedSizeBytes = await modelCacheService.GetHuggingFaceModelSizeBytesAsync(PyannoteModelId, cancellationToken);
        var fasterWhisperSavedSizeBytes = await modelCacheService.GetHuggingFaceModelSizeBytesAsync(
            FasterWhisperMediumCacheModelId,
            cancellationToken);
        var reconstructionSavedSizeBytes = await modelCacheService.GetHuggingFaceModelSizeBytesAsync(
            ReconstructionModelId,
            cancellationToken);
        var snapshot = new HuggingFaceAccessSnapshot
        {
            HasToken = hasToken,
            TermsConfirmed = settings.HuggingfaceTermsConfirmed,
            Models =
            [
                new GatedModelStatusItem
                {
                    ModelId = PyannoteModelId,
                    DisplayName = PyannoteDisplayName,
                    Purpose = PyannotePurpose,
                    ApprovalUrl = PyannoteApprovalUrl,
                    ModelUrl = PyannoteApprovalUrl,
                    RequiresApproval = true,
                    TokenConfigured = hasToken,
                    TermsConfirmed = settings.HuggingfaceTermsConfirmed,
                    CachedLocally = pyannoteSavedSizeBytes > 0,
                    SavedSizeBytes = pyannoteSavedSizeBytes,
                },
                CreateUngatedModel(
                    FasterWhisperMediumModelId,
                    "faster-whisper medium",
                    "Speech transcription",
                    FasterWhisperMediumModelUrl,
                    fasterWhisperSavedSizeBytes),
                CreateUngatedModel(
                    ReconstructionModelId,
                    ReconstructionDisplayName,
                    ReconstructionPurpose,
                    ReconstructionModelUrl,
                    reconstructionSavedSizeBytes),
            ],
        };

        if (!string.IsNullOrWhiteSpace(_overrideState))
        {
            var normalizedOverride = _overrideState.Trim().ToLowerInvariant() switch
            {
                "unauthorized" => "approval_required",
                _ => _overrideState.Trim().ToLowerInvariant(),
            };
            return ApplyState(snapshot, normalizedOverride, _overrideState);
        }

        if (!hasToken)
        {
            return ApplyState(snapshot, "token_missing", "Token is not configured.");
        }

        var token = await settingsStore.ReadTokenAsync(cancellationToken);
        if (string.IsNullOrWhiteSpace(token))
        {
            return ApplyState(snapshot, "token_missing", "Token is not configured.");
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, PyannoteResolveUrl);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var response = await httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);

            if (response.IsSuccessStatusCode)
            {
                return ApplyState(snapshot, "authorized", "Model access is available.");
            }

            if (response.StatusCode == HttpStatusCode.Forbidden)
            {
                return ApplyState(snapshot, "approval_required", "Token is valid, but model approval is not available yet.");
            }

            if (response.StatusCode == HttpStatusCode.Unauthorized)
            {
                return ApplyState(snapshot, "invalid_token", "Token is saved, but it is not valid.");
            }

            return ApplyState(snapshot, "unknown", $"Unexpected HTTP {(int)response.StatusCode}.");
        }
        catch (Exception ex)
        {
            return ApplyState(snapshot, "unknown", ex.Message);
        }
    }

    private static HuggingFaceAccessSnapshot ApplyState(
        HuggingFaceAccessSnapshot snapshot,
        string state,
        string message)
    {
        snapshot.AccessState = state;
        snapshot.AccessMessage = message;

        foreach (var model in snapshot.Models)
        {
            if (model.RequiresApproval)
            {
                model.AccessState = state;
            }
        }

        return snapshot;
    }

    private static GatedModelStatusItem CreateUngatedModel(
        string modelId,
        string displayName,
        string purpose,
        string modelUrl,
        long savedSizeBytes) =>
        new()
        {
            ModelId = modelId,
            DisplayName = displayName,
            Purpose = purpose,
            ApprovalUrl = string.Empty,
            ModelUrl = modelUrl,
            RequiresApproval = false,
            TokenConfigured = false,
            TermsConfirmed = true,
            AccessState = "available",
            CachedLocally = savedSizeBytes > 0,
            SavedSizeBytes = savedSizeBytes,
        };
}
