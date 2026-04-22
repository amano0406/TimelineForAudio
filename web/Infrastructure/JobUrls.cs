namespace TimelineForAudio.Web.Infrastructure;

public static class JobUrls
{
    public static string Details(string jobId) => $"/jobs/{Uri.EscapeDataString(jobId)}";

    public static string Media(string jobId, string mediaId) =>
        $"{Details(jobId)}/{Uri.EscapeDataString(mediaId)}";

    public static string Download(string jobId, string? artifactKind = null)
    {
        var path = $"{Details(jobId)}/download";
        return string.IsNullOrWhiteSpace(artifactKind)
            ? path
            : $"{path}?artifact={Uri.EscapeDataString(artifactKind)}";
    }
}
