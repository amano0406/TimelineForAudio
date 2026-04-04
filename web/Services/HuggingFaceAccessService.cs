using System.Net;
using System.Net.Http.Headers;
using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

public sealed class HuggingFaceAccessService(
    HttpClient httpClient,
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
    private const string FasterWhisperLargeModelId = "large-v3";

    private readonly string? _overrideState = configuration["AUDIO2TIMELINE_HF_ACCESS_OVERRIDE"];

    public async Task<HuggingFaceAccessSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var isHighQuality = string.Equals(
            settings.ProcessingQuality,
            "high",
            StringComparison.OrdinalIgnoreCase);
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
                    RequiresApproval = true,
                    TokenConfigured = hasToken,
                    TermsConfirmed = settings.HuggingfaceTermsConfirmed,
                },
                CreateUngatedModel(
                    isHighQuality ? FasterWhisperLargeModelId : FasterWhisperMediumModelId,
                    isHighQuality ? "faster-whisper large-v3" : "faster-whisper medium",
                    "Speech transcription"),
            ],
        };

        if (!string.IsNullOrWhiteSpace(_overrideState))
        {
            return ApplyState(snapshot, _overrideState.Trim().ToLowerInvariant(), _overrideState);
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

            if (response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.Unauthorized)
            {
                return ApplyState(snapshot, "unauthorized", "Token is saved, but model approval is not available yet.");
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

    private static GatedModelStatusItem CreateUngatedModel(string modelId, string displayName, string purpose) =>
        new()
        {
            ModelId = modelId,
            DisplayName = displayName,
            Purpose = purpose,
            ApprovalUrl = string.Empty,
            RequiresApproval = false,
            TokenConfigured = false,
            TermsConfirmed = true,
            AccessState = "available",
        };
}
