using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace TimelineForAudio.Web.Infrastructure;

public static class ConversionSignature
{
    public const string PipelineVersion = "2026-04-21-v2-ipa1";
    public const string TranscriptionBackend = "faster-whisper";
    public const string DiarizationModelId = "pyannote/speaker-diarization-community-1";
    public const string VadBackend = "faster-whisper-builtin";
    public const string VadModelId = "faster-whisper-default";
    public const string ContextBuilderVersion = "context-builder-v1";
    public const string LocalLlmReconstructionBackend = "local-transformers-japanese-p2g-v1";
    public const string LocalLlmModelId = "Respair/Japanese_Phoneme_to_Grapheme_LLM";
    public const string LocalLlmPromptVersion = "ipa-turn-reconstruction-ja-v2";
    public const string ReadableTextMarkdownSchema = "turn-markdown-v2";
    public const string IpaBackend = "sudachi-reading-ipa-v1";
    public const string IpaReadingBackend = "sudachipy-core";
    public const string IpaAsciiFallback = "latin-heuristic-v1";
    public const string IpaMarkdownSchema = "turn-markdown-v1";

    public static string ResolveTranscriptionModelId() =>
        RuntimeProfile.ResolveTranscriptionModelId();

    public static string Build(
        string? computeMode,
        bool diarizationEnabled,
        string? languageHint = null,
        string? supplementalContextText = null,
        string? contextBuilderVersion = null)
        => BuildGenerationSignature(
            computeMode,
            diarizationEnabled,
            languageHint,
            supplementalContextText,
            contextBuilderVersion);

    public static string BuildGenerationSignature(
        string? computeMode,
        bool diarizationEnabled,
        string? languageHint = null,
        string? supplementalContextText = null,
        string? contextBuilderVersion = null)
    {
        var payload = new Dictionary<string, object?>
        {
            ["pipeline"] = "TimelineForAudio",
            ["pipeline_version"] = PipelineVersion,
            ["compute_mode"] = NormalizeComputeMode(computeMode),
            ["transcription"] = new Dictionary<string, object?>
            {
                ["backend"] = TranscriptionBackend,
                ["model_id"] = ResolveTranscriptionModelId(),
                ["language"] = "ja",
            },
            ["reconstruction"] = new Dictionary<string, object?>
            {
                ["backend"] = ResolveReconstructionBackend(languageHint, computeMode),
                ["model_id"] = ResolveReconstructionModelId(languageHint, computeMode),
                ["prompt_version"] = ResolveReconstructionPromptVersion(languageHint, computeMode),
                ["decoding"] = BuildReconstructionDecoding(languageHint, computeMode),
                ["language_hint"] = NormalizeLanguageHint(languageHint),
                ["readable_text_schema"] = ReadableTextMarkdownSchema,
            },
            ["ipa"] = new Dictionary<string, object?>
            {
                ["backend"] = IpaBackend,
                ["reading_backend"] = IpaReadingBackend,
                ["ascii_fallback"] = IpaAsciiFallback,
                ["ipa_schema"] = IpaMarkdownSchema,
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
            ["audio_features"] = new Dictionary<string, object?>
            {
                ["pause"] = true,
                ["loudness"] = true,
                ["speaking_rate"] = true,
                ["pitch"] = true,
                ["voice_feature_summary"] = true,
            },
            ["ipa_cleanup"] = new Dictionary<string, object?>
            {
                ["supplemental_context_sha256"] = HashHintText(supplementalContextText),
                ["rules_version"] = string.IsNullOrWhiteSpace(contextBuilderVersion)
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

    public static string ResolveReconstructionBackend(string? languageHint, string? computeMode = null) =>
        string.Equals(NormalizeComputeMode(computeMode), "gpu", StringComparison.OrdinalIgnoreCase) &&
        LanguageHintSupportsLocalLlm(languageHint)
            ? LocalLlmReconstructionBackend
            : "ipa-aligned-text-fallback-v1";

    public static string? ResolveReconstructionModelId(string? languageHint, string? computeMode = null) =>
        ResolveReconstructionBackend(languageHint, computeMode) == LocalLlmReconstructionBackend
            ? LocalLlmModelId
            : null;

    public static string? ResolveReconstructionPromptVersion(string? languageHint, string? computeMode = null) =>
        ResolveReconstructionBackend(languageHint, computeMode) == LocalLlmReconstructionBackend
            ? LocalLlmPromptVersion
            : null;

    public static string? NormalizeLanguageHint(string? value)
    {
        var normalized = NormalizeHintText(value);
        return string.IsNullOrWhiteSpace(normalized)
            ? null
            : normalized.ToLowerInvariant();
    }

    public static Dictionary<string, object?>? BuildReconstructionDecoding(
        string? languageHint,
        string? computeMode = null)
    {
        if (ResolveReconstructionBackend(languageHint, computeMode) != LocalLlmReconstructionBackend)
        {
            return null;
        }

        return new Dictionary<string, object?>
        {
            ["do_sample"] = false,
            ["max_new_tokens"] = 128,
            ["repetition_penalty"] = 1.02,
        };
    }

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

    private static bool LanguageHintSupportsLocalLlm(string? value)
    {
        var normalized = NormalizeHintText(value);
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return true;
        }

        var tokens = normalized
            .ToLowerInvariant()
            .Split([',', ';', '/', ' ', '\t', '\n'], StringSplitOptions.RemoveEmptyEntries);
        return tokens.Any(static token =>
            string.Equals(token, "ja", StringComparison.OrdinalIgnoreCase) ||
            token.StartsWith("ja-", StringComparison.OrdinalIgnoreCase));
    }
}
