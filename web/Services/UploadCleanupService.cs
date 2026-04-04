namespace Audio2Timeline.Web.Services;

public sealed class UploadCleanupService(RunStore runStore, ILogger<UploadCleanupService> logger) : BackgroundService
{
    private static readonly TimeSpan CleanupInterval = TimeSpan.FromMinutes(2);
    private static readonly TimeSpan UploadRetention = TimeSpan.FromMinutes(10);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(CleanupInterval);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var deletedCount = await runStore.CleanupExpiredUploadsAsync(UploadRetention, stoppingToken);
                if (deletedCount > 0)
                {
                    logger.LogInformation("Deleted {DeletedCount} expired upload cache folder(s).", deletedCount);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Upload cleanup failed.");
            }

            await timer.WaitForNextTickAsync(stoppingToken);
        }
    }
}
