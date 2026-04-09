namespace TimelineForAudio.Web.Services;

public sealed class AppInstanceService
{
    public AppInstanceService()
    {
        InstanceId = $"app-{Guid.NewGuid():N}";
        StartedAt = DateTimeOffset.UtcNow;
    }

    public string InstanceId { get; }

    public DateTimeOffset StartedAt { get; }
}
