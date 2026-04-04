using System.Text.Json;
using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

public sealed class WorkerCapabilityService(AppPaths paths)
{
    private readonly JsonSerializerOptions _jsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public async Task<WorkerCapabilitySnapshot> GetAsync(CancellationToken cancellationToken = default)
    {
        if (!File.Exists(paths.WorkerCapabilitiesPath))
        {
            return new WorkerCapabilitySnapshot
            {
                Message = "Worker capability report is not available yet.",
            };
        }

        await using var stream = File.OpenRead(paths.WorkerCapabilitiesPath);
        return await JsonSerializer.DeserializeAsync<WorkerCapabilitySnapshot>(
                   stream,
                   _jsonOptions,
                   cancellationToken)
               ?? new WorkerCapabilitySnapshot
               {
                   Message = "Worker capability report could not be read.",
               };
    }
}
