using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Audio2Timeline.Web.Infrastructure;

public static class ConversionSignature
{
    public const string PipelineVersion = "2026-04-05-mvp1";
    public const string TranscriptionBackend = "faster-whisper";
    public const string DiarizationModelId = "pyannote/speaker-diarization-community-1";
    public const string VadBackend = "silero-vad";
    public const string VadModelId = "faster-whisper-default";

    public static string ResolveTranscriptionModelId(string? processingQuality) =>
        string.Equals(processingQuality, "high", StringComparison.OrdinalIgnoreCase)
            ? "large-v3"
            : "medium";

    public static string Build(
        string? computeMode,
        string? processingQuality,
        bool diarizationEnabled)
    {
        var payload = new Dictionary<string, object?>
        {
            ["pipeline"] = "audio2timeline",
            ["pipeline_version"] = PipelineVersion,
            ["compute_mode"] = NormalizeComputeMode(computeMode),
            ["processing_quality"] = NormalizeProcessingQuality(processingQuality),
            ["transcription"] = new Dictionary<string, object?>
            {
                ["backend"] = TranscriptionBackend,
                ["model_id"] = ResolveTranscriptionModelId(processingQuality),
                ["language"] = "ja",
            },
            ["diarization"] = new Dictionary<string, object?>
            {
                ["enabled"] = diarizationEnabled,
                ["model_id"] = diarizationEnabled ? DiarizationModelId : null,
            },
            ["vad"] = new Dictionary<string, object?>
            {
                ["backend"] = VadBackend,
                ["model_id"] = VadModelId,
            },
            ["features"] = new Dictionary<string, object?>
            {
                ["pause"] = true,
                ["loudness"] = true,
                ["speaking_rate"] = true,
                ["pitch"] = true,
                ["voice_feature_summary"] = true,
            },
            ["render"] = new Dictionary<string, object?>
            {
                ["timeline_schema"] = "audio-markdown-v1",
            },
        };

        var canonicalJson = JsonSerializer.Serialize(payload);
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(canonicalJson));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static string NormalizeComputeMode(string? value) =>
        string.Equals(value, "gpu", StringComparison.OrdinalIgnoreCase) ? "gpu" : "cpu";

    public static string NormalizeProcessingQuality(string? value) =>
        string.Equals(value, "high", StringComparison.OrdinalIgnoreCase) ? "high" : "standard";
}
