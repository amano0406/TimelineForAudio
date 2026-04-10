namespace TimelineForAudio.Web.Infrastructure;

public static class RuntimeProfile
{
    public const double HighQualityWarningGpuMemoryGiB = 8.0;
    public const double HighQualityRecommendedGpuMemoryGiB = 10.0;

    public static string NormalizeComputeMode(string? value) =>
        string.Equals(value, "gpu", StringComparison.OrdinalIgnoreCase) ? "gpu" : "cpu";

    public static string NormalizeProcessingQuality(string? value) =>
        string.Equals(value, "high", StringComparison.OrdinalIgnoreCase) ? "high" : "standard";

    public static string ResolveTranscriptionModelId(string? processingQuality) =>
        string.Equals(processingQuality, "high", StringComparison.OrdinalIgnoreCase)
            ? "large-v3"
            : "medium";

    public static bool ResolveDiarizationDefault(string? computeMode, bool tokenReady) =>
        tokenReady && string.Equals(NormalizeComputeMode(computeMode), "gpu", StringComparison.OrdinalIgnoreCase);
}
