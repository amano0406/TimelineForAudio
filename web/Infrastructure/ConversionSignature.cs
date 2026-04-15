using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TimelineForAudio.Web.Infrastructure;

public static class ConversionSignature
{
    public const string PipelineVersion = "2026-04-11-2pass2-diarize2";
    public const string TranscriptionBackend = "faster-whisper";
    public const string DiarizationModelId = "pyannote/speaker-diarization-community-1";
    public const string VadBackend = "faster-whisper-builtin";
    public const string VadModelId = "faster-whisper-default";
    public const string ContextBuilderVersion = "context-builder-v1";

    public static string ResolveTranscriptionModelId(string? processingQuality) =>
        RuntimeProfile.ResolveTranscriptionModelId(processingQuality);

    public static string Build(
        string? computeMode,
        string? processingQuality,
        bool diarizationEnabled,
        string? supplementalContextText = null,
        bool secondPassEnabled = true,
        string? contextBuilderVersion = null)
    {
        var payload = new Dictionary<string, object?>
        {
            ["pipeline"] = "TimelineForAudio",
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
            ["second_pass"] = new Dictionary<string, object?>
            {
                ["enabled"] = secondPassEnabled,
                ["supplemental_context_sha256"] = HashHintText(supplementalContextText),
                ["context_builder_version"] = string.IsNullOrWhiteSpace(contextBuilderVersion)
                    ? ContextBuilderVersion
                    : contextBuilderVersion,
            },
        };

        var canonicalJson = JsonSerializer.Serialize(payload);
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(canonicalJson));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public static string NormalizeComputeMode(string? value) =>
        RuntimeProfile.NormalizeComputeMode(value);

    public static string NormalizeProcessingQuality(string? value) =>
        RuntimeProfile.NormalizeProcessingQuality(value);

    private static string? HashHintText(string? value)
    {
        var normalized = NormalizeHintText(value);
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return null;
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(normalized));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string? NormalizeHintText(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var normalized = value.Replace("\r\n", "\n").Replace('\r', '\n');
        normalized = string.Join(
            "\n",
            normalized.Split('\n', StringSplitOptions.None).Select(static line => line.Trim()));
        normalized = normalized.Trim();
        return string.IsNullOrWhiteSpace(normalized) ? null : normalized;
    }
}
